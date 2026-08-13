"""Single-worker background queue for locally generated video files."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4

from .generation_jobs import GenerationCancelled
from .generation_errors import user_facing_generation_error

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]
VideoWork = Callable[[ProgressCallback, Callable[[], bool]], Path]


@dataclass
class VideoJob:
    job_id: str
    status: str = "queued"
    stage: str = "Waiting to generate video"
    step: int = 0
    steps: int = 0
    video_path: Path | None = None
    error: str | None = None
    cancel_requested: bool = False

    def as_dict(self) -> dict[str, object]:
        progress = 100 if self.status == "complete" else (0 if self.steps == 0 else round(self.step * 100 / self.steps))
        return {"id": self.job_id, "status": self.status, "stage": self.stage, "step": self.step,
                "steps": self.steps, "progress": progress, "error": self.error,
                "cancellable": self.status in {"queued", "running", "cancelling"}}


class VideoJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-generation")

    def create(self, work: VideoWork) -> VideoJob:
        job = VideoJob(uuid4().hex)
        with self._lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run, job.job_id, work)
        return job

    def get(self, job_id: str) -> VideoJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def has_active_job(self) -> bool:
        with self._lock:
            return any(job.status in {"queued", "running", "cancelling"} for job in self._jobs.values())

    def cancel(self, job_id: str) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status in {"queued", "running", "cancelling"}:
                job.cancel_requested, job.status, job.stage = True, "cancelling", "Cancelling video generation"
            return job

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str, work: VideoWork) -> None:
        def cancelled() -> bool:
            with self._lock:
                return self._jobs[job_id].cancel_requested

        def progress(step: int, steps: int, stage: str) -> None:
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested:
                    raise GenerationCancelled()
                job.status, job.stage, job.step, job.steps = "running", stage, step, steps

        try:
            progress(0, 0, "Preparing LTX-Video")
            path = work(progress, cancelled)
            if cancelled():
                raise GenerationCancelled()
        except GenerationCancelled:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.error = "cancelled", "Video generation cancelled", None
        except Exception as exc:
            logger.exception("Video generation job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.error = "failed", "Video generation failed", user_facing_generation_error(exc, "video")
        else:
            with self._lock:
                job = self._jobs[job_id]
                job.status, job.stage, job.video_path = "complete", "Video ready", path
