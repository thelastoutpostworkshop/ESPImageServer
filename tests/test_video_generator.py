import numpy as np
from PIL import Image

from esp_image_server.video_generator import (
    VIDEO_MODELS, frame_to_rgb_image, remove_cached_video_model, rotate_frame_for_display, video_model_is_cached, working_hunyuan_video_size,
    working_video_size, working_wan_video_size,
)


def test_working_video_size_keeps_portrait_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(172, 320) == (384, 704)


def test_working_video_size_keeps_landscape_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(480, 272) == (672, 384)


def test_working_wan_video_size_uses_a_larger_480p_class_canvas() -> None:
    assert working_wan_video_size(172, 320) == (448, 832)


def test_wan_uses_the_official_diffusers_repository() -> None:
    assert VIDEO_MODELS["wan-2.1-t2v-1.3b"]["repository"] == "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"


def test_hunyuan_video_supports_text_and_image_generation() -> None:
    model = VIDEO_MODELS["hunyuanvideo-1.5-480p"]
    assert model["repository"] == "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v"
    assert model["image_repository"] == "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v"
    assert working_hunyuan_video_size(480, 272) == working_wan_video_size(480, 272)


def test_removing_hunyuan_removes_both_text_and_image_cache_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path))
    model = VIDEO_MODELS["hunyuanvideo-1.5-480p"]
    for repository in (model["repository"], model["image_repository"]):
        (tmp_path / f"models--{repository.replace('/', '--')}" / "snapshots" / "main").mkdir(parents=True)

    assert video_model_is_cached("hunyuanvideo-1.5-480p") is True
    assert remove_cached_video_model("hunyuanvideo-1.5-480p") is True
    assert video_model_is_cached("hunyuanvideo-1.5-480p") is False


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
