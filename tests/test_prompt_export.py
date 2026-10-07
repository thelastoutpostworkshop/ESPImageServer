from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from esp_image_server.app import create_app
from esp_image_server.config import Settings
from esp_image_server.image_library import ImageLibrary
from esp_image_server.prompt_export import format_gallery_prompts


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))


def record(metadata, *, filename="creation.jpg", created_at="2026-01-01T00:00:00Z"):
    return {"id": filename, "filename": filename, "created_at": created_at, "metadata": metadata}


def test_export_preserves_saved_settings_zero_values_unicode_and_multiline_text():
    image = record({
        "model": {"name": "DreamShaper 8", "id": "Lykon/dreamshaper-8"},
        "prompt": "A café at dusk\n雨の中の猫 🎨",
        "negative_prompt": "blurry\nlow contrast",
        "steps": 0, "seed": 0,
        "display": {"width": 240, "height": 320}, "rotation": 90,
    })
    exported = format_gallery_prompts([image], [], exported_at=datetime(2026, 10, 7, 15, 30, tzinfo=UTC))
    assert "Exported: 2026-10-07 15:30:00 UTC" in exported
    assert "Model: DreamShaper 8 (Lykon/dreamshaper-8)" in exported
    assert "Orientation: Landscape (320 x 240)" in exported
    assert "Rotation: 90° clockwise" in exported
    assert "Steps: 0\nSeed: 0" in exported
    assert "Prompt:\nA café at dusk\n雨の中の猫 🎨\nNegative prompt:\nblurry\nlow contrast" in exported


@pytest.mark.parametrize(("width", "height", "rotation", "orientation", "rotation_label"), [
    (240, 320, 0, "Portrait (240 x 320)", "Normal (0°)"),
    (480, 272, 90, "Portrait (272 x 480)", "90° clockwise"),
    (240, 320, 180, "Portrait (240 x 320)", "180°"),
    (240, 320, 270, "Landscape (320 x 240)", "90° counter-clockwise (270°)"),
    (466, 466, 90, "Square (466 x 466)", "90° clockwise"),
])
def test_export_orientation_uses_saved_native_dimensions_and_rotation(width, height, rotation, orientation, rotation_label):
    exported = format_gallery_prompts([record({"display": {"width": width, "height": height}, "rotation": rotation})], [])
    assert f"Orientation: {orientation}" in exported
    assert f"Rotation: {rotation_label}" in exported


@pytest.mark.parametrize("metadata", [{}, {"display": {"width": 240, "height": 320}}, {"display": {"width": 240}, "rotation": 0}])
def test_export_does_not_invent_missing_orientation(metadata):
    exported = format_gallery_prompts([record(metadata)], [])
    assert "Orientation: Not recorded" in exported


def test_export_missing_legacy_fields_and_authoritative_empty_negative_prompt():
    exported = format_gallery_prompts([
        record({"model": {"id": "legacy-model"}, "negativePrompt": "old wording"}, filename="legacy.jpg"),
        record({"model_name": "Saved model", "negative_prompt": "", "negativePrompt": "stale wording"}, filename="empty.jpg"),
        record(None, filename="missing.jpg"),
    ], [])
    assert "Model: legacy-model" in exported
    assert "Model: Saved model" in exported
    assert "Negative prompt:\nold wording" in exported
    assert "stale wording" not in exported
    assert exported.count("Negative prompt:\nNone") == 2
    assert exported.count("Steps: Not recorded\nSeed: Not recorded\nPrompt:\nNot recorded") == 3


def test_export_combines_images_and_videos_in_saved_creation_order():
    exported = format_gallery_prompts(
        [record({"prompt": "older image"}, filename="older.jpg")],
        [record({"prompt": "newer video"}, filename="newer.mp4", created_at="2026-10-07T00:00:00Z")],
    )
    assert "Saved items: 2" in exported
    assert exported.index("1. Video: newer.mp4") < exported.index("2. Image: older.jpg")


def test_image_library_unbounded_listing_has_no_ten_thousand_record_ceiling(tmp_path, monkeypatch):
    library = ImageLibrary(tmp_path / "images", tmp_path / "index.json")
    records = [record({"prompt": f"prompt {index}"}, filename=f"{index}.jpg") for index in range(10_001)]
    monkeypatch.setattr(library, "_read_index", lambda: records)
    assert len(library.list()) == 50
    assert len(library.list(limit=None)) == 10_001


def test_export_endpoint_reads_all_saved_sources_fresh_and_ignores_current_settings(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Prompt export must not load a model or call FFmpeg")

    monkeypatch.setattr("esp_image_server.app.bundled_ffmpeg_executable", unexpected)
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", unexpected)
    generator = SimpleNamespace(device="cpu", ready=False, load=unexpected, generate=unexpected)
    app = create_app(Settings(), generator, enable_mdns=False)
    library = app.state.image_library
    videos = app.state.video_library
    videos.path.mkdir(parents=True, exist_ok=True)
    for index in range(55):
        library.save(b"saved JPEG bytes", {
            "prompt": f"saved image prompt {index}", "steps": index, "seed": index,
            "model": {"name": "Saved image model", "id": "saved-image-model"},
            "display": {"width": 240, "height": 320}, "rotation": 90,
        })
        video_record = record({
            "prompt": f"saved video prompt {index}", "steps": index, "seed": index,
            "model": {"id": "saved-video-model"},
            "display": {"width": 480, "height": 272}, "rotation": 270,
        }, filename=f"video-{index}.mp4")
        (videos.path / video_record["filename"]).write_bytes(b"saved MP4 bytes")
        (videos.path / f"video-{index}.json").write_text(json.dumps(video_record), encoding="utf-8")
    library._write_index([*library.list(limit=None), record({"prompt": "missing image"}, filename="missing.jpg")])
    (videos.path / "missing.json").write_text(json.dumps(record({"prompt": "missing video"}, filename="missing.mp4")), encoding="utf-8")
    assert len(library.list()) == len(videos.list()) == 50
    assert len(videos.list(limit=None)) == 55
    with TestClient(app) as client:
        app.state.active_display_store.set("Current display", 820, 320, "1.1.39")
        app.state.display_settings_store.set_rotation(180)
        app.state.display_settings_store.set_video_rotation(0)
        response = client.get("/creation-library/prompts.txt")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-disposition"].startswith('attachment; filename="ESPImageServer-prompts-')
        text = response.content.decode("utf-8")
        assert "Saved items: 110" in text
        for index in range(55):
            assert f"saved image prompt {index}\n" in text
            assert f"saved video prompt {index}\n" in text
        assert "Orientation: Landscape (320 x 240)" in text
        assert "Orientation: Portrait (272 x 480)" in text
        assert "(820 x 320)" not in text and "(320 x 820)" not in text
        assert "missing image" not in text and "missing video" not in text
        library.save(b"new saved JPEG", {"prompt": "newly saved café\n猫"})
        second = client.get("/creation-library/prompts.txt")
        assert "Saved items: 111" in second.text
        assert "newly saved café\n猫" in second.text
        assert "Model: Not recorded" in second.text


def test_empty_gallery_export_is_a_readable_download():
    app = create_app(Settings(), SimpleNamespace(device="cpu", ready=False), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/creation-library/prompts.txt")
    assert response.status_code == 200
    assert "Saved items: 0" in response.text
    assert "No saved images or videos were found" in response.text
