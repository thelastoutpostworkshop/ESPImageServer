"""Small in-process generation job queue with thread-safe progress reporting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from threading import Lock
from typing import Callable
from uuid import uuid4

from .generation_errors import user_facing_generation_error

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]
CancellationCallback = Callable[[], bool]
GenerationWork = Callable[[ProgressCallback, CancellationCallback], bytes]


class GenerationCancelled(Exception):
    """Raised when a running image job is cancelled by the user."""


@dataclass
class GenerationJob:
    job_id: str
    status: str = "queued"
    stage: str = "Waiting to generate"
    step: int = 0
    steps: int = 0
    jpeg: bytes | None = None
    error: str | None = None
    cancel_requested: bool = False

    def as_dict(self) -> dict[str, object]:
        progress = 0 if self.steps == 0 else round(self.step * 100 / self.steps)
        if self.status == "complete":
            progress = 100
        return {"id": self.job_id, "status": self.status, "stage": self.stage, "step": self.step,
                "steps": self.steps, "progress": progress, "error": self.error,
                "cancellable": self.status in {"queued", "running", "cancelling"}}


class GenerationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJob] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="image-generation")

    def create(self, work: GenerationWork) -> GenerationJob:
        job = GenerationJob(job_id=uuid4().hex)
        with self._lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run, job.job_id, work)
        return job

    def get(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def has_active_job(self) -> bool:
        with self._lock:
            return any(job.status in {"queued", "running", "cancelling"} for job in self._jobs.values())

    def cancel(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {"queued", "running", "cancelling"}:
                job.cancel_requested = True
                job.status = "cancelling"
                job.stage = "Cancelling image generation"
            return job

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str, work: GenerationWork) -> None:
        def is_cancelled() -> bool:
            with self._lock:
                return self._jobs[job_id].cancel_requested

        def progress(step: int, steps: int, stage: str) -> None:
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested:
                    raise GenerationCancelled()
                job.status, job.stage, job.step, job.steps = "running", stage, step, steps

        try:
            if is_cancelled():
                raise GenerationCancelled()
            progress(0, 0, "Preparing image generation")
            jpeg = work(progress, is_cancelled)
            if is_cancelled():
                raise GenerationCancelled()
        except GenerationCancelled:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.error = "cancelled", "Image generation cancelled", None
            return
        except Exception as exc:
            logger.exception("Image generation job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.error = "failed", "Generation failed", user_facing_generation_error(exc, "image")
            return
        with self._lock:
            job = self._jobs[job_id]
            job.status, job.stage, job.jpeg = "complete", "Image ready", jpeg
