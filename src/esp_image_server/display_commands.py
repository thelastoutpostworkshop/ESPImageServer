"""Small single-display command queue for actions performed by the ESP32."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4


class DisplayCommandStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[str, object] | None = None
        self._completed: dict[str, dict[str, object]] = {}

    def queue_save(self, filename: str, image_id: str | None = None) -> dict[str, object]:
        command = self.queue("save_saved_image" if image_id else "save_latest", filename=filename, image_id=image_id)
        filename = str(command["filename"])
        command["thumbnail_url"] = f"/display-sd-card/thumbnails/{filename}"
        with self._lock:
            self._pending = dict(command)
            self._completed[str(command["id"])] = dict(command)
        return command

    def queue(self, command_type: str, **values: object) -> dict[str, object]:
        with self._lock:
            command_id = uuid4().hex
            command = {
                "id": command_id,
                "type": command_type,
                "status": "pending",
            }
            command.update({key: value for key, value in values.items() if value is not None})
            self._pending = command
            self._completed[command_id] = command
            return dict(command)

    def report_sd_card(self, report: dict[str, object]) -> None:
        with self._lock:
            self._sd_card_report = dict(report)

    def sd_card_report(self) -> dict[str, object]:
        with self._lock:
            return dict(getattr(self, "_sd_card_report", {"available": False, "files": []}))

    def sd_card_has_image_hash(self, image_hash: str) -> bool:
        with self._lock:
            report = getattr(self, "_sd_card_report", {})
            if not report.get("available", False):
                return False
            files = report.get("files", [])
            return isinstance(files, list) and any(
                isinstance(item, dict) and str(item.get("name", "")).startswith(f"esp-image-{image_hash}")
                or isinstance(item, dict) and str(item.get("name", "")).endswith(f"-{image_hash}.jpg")
                for item in files
            )

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
