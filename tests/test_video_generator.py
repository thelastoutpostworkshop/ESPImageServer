import numpy as np
import sys
import pytest
from PIL import Image

from esp_image_server.video_generator import (
    VIDEO_MODELS, frame_to_rgb_image, remove_cached_video_model, rotate_frame_for_display, video_model_is_cached,
    working_video_size, working_wan_video_size,
)


def test_missing_exporter_fails_before_loading_video_model(tmp_path, monkeypatch):
    from esp_image_server.video_generator import LTXVideoGenerator
    monkeypatch.setitem(sys.modules, "imageio", None)
    generator = LTXVideoGenerator()
    monkeypatch.setattr(generator, "_load", lambda *args: pytest.fail("Model must not load before export validation"))
    with pytest.raises(RuntimeError, match="imageio and imageio-ffmpeg"):
        generator.generate("test", 64, 64, 9, 8, 4, None, tmp_path / "unused.mp4",
                           lambda *args: None, lambda: False)
    assert not (tmp_path / "unused.mp4").exists()


def test_working_video_size_keeps_portrait_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(172, 320) == (384, 704)


def test_working_video_size_keeps_landscape_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(480, 272) == (672, 384)


def test_working_wan_video_size_uses_a_larger_480p_class_canvas() -> None:
    assert working_wan_video_size(172, 320) == (448, 832)


def test_wan_uses_the_official_diffusers_repository() -> None:
    assert VIDEO_MODELS["wan-2.1-t2v-1.3b"]["repository"] == "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"


def test_removing_wan_cache_preserves_other_models_and_creations(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path))
    (tmp_path / "models--Wan-AI--Wan2.1-T2V-1.3B-Diffusers" / "snapshots" / "main").mkdir(parents=True)
    other = tmp_path / "other-model"
    other.mkdir()
    creation = tmp_path / "saved-video.mp4"
    creation.write_bytes(b"saved creation")
    assert video_model_is_cached("wan-2.1-t2v-1.3b")
    assert remove_cached_video_model("wan-2.1-t2v-1.3b")
    assert not video_model_is_cached("wan-2.1-t2v-1.3b")
    assert other.is_dir() and creation.read_bytes() == b"saved creation"


def test_wan_float_frame_arrays_are_converted_to_pillow_images() -> None:
    frame = np.full((24, 32, 3), 0.5, dtype=np.float32)
    image = frame_to_rgb_image(frame)

    assert image.size == (32, 24)
    assert image.getpixel((0, 0)) == (128, 128, 128)


def test_video_frame_rotation_matches_the_display_image_rotation_contract() -> None:
    frame = Image.new("RGB", (32, 24), "blue")

    assert rotate_frame_for_display(frame, 0).size == (32, 24)
    assert rotate_frame_for_display(frame, 90).size == (24, 32)
    assert rotate_frame_for_display(frame, 180).size == (32, 24)
    assert rotate_frame_for_display(frame, 270).size == (24, 32)


def test_video_module_image_helper_is_available_without_a_reference_image() -> None:
    # ImageOps is used after the text-to-video path, so Image must not be
    # shadowed by an import confined to the optional reference-image branch.
    from esp_image_server.video_generator import Image

    assert Image is not None
