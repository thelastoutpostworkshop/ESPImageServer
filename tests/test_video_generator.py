import numpy as np
from PIL import Image

from esp_image_server.video_generator import VIDEO_MODELS, working_video_size, working_wan_video_size


def test_working_video_size_keeps_portrait_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(172, 320) == (384, 704)


def test_working_video_size_keeps_landscape_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(480, 272) == (672, 384)


def test_working_wan_video_size_uses_a_larger_480p_class_canvas() -> None:
    assert working_wan_video_size(172, 320) == (448, 832)


def test_wan_uses_the_official_diffusers_repository() -> None:
    assert VIDEO_MODELS["wan-2.1-t2v-1.3b"]["repository"] == "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"


def test_wan_frame_arrays_can_be_converted_to_pillow_images() -> None:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    image = Image.fromarray(frame).convert("RGB")

    assert image.size == (32, 24)


def test_video_module_image_helper_is_available_without_a_reference_image() -> None:
    # ImageOps is used after the text-to-video path, so Image must not be
    # shadowed by an import confined to the optional reference-image branch.
    from esp_image_server.video_generator import Image

    assert Image is not None
