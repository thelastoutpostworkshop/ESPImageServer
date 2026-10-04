"""Creation Gallery identities follow the JPEG actually saved to a display."""

import hashlib
from io import BytesIO
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from esp_image_server.app import create_app, embed_jpeg_metadata, extract_jpeg_metadata
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_registry import DisplayRegistry
from esp_image_server.image_library import ImageLibrary


class PatternGenerator:
    """Exercise the production JPEG/assignment paths without loading a model."""

    device = "cuda"
    ready = False

    def activate_model(self, settings, progress=None):
        self.ready = True

    def unload(self):
        self.ready = False

    def generate(self, prompt, width=None, height=None, **kwargs):
        image = Image.new("RGB", (160, 96), "navy")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 60, 40), fill="orange")
        draw.polygon([(40, 90), (150, 30), (120, 90)], fill="lime")
        return image


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))

    def factory():
        library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
        app = create_app(
            Settings(output_width=160, output_height=96),
            PatternGenerator(),
            image_library=library,
            display_registry=DisplayRegistry(tmp_path / "displays.sqlite3"),
            app_settings_store=AppSettingsStore(tmp_path / "app_settings.json"),
            enable_mdns=False,
        )
        return app, library

    return factory


def register(client, hardware_id="first", width=480, height=272):
    response = client.post("/displays/register", json={
        "hardware_id": hardware_id,
        "name": hardware_id,
        "width": width,
        "height": height,
        "firmware_version": "1.1.39",
        "board_target": "JC4827W543",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def key(jpeg):
    return f"v1-{hashlib.sha256(jpeg).hexdigest()[:16]}"


def generate(client, display_ids=None, aspect_mode=None):
    payload = {"prompt": "a tiny robot"}
    if display_ids is not None:
        payload["display_ids"] = display_ids
    if aspect_mode is not None:
        payload["broadcast_aspect_mode"] = aspect_mode
    response = client.post("/generate", json=payload)
    assert response.status_code == 200, response.text
    return response.content


def remove_rendition_history(library):
    """Represent an index written by an app version predating this fix."""
    records = json.loads(library.index_path.read_text(encoding="utf-8"))
    for record in records:
        record.pop("source_sha256", None)
        record.pop("sd_card_rendition_keys", None)
    library.index_path.write_text(json.dumps(records), encoding="utf-8")


@pytest.mark.parametrize("aspect_mode", ["crop", "fit", "separate"])
def test_generated_save_latest_remembers_the_exact_command_key(application, aspect_mode):
    app, library = application()
    with TestClient(app) as client:
        display_id = register(client)
        generated = generate(client, [display_id], aspect_mode)
        response = client.post(f"/displays/{display_id}/display-commands/save-latest")
        assert response.status_code == 202, response.text
        command = response.json()
        assert command["content_key"] == key(generated)
        saved = client.get("/saved-images").json()[0]

    original = library.find_path(saved["id"]).read_bytes()
    assert saved["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert saved["sd_card_rendition_keys"] == [command["content_key"]]
    assert command["content_key"] in saved["sd_card_content_keys"]
    assert len(saved["sd_card_content_keys"]) == len(set(saved["sd_card_content_keys"]))


def test_changed_rotation_and_quality_renditions_survive_restart(application):
    app, library = application()
    with TestClient(app) as client:
        display_id = register(client)
        generate(client, [display_id])
        assert client.put(f"/displays/{display_id}/display-settings", json={"rotation": 90}).status_code == 200
        assert client.put("/app-settings", json={"jpeg_quality": 72}).status_code == 200
        latest = client.get(f"/displays/{display_id}/latest.jpg").content
        command = client.post(f"/displays/{display_id}/display-commands/save-latest").json()
        assert command["content_key"] == key(latest)
        assert client.put(f"/displays/{display_id}/display-settings", json={"rotation": 0}).status_code == 200
        assert client.put("/app-settings", json={"jpeg_quality": 85}).status_code == 200
        # A repeated save of the same source must merge, rather than replace,
        # identities for previously saved rotations and JPEG quality settings.
        second = client.post(f"/displays/{display_id}/display-commands/save-latest").json()
        assert second["content_key"] != command["content_key"]
        client.post(f"/displays/{display_id}/display-commands/save-latest")
        record = library.list()[0]
        original = library.find_path(record["id"]).read_bytes()

    restarted_app, restarted_library = application()
    with TestClient(restarted_app) as client:
        saved = client.get("/saved-images", params={"display_id": display_id}).json()[0]
    assert command["content_key"] in saved["sd_card_content_keys"]
    assert saved["sd_card_rendition_keys"] == [command["content_key"], second["content_key"]]
    assert restarted_library.find_path(record["id"]).read_bytes() == original


def test_new_target_fit_save_is_associated_by_full_source_identity(application):
    app, library = application()
    with TestClient(app) as client:
        first_id = register(client)
        second_id = register(client, "second", 172, 320)
        generate(client, [first_id])
        original_record = library.list()[0]
        original = library.find_path(original_record["id"]).read_bytes()
        metadata = extract_jpeg_metadata(original)
        other_image = BytesIO()
        Image.new("RGB", (160, 96), "red").save(other_image, format="JPEG")
        unrelated = library.save(embed_jpeg_metadata(other_image.getvalue(), metadata), metadata)

        response = client.post(f"/saved-images/{original_record['id']}/display", json={
            "display_ids": [second_id], "broadcast_aspect_mode": "fit",
        })
        assert response.status_code == 202, response.text
        assert client.put(f"/displays/{second_id}/display-settings", json={"rotation": 270}).status_code == 200
        actual = key(client.get(f"/displays/{second_id}/latest.jpg").content)
        command = client.post(f"/displays/{second_id}/display-commands/save-latest").json()
        assert command["content_key"] == actual
        records = {record["id"]: record for record in client.get("/saved-images").json()}

    assert actual in records[original_record["id"]]["sd_card_content_keys"]
    assert actual not in records[unrelated["id"]]["sd_card_content_keys"]
    assert "sd_card_rendition_keys" not in records[unrelated["id"]]


@pytest.mark.parametrize("registered", [False, True])
def test_already_saved_also_persists_rendition_identity(application, registered):
    app, library = application()
    with TestClient(app) as client:
        display_id = register(client) if registered else None
        generate(client, [display_id] if registered else None)
        if registered:
            assert client.put(f"/displays/{display_id}/display-settings", json={"rotation": 90}).status_code == 200
            prefix = f"/displays/{display_id}"
        else:
            assert client.put("/display-settings", json={"rotation": 90}).status_code == 200
            prefix = ""
        actual = key(client.get(f"{prefix}/latest.jpg").content)
        filename = f"esp-image-{actual}.jpg"
        report = client.post(f"{prefix}/display-sd-card/report", json={
            "available": True, "mode": "server_controlled", "verified_saves": True,
            "total_bytes": 1024, "used_bytes": 256,
            "files": [{"name": filename, "type": "image", "content_key": actual, "verified": True}],
        })
        assert report.status_code == 204, report.text
        response = client.post(f"{prefix}/display-commands/save-latest")
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "already_saved"
        assert response.json()["filename"] == filename
        saved = client.get("/saved-images").json()[0]

    assert saved["sd_card_rendition_keys"] == [actual]
    assert actual in saved["sd_card_content_keys"]
    assert library.list()[0]["sd_card_rendition_keys"] == [actual]


@pytest.mark.parametrize("aspect_mode", ["crop", "fit"])
def test_current_display_query_recovers_old_saves_with_missing_display_metadata(application, aspect_mode):
    app, library = application()
    with TestClient(app) as client:
        # No display was connected when this old creation was generated.
        generate(client)
        record = library.list()[0]
        assert record["metadata"]["display"] is None
        display_id = register(client, width=172, height=320)
        assert client.put(f"/displays/{display_id}/display-settings", json={"rotation": 90}).status_code == 200
        assert client.post(f"/saved-images/{record['id']}/display", json={
            "display_ids": [display_id], "broadcast_aspect_mode": aspect_mode,
        }).status_code == 202
        actual = key(client.get(f"/displays/{display_id}/latest.jpg").content)
        remove_rendition_history(library)
        before = client.get("/saved-images").json()[0]
        recovered = client.get("/saved-images", params={"display_id": display_id})
        assert recovered.status_code == 200, recovered.text
        after = recovered.json()[0]
        assert client.get("/saved-images", params={"display_id": "missing"}).status_code == 404

    assert actual not in before["sd_card_content_keys"]
    assert actual in after["sd_card_content_keys"]
    assert after["sd_card_content_key"] == before["sd_card_content_key"]
    assert "sd_card_rendition_keys" not in library.list()[0]


def test_old_separate_generation_uses_crop_for_its_first_rendition(application):
    app, library = application()
    with TestClient(app) as client:
        display_id = register(client)
        generated = generate(client, [display_id], "separate")
        remove_rendition_history(library)
        saved = client.get("/saved-images").json()[0]
    assert saved["metadata"]["broadcast_aspect_mode"] == "separate"
    assert key(generated) in saved["sd_card_content_keys"]


def test_legacy_source_hash_is_backfilled_and_stale_renditions_are_not_reused(application):
    app, library = application()
    with TestClient(app) as client:
        generate(client)
        record = library.list()[0]
        source_path = library.find_path(record["id"])
        original = source_path.read_bytes()
        remove_rendition_history(library)
        assert client.put("/display-settings", json={"rotation": 90}).status_code == 200
        actual = key(client.get("/latest.jpg").content)
        command = client.post("/display-commands/save-latest").json()
        assert command["content_key"] == actual
        saved = client.get("/saved-images").json()[0]
        assert saved["source_sha256"] == hashlib.sha256(original).hexdigest()
        assert saved["sd_card_rendition_keys"] == [actual]
        assert actual in saved["sd_card_content_keys"]

        changed = BytesIO()
        Image.new("RGB", (160, 96), "red").save(changed, format="JPEG")
        source_path.write_bytes(embed_jpeg_metadata(changed.getvalue(), extract_jpeg_metadata(original)))
        replaced = client.get("/saved-images").json()[0]

    assert actual not in replaced["sd_card_content_keys"]


def test_legacy_lookup_skips_unrelated_file_bytes_and_backfills_only_matches(application, monkeypatch):
    app, library = application()
    with TestClient(app) as client:
        generate(client)
        original_record = library.list()[0]
        source = library.find_path(original_record["id"]).read_bytes()
        other_image = BytesIO()
        Image.new("RGB", (64, 64), "red").save(other_image, format="JPEG")
        unrelated = library.save(other_image.getvalue(), original_record["metadata"])
        unrelated_path = library.find_path(unrelated["id"])
        assert unrelated_path.stat().st_size != len(source)
        # Change a JPEG quantization coefficient without changing its length
        # or embedded generation metadata. Equal lengths are only a filter;
        # this file must still be rejected by the complete source hash.
        different_source = bytearray(source)
        coefficient = source.index(b"\xff\xdb") + 5
        different_source[coefficient] += 1
        same_length = library.save(bytes(different_source), original_record["metadata"])
        same_length_path = library.find_path(same_length["id"])
        assert extract_jpeg_metadata(bytes(different_source)) == extract_jpeg_metadata(source)
        remove_rendition_history(library)

        read_bytes = Path.read_bytes
        files_read = []

        def guarded_read(path):
            assert path != unrelated_path, "An unrelated legacy image must not be read"
            files_read.append(path)
            return read_bytes(path)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", guarded_read)
            response = client.post("/display-commands/save-latest")
            assert response.status_code == 202, response.text

    records = {record["id"]: record for record in library.list()}
    assert records[original_record["id"]]["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert records[original_record["id"]]["sd_card_rendition_keys"] == [response.json()["content_key"]]
    assert "source_sha256" not in records[unrelated["id"]]
    assert "sd_card_rendition_keys" not in records[unrelated["id"]]
    assert same_length_path in files_read
    assert "source_sha256" not in records[same_length["id"]]
    assert "sd_card_rendition_keys" not in records[same_length["id"]]
