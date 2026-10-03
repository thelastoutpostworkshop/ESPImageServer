from esp_image_server.generation_errors import user_facing_generation_error


def test_cuda_memory_failure_has_a_plain_language_message() -> None:
    message = user_facing_generation_error(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"), "video")

    assert message == (
        "Your graphics card does not have enough memory for this video. Try fewer frames or a shorter clip."
        "\n\nTechnical details: CUDA out of memory. Tried to allocate 2.00 GiB"
    )


def test_unknown_failure_keeps_technical_details() -> None:
    message = user_facing_generation_error(RuntimeError("internal stack trace detail"), "image")

    assert "internal stack trace detail" in message
    assert "server log" in message


def test_windows_link_failure_does_not_require_developer_mode() -> None:
    error = OSError("[WinError 1314] A required privilege is not held by the client")
    message = user_facing_generation_error(error, "image")

    assert "Restart ESPImageServer" in message
    assert "Developer Mode" not in message
    assert "administrator" not in message.casefold()
    assert str(error) in message
