"""Manual gallery saves retain upright artwork and its captured orientation."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from esp_image_server.app import create_app, embed_jpeg_metadata, extract_jpeg_metadata
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_registry import DisplayRegistry
from esp_image_server.image_library import ImageLibrary
from esp_image_server.image_processor import to_display_jpeg
from esp_image_server.sd_orientation import sd_media_rotation


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    app = create_app(
        Settings(), SimpleNamespace(device="cpu", ready=False),
        image_library=ImageLibrary(tmp_path / "images", tmp_path / "index.json"),
        display_registry=DisplayRegistry(tmp_path / "displays.sqlite3"),
        app_settings_store=AppSettingsStore(tmp_path / "settings.json"),
        enable_mdns=False,
    )
    with TestClient(app) as client:
        response = client.post("/displays/register", json={
            "hardware_id": "manual-gallery", "name": "CYD", "width": 240, "height": 320,
            "firmware_version": "1.1.44", "board_target": "CHEAP_YELLOW_DISPLAY",
        })
        assert response.status_code == 201, response.text
        yield app, client, f"/displays/{response.json()['id']}"


COLORS = [(230, 30, 20), (20, 220, 30), (20, 35, 230), (225, 190, 25)]


def asymmetric_artwork(rotation):
    width, height = (320, 240) if rotation in (90, 270) else (240, 320)
    artwork = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(artwork)
    for box, color in zip([
        (0, 0, width // 2 - 1, height // 2 - 1),
        (width // 2, 0, width - 1, height // 2 - 1),
        (0, height // 2, width // 2 - 1, height - 1),
        (width // 2, height // 2, width - 1, height - 1),
    ], COLORS):
        draw.rectangle(box, fill=color)
    return artwork


def quarter_colors(image):
    return [image.getpixel((image.width * x // 4, image.height * y // 4))
            for x, y in ((1, 1), (3, 1), (1, 3), (3, 3))]


def assert_colors(actual, expected):
    for actual_color, expected_color in zip(actual, expected):
        assert max(abs(a - e) for a, e in zip(actual_color, expected_color)) <= 12


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_manual_gallery_save_unrotates_preview_before_sd_save(application, rotation):
    app, client, prefix = application
    artwork = asymmetric_artwork(rotation)
    metadata = {"rotation": rotation, "prompt": "four different colored corners",
                "display": {"name": "CYD", "width": 240, "height": 320}}
    rendered = to_display_jpeg(artwork, width=240, height=320, rotation=rotation, quality=85)
    uploaded = embed_jpeg_metadata(rendered, metadata)
    # The board preference is for the next generation, independently of this JPEG.
    client.put(prefix + "/display-settings", json={"rotation": (rotation + 90) % 360})
    response = client.post("/creation-library/images", content=uploaded, headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["metadata"] == metadata
    stored = app.state.image_library.find_path(record["id"]).read_bytes()
    assert extract_jpeg_metadata(stored) == metadata
    if rotation == 0:
        assert stored == uploaded
    with Image.open(BytesIO(stored)) as saved_artwork:
        assert saved_artwork.size == artwork.size
        assert_colors(quarter_colors(saved_artwork), COLORS)
        expected_sd = to_display_jpeg(saved_artwork, width=240, height=320, rotation=rotation, quality=85)
    saved = client.post(prefix + f"/display-commands/save-saved-image/{record['id']}")
    assert saved.status_code == 202, saved.text
    command = saved.json()
    assert command["orientation_rotation"] == rotation
    assert sd_media_rotation(command["filename"]) == rotation
    snapshot = client.get(command["image_url"]).content
    assert snapshot == expected_sd
    with Image.open(BytesIO(snapshot)) as display_copy, Image.open(BytesIO(rendered)) as original_preview:
        assert display_copy.size == (240, 320)
        assert_colors(quarter_colors(display_copy), quarter_colors(original_preview))
    assert app.state.image_library.find_path(record["id"]).read_bytes() == stored


@pytest.mark.parametrize("metadata", [
    {}, {"rotation": None}, {"rotation": True}, {"rotation": "90"},
    {"rotation": 90.0}, {"rotation": 45}, {"rotation": 360},
])
def test_manual_gallery_save_rejects_missing_or_invalid_orientation(application, metadata):
    app, client, _ = application
    jpeg = to_display_jpeg(asymmetric_artwork(0), width=240, height=320, rotation=0, quality=85)
    uploaded = embed_jpeg_metadata(jpeg, metadata)
    response = client.post("/creation-library/images", content=uploaded, headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 422
    assert "valid recorded orientation" in response.json()["detail"]
    assert app.state.image_library.list() == []


def test_manual_gallery_save_reports_invalid_preview_bytes(application):
    app, client, _ = application
    uploaded = embed_jpeg_metadata(b"\xff\xd8invalid JPEG pixels", {"rotation": 90})
    response = client.post("/creation-library/images", content=uploaded, headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 422
    assert "Could not save image artwork" in response.json()["detail"]
    assert app.state.image_library.list() == []
