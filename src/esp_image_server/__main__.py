import logging

import uvicorn

from .app import app
from .config import Settings


class BrowserAddressFilter(logging.Filter):
    """Show a usable local URL while retaining the LAN-wide bind address."""

    _startup_message_prefix = "Uvicorn running on %s://%s:%d"

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            isinstance(record.msg, str)
            and record.msg.startswith(self._startup_message_prefix)
            and isinstance(record.args, tuple)
            and len(record.args) >= 3
        ):
            protocol, host, port, *rest = record.args
            if host in {"0.0.0.0", "::"}:
                record.args = (protocol, "127.0.0.1", port, *rest)
        return True


if __name__ == "__main__":
    settings = Settings.from_env()
    # Uvicorn's default startup link mirrors its bind address.  0.0.0.0 is
    # necessary for ESP32/LAN access but is not a browser destination.
    logging.getLogger("uvicorn.error").addFilter(BrowserAddressFilter())
    uvicorn.run(app, host=settings.host, port=settings.port)
