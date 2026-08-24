"""One FIFO queue for all GPU-backed image and video generation work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .generation_errors import user_facing_generation_error
from .generation_jobs import GenerationCancelled


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
    error: str | None = None
    cancel_requested: bool = False
    generation_time_seconds: float | None = None

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

    def __init__(self) -> None:
        self._jobs: dict[str, QueuedGenerationJob] = {}
        self._order: list[str] = []
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="generation-queue")

    def create(self, kind: str, work: GenerationWork, metadata: dict[str, object] | None = None) -> QueuedGenerationJob:
        job = QueuedGenerationJob(uuid4().hex, kind, work, metadata or {})
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
            return items

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
            elif job.status in {"running", "cancelling"}:
                job.cancel_requested = True
                job.status, job.stage = "cancelling", f"Cancelling {job.kind} generation"
            return job

    def clear_finished(self) -> int:
        """Remove completed, failed, and cancelled jobs while preserving active work."""
        with self._lock:
            finished_ids = [job_id for job_id in self._order if self._jobs[job_id].status in {"complete", "failed", "cancelled"}]
            for job_id in finished_ids:
                del self._jobs[job_id]
            self._order = [job_id for job_id in self._order if job_id not in finished_ids]
            return len(finished_ids)

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
        except Exception as exc:
            logger.exception("%s generation job %s failed", kind, job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage = "failed", f"{kind.capitalize()} generation failed"
                job.error = user_facing_generation_error(exc, kind)
                job.generation_time_seconds = round(perf_counter() - generation_started_at, 2)
        else:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage = "complete", f"{kind.capitalize()} ready"
                job.generation_time_seconds = round(perf_counter() - generation_started_at, 2)
                if kind == "image":
                    job.jpeg = result if isinstance(result, bytes) else None
                else:
                    job.video_path = result if isinstance(result, Path) else None
