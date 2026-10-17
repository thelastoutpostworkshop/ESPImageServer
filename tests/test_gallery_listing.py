"""Gallery endpoints return the whole saved library before client-side filters."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app import create_app
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_registry import DisplayRegistry
from esp_image_server.image_library import ImageLibrary


AMOLED_NAME = "AMOLED gallery display"


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))

    def unexpected(*args, **kwargs):
        raise AssertionError("Gallery listing must not generate media or call FFmpeg")

    jpeg_buffer = BytesIO()
    Image.new("RGB", (8, 8), "navy").save(jpeg_buffer, format="JPEG")
    jpeg = jpeg_buffer.getvalue()
    # These regressions exercise listing and file existence, not resizing.
    monkeypatch.setattr("esp_image_server.app.to_display_jpeg", lambda *args, **kwargs: jpeg)
    monkeypatch.setattr("esp_image_server.app.bundled_ffmpeg_executable", unexpected)
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", unexpected)
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    library.path.mkdir()
    registry = DisplayRegistry(tmp_path / "displays.sqlite3")
    display = registry.register(
        "gallery-amoled", AMOLED_NAME, 466, 466, "1.1.45",
        board_target="ESP32_S3_AMOLED_143",
    )
    app = create_app(
        Settings(), SimpleNamespace(device="cpu", ready=False, load=unexpected, generate=unexpected),
        image_library=library,
        display_registry=registry,
        app_settings_store=AppSettingsStore(tmp_path / "settings.json"),
        enable_mdns=False,
    )
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, library=library, display_id=display.id, jpeg=jpeg)


def image_records(gallery, count):
    records = []
    for index in range(count):
        # Only one AMOLED image falls within the newest fifty. Fourteen older
        # AMOLED records reproduce the display-filter count mismatch.
        name = AMOLED_NAME if index == 0 or index >= count - 14 else "Other gallery display"
        record = {
            "id": f"image-{index:03d}",
            "filename": f"image-{index:03d}.jpg",
            "created_at": (datetime(2026, 10, 17, tzinfo=UTC) - timedelta(seconds=index)).isoformat(),
            "metadata": {"display": {"name": name}, "rotation": 90},
        }
        (gallery.library.path / record["filename"]).write_bytes(gallery.jpeg)
        records.append(record)
    gallery.library.index_path.write_text(json.dumps(records), encoding="utf-8")
    return records


def test_saved_images_returns_all_87_files_including_older_display_creations(gallery):
    records = image_records(gallery, 87)
    assert len(list(gallery.library.path.glob("*.jpg"))) == 87
    assert sum(record["metadata"]["display"]["name"] == AMOLED_NAME for record in records[:50]) == 1
    for params in ({}, {"display_id": gallery.display_id}):
        response = gallery.client.get("/saved-images", params=params)
        assert response.status_code == 200, response.text
        returned = response.json()
        assert [item["id"] for item in returned] == [record["id"] for record in records]
        assert sum(item["metadata"]["display"]["name"] == AMOLED_NAME for item in returned) == 15
        assert all(item["sd_card_content_key"] in item["sd_card_content_keys"] for item in returned)


def test_saved_images_skips_missing_files_without_truncating_older_valid_records(gallery):
    records = image_records(gallery, 65)
    # Stale entries can remain after files are removed outside the app.
    for record in (records[0], records[54]):
        (gallery.library.path / record["filename"]).unlink()
    expected = [record["id"] for record in records if record not in (records[0], records[54])]
    assert len(expected) == len(list(gallery.library.path.glob("*.jpg"))) == 63
    for params in ({}, {"display_id": gallery.display_id}):
        response = gallery.client.get("/saved-images", params=params)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == expected
        assert response.json()[-1]["id"] == records[-1]["id"]


def test_saved_videos_returns_more_than_50_files_and_skips_missing_media(gallery):
    library = gallery.app.state.video_library
    library.path.mkdir()
    records = []
    for index in range(65):
        record = {
            "id": f"video-{index:03d}",
            "filename": f"video-{index:03d}.mp4",
            "thumbnail_filename": "",
            "created_at": (datetime(2026, 10, 17, tzinfo=UTC) - timedelta(seconds=index)).isoformat(),
            "metadata": {"display": {"name": AMOLED_NAME}, "rotation": 270},
        }
        (library.path / record["filename"]).write_bytes(b"fixture MP4 bytes; no playback requested")
        (library.path / f"video-{index:03d}.json").write_text(json.dumps(record), encoding="utf-8")
        records.append(record)
    (library.path / records[0]["filename"]).unlink()
    assert len(list(library.path.glob("*.mp4"))) == 64
    response = gallery.client.get("/saved-videos")
    assert response.status_code == 200, response.text
    assert response.json() == records[1:]
