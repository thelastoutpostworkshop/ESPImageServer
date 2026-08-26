"""Small single-display command queue for actions performed by the ESP32."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from threading import Lock
from time import time
from uuid import uuid4

from .retention import DISPLAY_COMMAND_RETENTION, RetentionPolicy


class DisplayCommandStore:
    def __init__(self, retention: RetentionPolicy = DISPLAY_COMMAND_RETENTION) -> None:
        self._lock = Lock()
        self._pending: dict[str, object] | None = None
        self._completed: dict[str, dict[str, object]] = {}
        self._finished_at: dict[str, float] = {}
        self._retention = retention
        self._sd_card_report_version = 0
        self._sd_card_report: dict[str, object] = {
            "available": False,
            "files": [],
            "report_version": self._sd_card_report_version,
        }

    def queue_save(
        self, filename: str, image_id: str | None = None, content_key: str | None = None,
    ) -> dict[str, object]:
        command = self.queue(
            "save_saved_image" if image_id else "save_latest",
            filename=filename,
            image_id=image_id,
            content_key=content_key,
        )
        filename = str(command["filename"])
        command["thumbnail_url"] = f"/display-sd-card/thumbnails/{filename}"
        with self._lock:
            self._pending = dict(command)
            self._completed[str(command["id"])] = dict(command)
        return command

    def queue(self, command_type: str, **values: object) -> dict[str, object]:
        with self._lock:
            if self._pending is not None:
                previous_id = str(self._pending["id"])
                previous = self._completed.get(previous_id)
                if previous is not None and previous.get("status") == "pending":
                    previous["status"] = "superseded"
                    self._finished_at[previous_id] = time()
            command_id = uuid4().hex
            command = {
                "id": command_id,
                "type": command_type,
                "status": "pending",
            }
            command.update({key: value for key, value in values.items() if value is not None})
            self._pending = command
            self._completed[command_id] = command
            self._prune_completed_locked()
            return dict(command)

    def report_sd_card(self, report: dict[str, object]) -> None:
        with self._lock:
            report_version = self._sd_card_report_version + 1
            self._sd_card_report_version = report_version
            self._sd_card_report = {
                **report,
                "reported_at": datetime.now(UTC).isoformat(),
                "report_version": report_version,
            }

    def sd_card_report(self) -> dict[str, object]:
        with self._lock:
            return dict(self._sd_card_report)

    def find_sd_card_image(self, image_hash: str) -> str | None:
        """Find a stored image by its stable content hash, including legacy names."""
        with self._lock:
            report = self._sd_card_report
            if not report.get("available", False):
                return None
            files = report.get("files", [])
            if not isinstance(files, list):
                return None
            content_key = f"v1-{image_hash}"
            for item in files:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", ""))
                if (
                    item.get("type", "image") == "image"
                    and (
                        str(item.get("content_key", "")) == content_key
                        or name.startswith(f"esp-image-{image_hash}")
                        or name.endswith(f"-{image_hash}.jpg")
                    )
                ):
                    return name
            return None

    def find_sd_card_content(self, content_key: str, media_type: str) -> str | None:
        """Return the filename currently reported for a stable SD-card content key."""
        with self._lock:
            report = self._sd_card_report
            if not report.get("available", False):
                return None
            files = report.get("files", [])
            if not isinstance(files, list):
                return None
            for item in files:
                if not isinstance(item, dict) or item.get("type") != media_type:
                    continue
                name = str(item.get("name", ""))
                extension = "mjpeg" if media_type == "video" else "jpg"
                if str(item.get("content_key", "")) == content_key or name.endswith(f"-{content_key}.{extension}"):
                    return name
            return None

    def find_sd_card_video(self, content_key: str, video_id: str, fps: int) -> str | None:
        """Find a video by its current key or the older short-ID filename."""
        existing_filename = self.find_sd_card_content(content_key, "video")
        if existing_filename is not None:
            return existing_filename
        legacy_suffix = f"-{video_id[:8]}-fps{fps}.mjpeg"
        with self._lock:
            files = self._sd_card_report.get("files", [])
            if not self._sd_card_report.get("available", False) or not isinstance(files, list):
                return None
            for item in files:
                if isinstance(item, dict) and item.get("type") == "video":
                    name = str(item.get("name", ""))
                    if name.startswith("esp-video-") and name.endswith(legacy_suffix):
                        return name
            return None

    def next(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._pending) if self._pending is not None else None

    def acknowledge(self, command_id: str, success: bool, detail: str) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            if command is None:
                return None
            command.update({"status": "complete" if success else "failed", "detail": detail})
            if success and command.get("type") == "refresh_sd_card":
                # Firmware acknowledges a refresh immediately before it posts its
                # new inventory. The UI waits for this exact next report.
                command["report_version"] = self._sd_card_report_version + 1
            if self._pending is not None and self._pending.get("id") == command_id:
                self._pending = None
            self._finished_at[command_id] = time()
            self._prune_completed_locked()
            return dict(command)

    def get(self, command_id: str) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            return dict(command) if command is not None else None

    def referenced_video_ids(self) -> set[str]:
        """Return media still needed by the command waiting for the display."""
        with self._lock:
            if self._pending is None or self._pending.get("type") != "save_saved_video":
                return set()
            video_id = self._pending.get("video_id")
            return {str(video_id)} if video_id else set()

    def prune_completed(self, now: float | None = None) -> int:
        with self._lock:
            return self._prune_completed_locked(time() if now is None else now)

    def _prune_completed_locked(self, now: float | None = None) -> int:
        now = time() if now is None else now
        active_id = str(self._pending["id"]) if self._pending is not None else None
        finished_ids = [
            command_id for command_id in self._completed
            if command_id != active_id and command_id in self._finished_at
        ]
        expired_ids = [
            command_id for command_id in finished_ids
            if self._finished_at[command_id] + self._retention.max_age_seconds < now
        ]
        remove_ids = list(expired_ids)
        remaining_ids = [command_id for command_id in finished_ids if command_id not in set(remove_ids)]
        total_bytes = sum(self._command_size(self._completed[command_id]) for command_id in remaining_ids)
        while len(remaining_ids) > self._retention.max_items or (
            self._retention.max_bytes is not None and total_bytes > self._retention.max_bytes
        ):
            command_id = min(remaining_ids, key=lambda candidate: self._finished_at[candidate])
            remaining_ids.remove(command_id)
            remove_ids.append(command_id)
            total_bytes -= self._command_size(self._completed[command_id])
        for command_id in dict.fromkeys(remove_ids):
            self._completed.pop(command_id, None)
            self._finished_at.pop(command_id, None)
        return len(set(remove_ids))

    @staticmethod
    def _command_size(command: dict[str, object]) -> int:
        return len(json.dumps(command, default=str, separators=(",", ":")).encode("utf-8"))
