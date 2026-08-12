"""Small single-display command queue for actions performed by the ESP32."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4


class DisplayCommandStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[str, object] | None = None
        self._completed: dict[str, dict[str, object]] = {}

    def queue_save(self, image_id: str | None = None) -> dict[str, object]:
        with self._lock:
            command_id = uuid4().hex
            command = {
                "id": command_id,
                "type": "save_saved_image" if image_id else "save_latest",
                "filename": f"esp-image-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.jpg",
                "status": "pending",
            }
            if image_id:
                command["image_id"] = image_id
            self._pending = command
            self._completed[command_id] = command
            return dict(command)

    def next(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._pending) if self._pending is not None else None

    def acknowledge(self, command_id: str, success: bool, detail: str) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            if command is None:
                return None
            command.update({"status": "complete" if success else "failed", "detail": detail})
            if self._pending is not None and self._pending.get("id") == command_id:
                self._pending = None
            return dict(command)

    def get(self, command_id: str) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            return dict(command) if command is not None else None
