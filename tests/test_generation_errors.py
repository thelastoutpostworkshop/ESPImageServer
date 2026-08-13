from esp_image_server.generation_errors import user_facing_generation_error


def test_cuda_memory_failure_has_a_plain_language_message() -> None:
    message = user_facing_generation_error(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"), "video")

    assert message == "Your graphics card does not have enough memory for this video. Try fewer frames or a shorter clip."


def test_unknown_failure_does_not_expose_technical_details() -> None:
    message = user_facing_generation_error(RuntimeError("internal stack trace detail"), "image")

    assert "internal stack trace detail" not in message
    assert "server log" in message
