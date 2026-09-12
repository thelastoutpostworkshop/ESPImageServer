"""Per-display command queues and SD-card inventory reported by ESP32 boards."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from threading import Lock
from time import time
from uuid import uuid4

from .retention import DISPLAY_COMMAND_RETENTION, RetentionPolicy


LEGACY_DISPLAY_ID = "__legacy__"


class DisplayCommandStore:
    def __init__(self, retention: RetentionPolicy = DISPLAY_COMMAND_RETENTION) -> None:
        self._lock = Lock()
        self._pending: dict[str, dict[str, object]] = {}
        self._completed: dict[str, dict[str, object]] = {}
        self._finished_at: dict[str, float] = {}
        self._retention = retention
        self._sd_card_report_versions: dict[str, int] = {}
        self._sd_card_reports: dict[str, dict[str, object]] = {}

    def queue_save(
        self,
        filename: str,
        image_id: str | None = None,
        content_key: str | None = None,
        *,
        display_id: str = LEGACY_DISPLAY_ID,
        thumbnail_url: str | None = None,
    ) -> dict[str, object]:
        command = self.queue(
            "save_saved_image" if image_id else "save_latest",
            display_id=display_id,
            filename=filename,
            image_id=image_id,
            content_key=content_key,
            thumbnail_url=thumbnail_url or f"/display-sd-card/thumbnails/{filename}",
        )
        return command

    def queue(
        self, command_type: str, *, display_id: str = LEGACY_DISPLAY_ID, **values: object,
    ) -> dict[str, object]:
        with self._lock:
            pending = self._pending.get(display_id)
            if pending is not None:
                previous_id = str(pending["id"])
                previous = self._completed.get(previous_id)
                if previous is not None and previous.get("status") == "pending":
                    previous["status"] = "superseded"
                    self._finished_at[previous_id] = time()
                    if previous.get("type") == "cancel_operation":
                        original = self._completed.get(str(previous.get("cancelled_command_id", "")))
                        if original is not None and original.get("status") == "cancelling":
                            original.update(status="superseded", detail="Replaced by another display command")
                            self._finished_at[str(original["id"])] = time()
            command_id = uuid4().hex
            command = {
                "id": command_id,
                "type": command_type,
                "status": "pending",
                "display_id": display_id,
            }
            command.update({key: value for key, value in values.items() if value is not None})
            self._pending[display_id] = command
            self._completed[command_id] = command
            self._prune_completed_locked()
            return dict(command)

    def report_sd_card(
        self, report: dict[str, object], *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> None:
        with self._lock:
            report_version = self._sd_card_report_versions.get(display_id, 0) + 1
            self._sd_card_report_versions[display_id] = report_version
            self._sd_card_reports[display_id] = {
                **report,
                "reported_at": datetime.now(UTC).isoformat(),
                "report_version": report_version,
            }

    def sd_card_report(self, display_id: str = LEGACY_DISPLAY_ID) -> dict[str, object]:
        with self._lock:
            report = self._sd_card_reports.get(display_id)
            if report is not None:
                return dict(report)
            return {
                "available": False,
                "files": [],
                "report_version": self._sd_card_report_versions.get(display_id, 0),
            }

    def find_sd_card_image(
        self, image_hash: str, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> str | None:
        """Find a stored image by its stable content hash, including legacy names."""
        with self._lock:
            report = self._sd_card_reports.get(display_id, {})
            if not report.get("available", False):
                return None
            files = report.get("files", [])
            if not isinstance(files, list):
                return None
            content_key = f"v1-{image_hash}"
            for item in files:
                if not isinstance(item, dict):
                    continue
                if report.get("verified_saves") and item.get("verified") is not True:
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

    def find_sd_card_content(
        self, content_key: str, media_type: str, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> str | None:
        """Return the filename currently reported for a stable SD-card content key."""
        with self._lock:
            report = self._sd_card_reports.get(display_id, {})
            if not report.get("available", False):
                return None
            files = report.get("files", [])
            if not isinstance(files, list):
                return None
            for item in files:
                if not isinstance(item, dict) or item.get("type") != media_type:
                    continue
                if report.get("verified_saves") and item.get("verified") is not True:
                    continue
                name = str(item.get("name", ""))
                extension = "mjpeg" if media_type == "video" else "jpg"
                if str(item.get("content_key", "")) == content_key or name.endswith(f"-{content_key}.{extension}"):
                    return name
            return None

    def find_sd_card_video(
        self, content_key: str, video_id: str, fps: int, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> str | None:
        """Find a video by its current key or the older short-ID filename."""
        existing_filename = self.find_sd_card_content(content_key, "video", display_id=display_id)
        if existing_filename is not None:
            return existing_filename
        legacy_suffix = f"-{video_id[:8]}-fps{fps}.mjpeg"
        with self._lock:
            report = self._sd_card_reports.get(display_id, {})
            files = report.get("files", [])
            if not report.get("available", False) or not isinstance(files, list):
                return None
            for item in files:
                if report.get("verified_saves") and (not isinstance(item, dict) or item.get("verified") is not True):
                    continue
                if isinstance(item, dict) and item.get("type") == "video":
                    name = str(item.get("name", ""))
                    if name.startswith("esp-video-") and name.endswith(legacy_suffix):
                        return name
            return None

    def next(self, display_id: str = LEGACY_DISPLAY_ID) -> dict[str, object] | None:
        with self._lock:
            command = self._pending.get(display_id)
            return dict(command) if command is not None else None

    def acknowledge(
        self,
        command_id: str,
        success: bool,
        detail: str,
        *,
        display_id: str = LEGACY_DISPLAY_ID,
    ) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            if command is None or command.get("display_id") != display_id:
                return None
            if command.get("status") in {"complete", "failed", "cancelled", "superseded"}:
                return dict(command)
            command.update({"status": "complete" if success else "failed", "detail": detail})
            if command.get("type") == "cancel_operation":
                original = self._completed.get(str(command.get("cancelled_command_id", "")))
                if original is not None and original.get("status") == "cancelling":
                    original.update(status="cancelled" if success else "failed", detail=detail)
                    self._finished_at[str(original["id"])] = time()
            if success and command.get("type") == "refresh_sd_card":
                # Firmware acknowledges a refresh immediately before it posts its
                # new inventory. The UI waits for this exact next report.
                command["report_version"] = self._sd_card_report_versions.get(display_id, 0) + 1
            pending = self._pending.get(display_id)
            if pending is not None and pending.get("id") == command_id:
                del self._pending[display_id]
            self._finished_at[command_id] = time()
            self._prune_completed_locked()
            return dict(command)

    def progress(
        self, command_id: str, stage: str, received: int, total: int, *, display_id: str,
    ) -> dict[str, object] | None:
        if stage not in {"downloading", "verifying"} or not 0 <= received <= total <= 64 * 1024 * 1024:
            raise ValueError("Invalid transfer progress")
        with self._lock:
            command = self._completed.get(command_id)
            if command is None or command.get("display_id") != display_id:
                return None
            if command.get("status") == "pending" and command.get("type") in {"save_latest", "save_saved_image", "save_saved_video"}:
                command["progress"] = {"stage": stage, "received_bytes": received, "total_bytes": total}
            return dict(command)

    def cancel(self, command_id: str, *, display_id: str) -> dict[str, object] | None:
        with self._lock:
            original = self._completed.get(command_id)
            if original is None or original.get("display_id") != display_id:
                return None
            if original.get("status") != "pending" or original.get("type") not in {"save_latest", "save_saved_image", "save_saved_video"}:
                return dict(original)
            if self._pending.get(display_id, {}).get("id") != command_id:
                return dict(original)
            original.update(status="cancelling", detail="Cancellation requested; waiting for the display")
            cancel_id = uuid4().hex
            command = {"id": cancel_id, "type": "cancel_operation", "status": "pending", "display_id": display_id,
                       "cancelled_command_id": command_id}
            self._pending[display_id] = command
            self._completed[cancel_id] = command
            return dict(original)

    def get(
        self, command_id: str, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> dict[str, object] | None:
        with self._lock:
            command = self._completed.get(command_id)
            if command is None or command.get("display_id") != display_id:
                return None
            return dict(command)

    def referenced_video_ids(self) -> set[str]:
        """Return media still needed by the command waiting for the display."""
        with self._lock:
            return {
                str(command["video_id"])
                for command in self._pending.values()
                if command.get("type") == "save_saved_video" and command.get("video_id")
            }

    def prune_completed(self, now: float | None = None) -> int:
        with self._lock:
            return self._prune_completed_locked(time() if now is None else now)

    def _prune_completed_locked(self, now: float | None = None) -> int:
        now = time() if now is None else now
        active_ids = {str(command["id"]) for command in self._pending.values()}
        finished_ids = [
            command_id for command_id in self._completed
            if command_id not in active_ids and command_id in self._finished_at
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
