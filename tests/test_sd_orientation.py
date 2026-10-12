"""SD playback filters describe the exact pixels saved, including queued saves."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from esp_image_server.app import create_app, embed_jpeg_metadata
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_commands import DisplayCommandStore
from esp_image_server.display_registry import DisplayRegistry
from esp_image_server.image_library import ImageLibrary
from esp_image_server.image_processor import to_display_jpeg
from esp_image_server.retention import RetentionPolicy
from esp_image_server.sd_orientation import sd_media_rotation


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    monkeypatch.setattr("esp_image_server.app.bundled_ffmpeg_executable", lambda: "bundled-ffmpeg")
    app = create_app(
        Settings(output_width=64, output_height=96),
        SimpleNamespace(device="cpu", ready=False),
        image_library=ImageLibrary(tmp_path / "images", tmp_path / "index.json"),
        display_registry=DisplayRegistry(tmp_path / "displays.sqlite3"),
        app_settings_store=AppSettingsStore(tmp_path / "settings.json"),
        enable_mdns=False,
    )
    with TestClient(app) as client:
        yield app, client


def register(client, hardware_id="desk"):
    response = client.post("/displays/register", json={
        "hardware_id": hardware_id, "name": hardware_id, "width": 240, "height": 320,
        "firmware_version": "1.1.44", "board_target": "CHEAP_YELLOW_DISPLAY",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def board_prefix(client, registered):
    if registered:
        return f"/displays/{register(client)}"
    assert client.post("/display", json={
        "name": "CYD", "width": 240, "height": 320, "firmware_version": "1.1.44",
    }).status_code == 201
    return ""


def pattern_jpeg():
    source = Image.new("RGB", (120, 80), "navy")
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 40, 25), fill="orange")
    draw.polygon([(65, 65), (110, 45), (110, 75)], fill="lime")
    jpeg = BytesIO()
    source.save(jpeg, "JPEG", quality=95)
    # A generation preference on master artwork is not its pixel rotation.
    return embed_jpeg_metadata(jpeg.getvalue(), {"rotation": 270, "prompt": "pattern"})


def report(client, prefix, **values):
    response = client.post(prefix + "/display-sd-card/report", json={
        "available": True, "mode": "server_controlled", "total_bytes": 100_000,
        "used_bytes": 0, "files": [], **values,
    })
    assert response.status_code == 204, response.text


@pytest.mark.parametrize("registered", [False, True])
def test_filter_starts_disabled_and_round_trips_confirmed_board_settings(application, registered):
    _, client = application
    prefix = board_prefix(client, registered)
    initial = client.get(prefix + "/display-experience").json()
    assert initial["orientation_filter_enabled"] is False
    assert initial["orientation_rotation"] == 0
    settings = {"offline_experience": "slideshow", "slideshow_interval_ms": 15000,
                "slideshow_order": "newest_first"}
    defaults = client.put(prefix + "/display-experience", json=settings)
    assert defaults.status_code == 202
    assert defaults.json()["orientation_filter_enabled"] is False
    assert defaults.json()["orientation_rotation"] == 0
    for experience in ("slideshow", "video_loop"):
        for rotation in (0, 90, 180, 270):
            selected = {**settings, "offline_experience": experience,
                        "orientation_filter_enabled": True, "orientation_rotation": rotation}
            for method, endpoint, command_type in (
                (client.put, "/display-experience", "set_display_experience"),
                (client.post, "/display-experience/preview", "preview_display_experience"),
            ):
                response = method(prefix + endpoint, json=selected)
                assert response.status_code == 202, response.text
                assert response.json()["type"] == command_type
                assert response.json()["orientation_filter_enabled"] is True
                assert response.json()["orientation_rotation"] == rotation
            report(client, prefix, **selected, offline_experience_saved=True)
            actual = client.get(prefix + "/display-experience").json()
            assert actual["orientation_filter_enabled"] is True
            assert actual["orientation_rotation"] == rotation


@pytest.mark.parametrize("rotation", [-90, 45, 360, "90", 90.0, True, None])
def test_only_exact_quarter_turn_angles_are_accepted(application, rotation):
    _, client = application
    prefix = f"/displays/{register(client)}"
    settings = {"offline_experience": "slideshow", "slideshow_interval_ms": 15000,
                "slideshow_order": "newest_first", "orientation_rotation": rotation}
    for method, endpoint in ((client.put, "/display-experience"), (client.post, "/display-experience/preview")):
        assert method(prefix + endpoint, json=settings).status_code == 422
    assert client.post(prefix + "/display-sd-card/report", json={
        "available": True, "mode": "server_controlled", "total_bytes": 1000,
        "used_bytes": 0, "orientation_rotation": rotation,
    }).status_code == 422


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_latest_save_freezes_pixels_and_used_rotation(application, registered, rotation):
    app, client = application
    prefix = board_prefix(client, registered)
    source = pattern_jpeg()
    app.state.latest_image_store.set(source)
    assert client.put(prefix + "/display-settings", json={"rotation": rotation}).status_code == 200
    latest = client.get(prefix + "/latest.jpg").content
    queued = client.post(prefix + "/display-commands/save-latest")
    assert queued.status_code == 202, queued.text
    command = queued.json()
    assert sd_media_rotation(command["filename"]) == rotation
    assert command["orientation_rotation"] == rotation
    assert command["content_key"] == f"v1-{sha256(latest).hexdigest()[:16]}"
    assert client.get(command["image_url"]).content == latest
    assert Image.open(BytesIO(latest)).size == (240, 320)
    # The file advertised to the board cannot change while queued/downloaded.
    client.put(prefix + "/display-settings", json={"rotation": (rotation + 90) % 360})
    client.put("/app-settings", json={"jpeg_quality": 50})
    app.state.latest_image_store.set(b"another source must not be read")
    snapshot = client.get(command["image_url"])
    assert snapshot.status_code == 200 and snapshot.content == latest
    other_id = register(client, "other")
    assert client.get(f"/displays/{other_id}/display-commands/{command['id']}/image").status_code == 404
    assert client.get(prefix + "/display-commands/missing/image").status_code == 404


@pytest.mark.parametrize("enabled", ["true", "false", 0, 1, None])
def test_orientation_filter_requires_an_explicit_boolean(application, enabled):
    _, client = application
    prefix = f"/displays/{register(client)}"
    settings = {"offline_experience": "slideshow", "slideshow_interval_ms": 15000,
                "slideshow_order": "newest_first", "orientation_filter_enabled": enabled}
    for method, endpoint in ((client.put, "/display-experience"), (client.post, "/display-experience/preview")):
        assert method(prefix + endpoint, json=settings).status_code == 422
    assert client.post(prefix + "/display-sd-card/report", json={
        "available": True, "mode": "server_controlled", "total_bytes": 1000,
        "used_bytes": 0, "orientation_filter_enabled": enabled,
    }).status_code == 422


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_gallery_save_keeps_creation_rotation_despite_current_board_preference(application, registered, rotation):
    app, client = application
    prefix = board_prefix(client, registered)
    source = pattern_jpeg()
    image = app.state.image_library.save(source, {"rotation": rotation})
    client.put(prefix + "/display-settings", json={"rotation": (rotation + 90) % 360})
    response = client.post(prefix + f"/display-commands/save-saved-image/{image['id']}")
    assert response.status_code == 202, response.text
    command = response.json()
    with Image.open(BytesIO(source)) as artwork:
        expected = to_display_jpeg(artwork, width=240, height=320, rotation=rotation, quality=85)
    actual = client.get(command["image_url"]).content
    assert actual == expected
    assert command["content_key"] == f"v1-{sha256(actual).hexdigest()[:16]}"
    assert sd_media_rotation(command["filename"]) == rotation
    assert app.state.image_library.find_path(image["id"]).read_bytes() == source
    assert command["content_key"] in app.state.image_library.list()[0]["sd_card_rendition_keys"]
    client.put(prefix + "/display-settings", json={"rotation": (rotation + 90) % 360})
    assert client.get(command["image_url"]).content == expected


@pytest.mark.parametrize("metadata", [
    {}, {"rotation": None}, {"rotation": True}, {"rotation": "90"},
    {"rotation": 90.0}, {"rotation": 45}, {"rotation": 360},
])
def test_gallery_sd_save_rejects_missing_or_invalid_recorded_orientation(application, metadata):
    app, client = application
    prefix = f"/displays/{register(client)}"
    image = app.state.image_library.save(pattern_jpeg(), metadata)
    response = client.post(prefix + f"/display-commands/save-saved-image/{image['id']}")
    assert response.status_code == 422
    assert "valid recorded orientation" in response.json()["detail"]
    assert client.get(prefix + "/display-commands/next").status_code == 204


@pytest.mark.parametrize("metadata,rotation", [
    ({"rotation": 0}, 0), ({"rotation": 90}, 90), ({"rotation": 180}, 180),
    ({"rotation": 270}, 270), ({"source_display": {"rotation": 90}}, None),
    ({}, None), ({"rotation": 45}, None), ({"rotation": "90"}, None),
    ({"rotation": True}, None), ({"rotation": None}, None),
])
def test_video_save_labels_existing_pixels_without_using_current_video_preference(application, tmp_path, metadata, rotation):
    app, client = application
    prefix = f"/displays/{register(client)}"
    source = tmp_path / "video.mp4"
    source.write_bytes(b"already rotated video; no generation or conversion needed to queue")
    video = app.state.video_library.save(source, {"fps": 12, **metadata})
    client.put(prefix + "/video-display-settings", json={"rotation": 270})
    response = client.post(prefix + f"/display-commands/save-saved-video/{video['id']}")
    assert response.status_code == 202, response.text
    command = response.json()
    assert sd_media_rotation(command["filename"]) == rotation
    assert command.get("orientation_rotation") == rotation
    assert command["filename"].endswith(f"-v1-{video['id']}-240x320-fps12.mjpeg")
    assert command["content_key"] == f"v1-{video['id']}-240x320-fps12"


@pytest.mark.parametrize("reported_rotation,expected", [(None, "pending"), (0, "pending"), (90, "already_saved")])
def test_same_pixels_at_different_or_unknown_angles_do_not_skip_required_save(application, reported_rotation, expected):
    app, client = application
    prefix = f"/displays/{register(client)}"
    app.state.latest_image_store.set(pattern_jpeg())
    client.put(prefix + "/display-settings", json={"rotation": 90})
    jpeg = client.get(prefix + "/latest.jpg").content
    content_key = f"v1-{sha256(jpeg).hexdigest()[:16]}"
    marker = f"-r{reported_rotation}" if reported_rotation is not None else ""
    filename = f"esp-image-20261012-120000{marker}-{content_key}.jpg"
    report(client, prefix, files=[{"name": filename, "type": "image", "content_key": content_key, "verified": True}])
    result = client.post(prefix + "/display-commands/save-latest").json()
    assert result["status"] == expected
    if expected == "already_saved":
        assert result["filename"] == filename
    else:
        assert sd_media_rotation(result["filename"]) == 90


def test_inventory_reports_only_explicit_valid_filename_orientation(application):
    _, client = application
    prefix = f"/displays/{register(client)}"
    names = [
        "esp-image-20261012-120000-r90-v1-0123456789abcdef.jpg",
        "esp-video-20261012-120000-r270-v1-0123456789abcdef-240x320-fps15.mjpeg",
        "esp-image-20261012-120000-v1-0123456789abcdef.jpg",
        "imported-r90.jpg", "esp-image-20261012-120000-r45-v1-0123456789abcdef.jpg",
        "esp-image-２０２６１０１２-120000-r90-v1-0123456789abcdef.jpg",
        "esp-video-20261012-120000-r90-v1-" + "a" * 160 + "-240x320-fps15.mjpeg",
        "folder/esp-image-20261012-120000-r90-v1-0123456789abcdef.jpg",
    ]
    report(client, prefix, files=[{"name": name, "orientation_rotation": 0} for name in names])
    files = client.get(prefix + "/display-sd-card").json()["files"]
    assert [file["orientation_rotation"] for file in files] == [90, 270, None, None, None, None, None, None]


def test_image_snapshots_share_command_retention_and_active_protection():
    store = DisplayCommandStore(RetentionPolicy(max_items=20, max_age_seconds=60, max_bytes=1024))
    first = store.queue_save("one.jpg", image_jpeg=b"a" * 800)
    store.acknowledge(first["id"], True, "saved")
    second = store.queue_save("two.jpg", image_jpeg=b"b" * 800)
    store.acknowledge(second["id"], True, "saved")
    assert store.image_snapshot(first["id"]) is None
    pending = store.queue_save("active.jpg", image_jpeg=b"c" * 2000)
    store.prune_completed(now=10_000_000_000)
    assert store.image_snapshot(pending["id"]) == b"c" * 2000
    assert store.image_snapshot(second["id"]) is None


def eventually(read, predicate):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        sleep(0.005)
    raise AssertionError("Bulk SD-card save did not reach the expected state")


def test_bulk_image_save_has_native_orientation_snapshot_and_owned_command(application):
    app, client = application
    prefix = f"/displays/{register(client)}"
    source = pattern_jpeg()
    image = app.state.image_library.save(source, {"rotation": 270})
    client.put(prefix + "/display-settings", json={"rotation": 90})
    batch = client.post(prefix + "/sd-card-save-batches", json={"items": [{"id": image["id"], "type": "image"}]}).json()
    refresh = client.get(prefix + "/display-commands/next").json()
    assert refresh["type"] == "refresh_sd_card"
    client.post(prefix + f"/display-commands/{refresh['id']}/ack", json={"success": True})
    report(client, prefix)
    response = eventually(lambda: client.get(prefix + "/display-commands/next"), lambda r: r.status_code == 200)
    command = response.json()
    assert command["type"] == "save_saved_image"
    assert command["bulk_save_id"] == batch["id"]
    assert sd_media_rotation(command["filename"]) == 270
    snapshot = client.get(command["image_url"]).content
    with Image.open(BytesIO(source)) as artwork:
        expected = to_display_jpeg(artwork, width=240, height=320, rotation=270, quality=85)
    assert snapshot == expected
    client.put(prefix + "/display-settings", json={"rotation": 0})
    assert client.get(command["image_url"]).content == expected
    client.post(prefix + f"/display-commands/{command['id']}/ack", json={"success": True})
    finished = eventually(lambda: client.get(prefix + f"/sd-card-save-batches/{batch['id']}").json(), lambda b: b["status"] == "complete")
    assert finished["saved"] == 1


def test_bulk_save_preserves_portrait_and_landscape_creations_on_the_same_board(application):
    app, client = application
    prefix = f"/displays/{register(client)}"
    client.put(prefix + "/display-settings", json={"rotation": 90})
    creations = []
    for rotation, size, color in [(0, (80, 120), "red"), (0, (80, 120), "green"), (90, (120, 80), "blue")]:
        source = Image.new("RGB", size, color)
        ImageDraw.Draw(source).rectangle((0, 0, 20, 30), fill="yellow")
        jpeg = BytesIO()
        source.save(jpeg, "JPEG", quality=95)
        record = app.state.image_library.save(jpeg.getvalue(), {"rotation": rotation})
        with Image.open(BytesIO(jpeg.getvalue())) as artwork:
            expected = to_display_jpeg(artwork, width=240, height=320, rotation=rotation, quality=85)
        creations.append((record, rotation, expected))

    batch_response = client.post(prefix + "/sd-card-save-batches", json={
        "items": [{"id": record["id"], "type": "image"} for record, _, _ in creations],
    })
    assert batch_response.status_code == 202, batch_response.text
    batch = batch_response.json()
    refresh = client.get(prefix + "/display-commands/next").json()
    assert refresh["type"] == "refresh_sd_card"
    client.post(prefix + f"/display-commands/{refresh['id']}/ack", json={"success": True})
    report(client, prefix)

    files = []
    for _, rotation, expected in creations:
        response = eventually(lambda: client.get(prefix + "/display-commands/next"), lambda r: r.status_code == 200)
        command = response.json()
        assert command["type"] == "save_saved_image"
        assert command["orientation_rotation"] == rotation
        assert sd_media_rotation(command["filename"]) == rotation
        assert client.get(command["image_url"]).content == expected
        files.append({"name": command["filename"], "type": "image",
                      "content_key": command["content_key"], "verified": True})
        client.post(prefix + f"/display-commands/{command['id']}/ack", json={"success": True})

    finished = eventually(lambda: client.get(prefix + f"/sd-card-save-batches/{batch['id']}").json(),
                          lambda value: value["status"] == "complete")
    assert finished["saved"] == 3
    report(client, prefix, files=files)
    inventory = client.get(prefix + "/display-sd-card").json()["files"]
    assert [item["orientation_rotation"] for item in inventory].count(0) == 2
    assert [item["orientation_rotation"] for item in inventory].count(90) == 1
