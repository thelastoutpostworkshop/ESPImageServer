"""Sequential, cancellable SD-card saves independent of browser navigation."""

from __future__ import annotations

from copy import deepcopy
from threading import Event, RLock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from .display_commands import DisplayCommandBusyError, DisplayCommandStore


class SDSaveBatchStore:
    """Own the command channel until every dispatched operation is reconciled.

    Cancellation and a completed download can race. A successful original ACK
    still counts as saved, but the separate cancel ACK must arrive before the
    channel is released. An offline board can therefore keep a cancelling batch
    alive until it reconnects; no later item is dispatched in that interval.
    """

    def __init__(
        self,
        commands: DisplayCommandStore,
        queue_item: Callable[[str, dict[str, object], str, int, int], dict[str, object]],
        is_connected: Callable[[str], bool],
        *,
        command_timeout: float = 600,
        poll_interval: float = 0.1,
        max_completed: int = 50,
    ) -> None:
        self._commands = commands
        self._queue_item = queue_item
        self._is_connected = is_connected
        self._command_timeout = command_timeout
        self._poll_interval = poll_interval
        self._max_completed = max_completed
        self._lock = RLock()
        self._stop = Event()
        self._batches: dict[str, dict[str, object]] = {}
        self._active: dict[str, str] = {}
        self._workers: dict[str, Thread] = {}

    def start(self, display_id: str, display_name: str, items: list[dict[str, object]]) -> dict[str, object]:
        with self._lock:
            if self._stop.is_set():
                raise DisplayCommandBusyError("The server is shutting down")
            if display_id in self._active:
                raise DisplayCommandBusyError("A bulk SD-card save is already active on this display")
            unique = list({(str(item["type"]), str(item["id"])): item for item in items}.values())
            if not 1 <= len(unique) <= 500:
                raise ValueError("Select between 1 and 500 gallery items")
            batch_id = uuid4().hex
            self._commands.reserve(display_id, batch_id)
            batch: dict[str, object] = {
                "id": batch_id, "display_id": display_id, "display_name": display_name,
                "status": "running", "total": len(unique), "completed": 0, "saved": 0, "skipped": 0,
                "items": [{"id": item["id"], "type": item["type"], "status": "queued"} for item in unique],
                "current_index": 0, "current_command": None, "detail": "Refreshing the display SD card",
                "_cancel": False, "_failure": "",
            }
            self._batches[batch_id] = batch
            self._active[display_id] = batch_id
            try:
                command = self._commands.queue("refresh_sd_card", display_id=display_id, owner_id=batch_id)
                batch["current_command"] = command
                worker = Thread(target=self._run, args=(batch_id,), name=f"sd-save-{batch_id[:8]}", daemon=True)
                self._workers[batch_id] = worker
                worker.start()
            except Exception:
                self._batches.pop(batch_id, None)
                self._active.pop(display_id, None)
                self._commands.release(display_id, batch_id)
                raise
            return self._snapshot_locked(batch)

    def get(self, display_id: str, batch_id: str) -> dict[str, object] | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return self._snapshot_locked(batch) if batch and batch["display_id"] == display_id else None

    def active(self, display_id: str) -> dict[str, object] | None:
        with self._lock:
            batch = self._batches.get(self._active.get(display_id, ""))
            return self._snapshot_locked(batch) if batch else None

    def cancel(self, display_id: str, batch_id: str) -> dict[str, object] | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch["display_id"] != display_id:
                return None
            if batch_id == self._active.get(display_id):
                self._request_stop_locked(batch)
            return self._snapshot_locked(batch)

    def references(self, media_type: str) -> set[str]:
        with self._lock:
            return {
                str(item["id"])
                for batch_id in self._active.values()
                for item in self._batches[batch_id]["items"]
                if item["type"] == media_type and item["status"] in {"queued", "saving"}
            }

    def has_active(self) -> bool:
        with self._lock:
            return bool(self._active)

    def active_saves(self) -> list[dict[str, object]]:
        """Snapshot all SD saves, including a batch's gaps between commands."""
        with self._lock:
            # Keep the existing batch -> command lock order. Holding the batch
            # lock across both reads prevents dispatch/completion transitions
            # from leaving a bulk save absent from the shutdown snapshot.
            commands = self._commands.active_sd_card_saves()
            active_ids = set(self._active.values())
            saves = [command for command in commands if command.get("bulk_save_id") not in active_ids]
            for batch_id in self._active.values():
                batch = self._batches[batch_id]
                saves.append({
                    "id": batch["id"], "display_id": batch["display_id"],
                    "type": "sd_card_save_batch", "status": batch["status"],
                    "display_name": batch["display_name"], "total": batch["total"],
                    "completed": batch["completed"], "current_index": batch["current_index"],
                })
            return saves

    def close(self) -> None:
        with self._lock:
            for batch_id in self._active.values():
                self._request_stop_locked(self._batches[batch_id])
            self._stop.set()
            workers = list(self._workers.values())
        for worker in workers:
            worker.join(timeout=1)

    def _snapshot_locked(self, batch: dict[str, object]) -> dict[str, object]:
        snapshot = deepcopy({key: value for key, value in batch.items() if not key.startswith("_")})
        current = snapshot.get("current_command")
        if current:
            snapshot["current_command"] = self._commands.get(str(current["id"]), display_id=str(batch["display_id"])) or current
        return snapshot

    def _request_stop_locked(self, batch: dict[str, object], failure: str = "") -> None:
        batch["_cancel"] = True
        if failure and not batch["_failure"]:
            batch["_failure"] = failure
        batch["status"] = "cancelling"
        batch["detail"] = (str(batch["_failure"]) + "; " if batch["_failure"] else "") + "Cancellation requested; waiting for the display"
        current = batch.get("current_command")
        if current:
            self._commands.cancel(str(current["id"]), display_id=str(batch["display_id"]), owner_id=str(batch["id"]))
            pending = self._commands.next(str(batch["display_id"]))
            if pending and pending.get("type") == "cancel_operation":
                batch["_cancel_command_id"] = pending["id"]

    def _wait_command(self, batch: dict[str, object]) -> dict[str, object] | None:
        deadline = monotonic() + self._command_timeout
        display_id = str(batch["display_id"])
        command_id = str(batch["current_command"]["id"])
        while not self._stop.is_set():
            with self._lock:
                command = self._commands.get(command_id, display_id=display_id)
                if command is None:
                    self._request_stop_locked(batch, "The display command is no longer available")
                    return None
                pending = self._commands.next(display_id)
                if batch["_cancel"]:
                    # Original success may arrive before cancel_operation's ACK.
                    if pending is None and command["status"] not in {"pending", "cancelling"}:
                        cancellation = self._commands.get(str(batch.get("_cancel_command_id", "")), display_id=display_id)
                        if cancellation and cancellation["status"] == "failed":
                            batch["_failure"] = str(cancellation.get("detail") or "The display could not confirm cancellation")
                        return command
                elif command["status"] not in {"pending", "cancelling"}:
                    return command
                elif monotonic() >= deadline:
                    self._request_stop_locked(batch, "The display did not finish the SD-card operation in time")
                elif not self._is_connected(display_id):
                    self._request_stop_locked(batch, "The display disconnected during the bulk save")
            self._stop.wait(self._poll_interval)
        return None

    def _wait_inventory(self, batch: dict[str, object], command: dict[str, object]) -> bool:
        deadline = monotonic() + self._command_timeout
        display_id = str(batch["display_id"])
        while not self._stop.is_set():
            with self._lock:
                if batch["_cancel"]:
                    return False
                report = self._commands.sd_card_report(display_id)
                if int(report.get("report_version", 0)) >= int(command.get("report_version", 1)):
                    if not report.get("available"):
                        batch["_failure"] = "The display SD card is unavailable"
                        return False
                    return True
                if monotonic() >= deadline or not self._is_connected(display_id):
                    batch["_failure"] = "The display did not report a fresh SD-card inventory"
                    return False
            self._stop.wait(self._poll_interval)
        return False

    def _run(self, batch_id: str) -> None:
        batch = self._batches[batch_id]
        display_id = str(batch["display_id"])
        try:
            command = self._wait_command(batch)
            if command is None:
                return
            if command["status"] != "complete":
                if not batch["_cancel"]:
                    batch["_failure"] = str(command.get("detail") or "Could not refresh the display SD card")
                return
            if not self._wait_inventory(batch, command):
                return
            for index, item in enumerate(batch["items"], start=1):
                with self._lock:
                    if batch["_cancel"] or self._stop.is_set():
                        break
                    if not self._is_connected(display_id):
                        batch["_failure"] = "The display disconnected during the bulk save"
                        break
                    batch["current_index"] = index
                    batch["current_command"] = None
                    batch["detail"] = f"Saving {index} of {batch['total']} to {batch['display_name']}"
                    # Cancellation cannot interleave between dispatch and recording
                    # the command, so it always knows exactly which item to stop.
                    command = self._queue_item(display_id, item, batch_id, index, int(batch["total"]))
                    if command.get("status") == "already_saved":
                        item.update(status="already_saved", detail=command.get("detail", ""))
                        batch["skipped"] += 1
                        batch["completed"] += 1
                        continue
                    item["status"] = "saving"
                    batch["current_command"] = command
                command = self._wait_command(batch)
                if command is None:
                    return
                with self._lock:
                    if command["status"] == "complete":
                        item["status"] = "saved"
                        batch["saved"] += 1
                        batch["completed"] += 1
                    elif batch["_cancel"] and not batch["_failure"]:
                        item["status"] = "cancelled"
                    else:
                        item["status"] = "failed"
                        batch["_failure"] = batch["_failure"] or str(command.get("detail") or "The display could not save this item")
                    item["detail"] = command.get("detail", "")
                    if batch["_cancel"] or batch["_failure"]:
                        break
        except Exception as exc:
            with self._lock:
                batch["_failure"] = str(getattr(exc, "detail", "") or exc)
                index = int(batch["current_index"])
                if index:
                    batch["items"][index - 1].update(status="failed", detail=batch["_failure"])
        finally:
            with self._lock:
                # Shutdown or an unreconciled command must never free the channel.
                if self._commands.next(display_id) is None:
                    failure = str(batch["_failure"])
                    batch["status"] = "failed" if failure else "cancelled" if batch["_cancel"] else "complete"
                    batch["detail"] = failure or ("Bulk save cancelled" if batch["_cancel"] else "Bulk save complete")
                    if batch["_cancel"] and not failure:
                        for item in batch["items"]:
                            if item["status"] == "queued":
                                item["status"] = "cancelled"
                    self._commands.release(display_id, batch_id)
                    self._active.pop(display_id, None)
                self._workers.pop(batch_id, None)
                completed = [key for key in self._batches if key not in self._active.values()]
                for key in completed[:-self._max_completed]:
                    del self._batches[key]
