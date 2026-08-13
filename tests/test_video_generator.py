from esp_image_server.video_generator import working_video_size, working_wan_video_size


def test_working_video_size_keeps_portrait_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(172, 320) == (384, 704)


def test_working_video_size_keeps_landscape_display_aspect_at_useful_resolution() -> None:
    assert working_video_size(480, 272) == (672, 384)


def test_working_wan_video_size_uses_a_larger_480p_class_canvas() -> None:
    assert working_wan_video_size(172, 320) == (448, 832)


def test_video_module_image_helper_is_available_without_a_reference_image() -> None:
    # ImageOps is used after the text-to-video path, so Image must not be
    # shadowed by an import confined to the optional reference-image branch.
    from esp_image_server.video_generator import Image

    assert Image is not None
