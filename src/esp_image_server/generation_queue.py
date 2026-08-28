"""One FIFO queue for all GPU-backed image and video generation work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter, time
from typing import Callable
from uuid import uuid4

from .generation_errors import user_facing_generation_error
from .generation_jobs import GenerationCancelled
from .retention import COMPLETED_JOB_RETENTION, RetentionPolicy


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, str], None]
GenerationWork = Callable[[ProgressCallback, Callable[[], bool]], bytes | Path]


@dataclass
class QueuedGenerationJob:
    job_id: str
    kind: str
    work: GenerationWork = field(repr=False)
    metadata: dict[str, object] = field(default_factory=dict)
    status: str = "queued"
    stage: str = "Waiting in the generation queue"
    step: int = 0
    steps: int = 0
    jpeg: bytes | None = None
    video_path: Path | None = None
    temporary_media_path: Path | None = None
    error: str | None = None
    cancel_requested: bool = False
    generation_time_seconds: float | None = None
    finished_at: float | None = None
    media_references: int = 0

    def as_dict(self, queue_position: int | None = None) -> dict[str, object]:
        progress = 100 if self.status == "complete" else (0 if self.steps == 0 else round(self.step * 100 / self.steps))
        return {
            "id": self.job_id, "kind": self.kind, "status": self.status, "stage": self.stage,
            "step": self.step, "steps": self.steps, "progress": progress, "error": self.error,
            "cancellable": self.status in {"queued", "running", "cancelling"},
            "queue_position": queue_position, "metadata": self.metadata,
            "generation_time_seconds": self.generation_time_seconds,
        }


class GenerationQueue:
    """Serializes every generator operation so image and video jobs share the GPU safely."""

    def __init__(
        self,
        retention: RetentionPolicy = COMPLETED_JOB_RETENTION,
        video_result_root: Path | None = None,
    ) -> None:
        self._jobs: dict[str, QueuedGenerationJob] = {}
        self._order: list[str] = []
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="generation-queue")
        self._retention = retention
        self._video_result_root = video_result_root.resolve(strict=False) if video_result_root is not None else None

    def create(
        self,
        kind: str,
        work: GenerationWork,
        metadata: dict[str, object] | None = None,
        temporary_media_path: Path | None = None,
    ) -> QueuedGenerationJob:
        job = QueuedGenerationJob(
            uuid4().hex,
            kind,
            work,
            metadata or {},
            temporary_media_path=temporary_media_path,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
        self._executor.submit(self._run, job.job_id)
        return job

    def get(self, job_id: str, kind: str | None = None) -> QueuedGenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job if job is not None and (kind is None or job.kind == kind) else None

    def list(self) -> list[dict[str, object]]:
        """Return the newest jobs first while retaining FIFO queue positions."""
        with self._lock:
            position = 0
            items: list[dict[str, object]] = []
            for job_id in self._order:
                job = self._jobs[job_id]
                queue_position = None
                if job.status in {"queued", "running", "cancelling"}:
                    position += 1
                    queue_position = position
                items.append(job.as_dict(queue_position))
            return list(reversed(items))

    def has_active_job(self) -> bool:
        with self._lock:
            return any(job.status in {"queued", "running", "cancelling"} for job in self._jobs.values())

    def active_job(self) -> QueuedGenerationJob | None:
        with self._lock:
            return next((job for job in self._jobs.values() if job.status in {"running", "cancelling"}), None)

    def cancel(self, job_id: str, kind: str | None = None) -> QueuedGenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (kind is not None and job.kind != kind):
                return None
            if job.status == "queued":
                job.cancel_requested = True
                job.status, job.stage = "cancelled", "Cancelled before generation started"
                job.finished_at = time()
            elif job.status in {"running", "cancelling"}:
                job.cancel_requested = True
                job.status, job.stage = "cancelling", f"Cancelling {job.kind} generation"
            return job

    def clear_finished(self) -> int:
        """Remove completed, failed, and cancelled jobs while preserving active work."""
        with self._lock:
            finished_ids = [job_id for job_id in self._order if self._jobs[job_id].status in {"complete", "failed", "cancelled"}]
            removed = self._remove_finished_locked(finished_ids)
        self._delete_temporary_video_results(removed)
        self.cleanup_temporary_video_results()
        return len(removed)

    def prune_completed(self, now: float | None = None) -> int:
        """Apply age, count, and byte limits without touching active or leased jobs."""
        now = time() if now is None else now
        with self._lock:
            completed_ids = [
                job_id for job_id in self._order
                if self._jobs[job_id].status in {"complete", "failed", "cancelled"}
            ]
            removable_ids = [
                job_id for job_id in completed_ids
                if self._jobs[job_id].media_references == 0
            ]
            expired_ids = [
                job_id for job_id in removable_ids
                if (finished_at := self._jobs[job_id].finished_at) is not None
                and finished_at + self._retention.max_age_seconds < now
            ]
            removed_ids = list(expired_ids)
            remaining_ids = [job_id for job_id in completed_ids if job_id not in set(removed_ids)]
            total_bytes = sum(self._result_size(self._jobs[job_id]) for job_id in remaining_ids)
            while len(remaining_ids) > self._retention.max_items or (
                self._retention.max_bytes is not None and total_bytes > self._retention.max_bytes
            ):
                job_id = next(
                    (candidate for candidate in remaining_ids if self._jobs[candidate].media_references == 0),
                    None,
                )
                if job_id is None:
                    break
                remaining_ids.remove(job_id)
                removed_ids.append(job_id)
                total_bytes -= self._result_size(self._jobs[job_id])
            removed = self._remove_finished_locked(removed_ids)
        self._delete_temporary_video_results(removed)
        self.cleanup_temporary_video_results(now=now)
        return len(removed)

    def acquire_media(self, job_id: str, kind: str | None = None) -> QueuedGenerationJob | None:
        """Lease a completed file result until the response that uses it is finished."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (kind is not None and job.kind != kind) or job.status != "complete":
                return None
            job.media_references += 1
            return job

    def release_media(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.media_references = max(0, job.media_references - 1)
        self.prune_completed()

    def cleanup_temporary_video_results(self, now: float | None = None) -> int:
        """Remove orphaned generated MP4s without touching active or leased results."""
        if self._video_result_root is None or not self._video_result_root.is_dir():
            return 0
        now = time() if now is None else now
        with self._lock:
            protected_paths = {
                self._temporary_path(job)
                for job in self._jobs.values()
                if job.status in {"queued", "running", "cancelling"} or job.media_references
            }
        entries: list[tuple[Path, float, int]] = []
        for path in self._video_result_root.glob("ltx-video-*.mp4"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((path.resolve(strict=False), stat.st_mtime, stat.st_size))
        entries.sort(key=lambda entry: entry[1])
        deletable = [entry for entry in entries if entry[0] not in protected_paths]
        remove = [
            path for path, modified_at, _size in deletable
            if modified_at + self._retention.max_age_seconds < now
        ]
        remaining = [entry for entry in entries if entry[0] not in set(remove)]
        total_bytes = sum(size for _path, _modified_at, size in remaining)
        while len(remaining) > self._retention.max_items or (
            self._retention.max_bytes is not None and total_bytes > self._retention.max_bytes
        ):
            candidate = next((entry for entry in remaining if entry[0] not in protected_paths), None)
            if candidate is None:
                break
            path, _modified_at, size = candidate
            remove.append(path)
            remaining.remove(candidate)
            total_bytes -= size
        removed = 0
        for path in dict.fromkeys(remove):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                logger.warning("Could not remove temporary video result %s", path)
                continue
            removed += 1
        return removed

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str) -> None:
        def cancelled() -> bool:
            with self._lock:
                return self._jobs[job_id].cancel_requested

        def progress(step: int, steps: int, stage: str) -> None:
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested:
                    raise GenerationCancelled()
                job.status, job.stage, job.step, job.steps = "running", stage, step, steps

        with self._lock:
            job = self._jobs[job_id]
            kind = job.kind
            work = job.work
        generation_started_at = perf_counter()
        try:
            if cancelled():
                raise GenerationCancelled()
            progress(0, 0, f"Preparing {kind} generation")
            result = work(progress, cancelled)
            if cancelled():
                raise GenerationCancelled()
        except GenerationCancelled:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.error = "cancelled", f"{kind.capitalize()} generation cancelled", None
                job.generation_time_seconds = round(perf_counter() - generation_started_at, 2)
                job.finished_at = time()
        except Exception as exc:
            logger.exception("%s generation job %s failed", kind, job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage = "failed", f"{kind.capitalize()} generation failed"
                job.error = user_facing_generation_error(exc, kind)
                job.generation_time_seconds = round(perf_counter() - generation_started_at, 2)
                job.finished_at = time()
        else:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage = "complete", f"{kind.capitalize()} ready"
                job.generation_time_seconds = round(perf_counter() - generation_started_at, 2)
                job.finished_at = time()
                if kind == "image":
                    job.jpeg = result if isinstance(result, bytes) else None
                else:
                    job.video_path = result if isinstance(result, Path) else None
        self.prune_completed()

    def _remove_finished_locked(self, job_ids: list[str]) -> list[QueuedGenerationJob]:
        removed: list[QueuedGenerationJob] = []
        for job_id in dict.fromkeys(job_ids):
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"complete", "failed", "cancelled"} or job.media_references:
                continue
            removed.append(job)
            del self._jobs[job_id]
        removed_ids = {job.job_id for job in removed}
        self._order = [job_id for job_id in self._order if job_id not in removed_ids]
        return removed

    @staticmethod
    def _result_size(job: QueuedGenerationJob) -> int:
        if job.jpeg is not None:
            return len(job.jpeg)
        if job.video_path is not None:
            try:
                return job.video_path.stat().st_size
            except OSError:
                return 0
        return 0

    def _delete_temporary_video_results(self, jobs: list[QueuedGenerationJob]) -> None:
        if self._video_result_root is None:
            return
        for job in jobs:
            path = self._temporary_path(job)
            if path is None:
                continue
            if not path.is_relative_to(self._video_result_root):
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary video result %s", path)

    def _temporary_path(self, job: QueuedGenerationJob) -> Path | None:
        path = job.video_path or job.temporary_media_path
        return path.resolve(strict=False) if path is not None else None
