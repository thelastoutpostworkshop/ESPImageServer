import logging

from esp_image_server.__main__ import BrowserAddressFilter


def test_browser_address_filter_replaces_wildcard_bind_address() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
        ("http", "0.0.0.0", 8000),
        None,
    )

    assert BrowserAddressFilter().filter(record) is True
    assert record.getMessage() == "Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)"


def test_browser_address_filter_keeps_specific_bind_address() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
        ("http", "192.168.1.10", 8000),
        None,
    )

    BrowserAddressFilter().filter(record)

    assert record.getMessage() == "Uvicorn running on http://192.168.1.10:8000 (Press CTRL+C to quit)"
