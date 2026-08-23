"""Small in-memory diagnostic log used by the local app UI."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
import re
from threading import Lock


class DiagnosticLogStore(logging.Handler):
    def __init__(self, capacity: int = 300) -> None:
        super().__init__(level=logging.INFO)
        self._entries: deque[dict[str, str]] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            level = record.levelname.lower()
            if self._is_recoverable_connection_reset(record):
                message = "A device or browser briefly closed its network connection. The server and queued generation will continue."
                level = "info"
            with self._lock:
                self._entries.append({
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": level,
                    "source": record.name,
                    "message": message,
                })
        except Exception:
            self.handleError(record)

    @staticmethod
    def _is_recoverable_connection_reset(record: logging.LogRecord) -> bool:
        exception = record.exc_info[1] if record.exc_info else None
        return (
            record.name == "asyncio"
            and "_ProactorBasePipeTransport._call_connection_lost" in record.getMessage()
            and isinstance(exception, ConnectionResetError)
            and getattr(exception, "winerror", None) == 10054
        )

    def list(self) -> list[dict[str, str]]:
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ConsoleLogStore(logging.Handler):
    """A bounded mirror of the server's formatted console log output."""

    _secret_patterns = (
        (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)(\S+)"), r"\1[redacted]"),
        (re.compile(r"(?i)(\b(?:api[_ -]?key|token|password)\s*[:=]\s*)([^\s,;]+)"), r"\1[redacted]"),
        (re.compile(r"\bhf_[A-Za-z0-9]{8,}"), "[redacted Hugging Face token]"),
        (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[redacted API key]"),
    )

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self._lines: deque[str] = deque(maxlen=capacity)
        self._lock = Lock()

    @classmethod
    def _redact(cls, message: str) -> str:
        for pattern, replacement in cls._secret_patterns:
            message = pattern.sub(replacement, message)
        return message

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self._redact(self.format(record)).rstrip()
            if not message:
                return
            with self._lock:
                self._lines.append(message)
        except Exception:
            self.handleError(record)

    def list(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
