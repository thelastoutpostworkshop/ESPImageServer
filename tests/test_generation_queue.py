from __future__ import annotations

from threading import Event
from pathlib import Path

from esp_image_server.generation_queue import GenerationQueue


def test_shared_queue_orders_mixed_work_and_cancels_waiting_job() -> None:
    queue = GenerationQueue()
    started = Event()
    release = Event()
    try:
        first = queue.create("image", lambda progress, cancelled: (started.set(), release.wait(2), b"jpeg")[2])
        assert started.wait(1)
        second = queue.create("video", lambda progress, cancelled: Path("video.mp4"))

        queued = queue.list()
        assert next(item for item in queued if item["id"] == first.job_id)["queue_position"] == 1
        assert next(item for item in queued if item["id"] == second.job_id)["queue_position"] == 2
        assert queue.cancel(second.job_id) is not None
        assert queue.get(second.job_id).status == "cancelled"
    finally:
        release.set()
        queue.close()


def test_clear_finished_keeps_active_jobs() -> None:
    queue = GenerationQueue()
    started = Event()
    release = Event()
    try:
        active = queue.create("image", lambda progress, cancelled: (started.set(), release.wait(2), b"jpeg")[2])
        assert started.wait(1)
        finished = queue.create("video", lambda progress, cancelled: Path("video.mp4"))
        assert queue.cancel(finished.job_id) is not None

        assert queue.clear_finished() == 1
        assert queue.get(active.job_id) is not None
        assert queue.get(finished.job_id) is None
    finally:
        release.set()
        queue.close()
