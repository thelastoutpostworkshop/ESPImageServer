import logging

from esp_image_server.diagnostics import DiagnosticLogStore


def test_recoverable_windows_connection_reset_is_a_calm_diagnostic() -> None:
    store = DiagnosticLogStore()
    logger = logging.getLogger("asyncio")
    logger.setLevel(logging.ERROR)
    logger.addHandler(store)
    try:
        try:
            error = ConnectionResetError("An existing connection was forcibly closed by the remote host")
            error.winerror = 10054  # type: ignore[attr-defined]
            raise error
        except ConnectionResetError:
            logger.exception("Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)")
    finally:
        logger.removeHandler(store)

    entry = store.list()[0]
    assert entry["level"] == "info"
    assert entry["message"] == "A device or browser briefly closed its network connection. The server and queued generation will continue."
