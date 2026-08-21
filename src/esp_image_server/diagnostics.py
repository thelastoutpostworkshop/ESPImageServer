"""Small in-memory diagnostic log used by the local app UI."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
from threading import Lock


class DiagnosticLogStore(logging.Handler):
    def __init__(self, capacity: int = 300) -> None:
        super().__init__(level=logging.INFO)
        self._entries: deque[dict[str, str]] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self._lock:
                self._entries.append({
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": record.levelname.lower(),
                    "source": record.name,
                    "message": message,
                })
        except Exception:
            self.handleError(record)

    def list(self) -> list[dict[str, str]]:
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
