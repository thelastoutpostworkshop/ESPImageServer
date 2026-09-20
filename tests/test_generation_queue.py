from __future__ import annotations

from threading import Event
from pathlib import Path
import time

from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.retention import RetentionPolicy


def wait_for_status(queue: GenerationQueue, job_id: str, status: str) -> None:
    for _ in range(100):
        job = queue.get(job_id)
        if job is not None and job.status == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {status}")


def test_pending_cancellation_keeps_gpu_queue_blocked_until_work_returns() -> None:
    queue = GenerationQueue()
    started, release, next_started = Event(), Event(), Event()
    def loading(progress, cancelled):
        progress(0, 0, 'Loading model from disk')
        started.set()
        assert release.wait(3)
        return b'cancelled result'
    try:
        first = queue.create('image', loading)
        assert started.wait(1)
        second = queue.create('video', lambda progress, cancelled: (next_started.set(), Path('video.mp4'))[1])
        queue.cancel(first.job_id)
        queue.cancel(first.job_id)
        assert first.status == 'cancelling'
        assert first.stage == 'Loading model from disk'
        assert not next_started.is_set()
        assert second.status == 'queued'
        release.set()
        wait_for_status(queue, first.job_id, 'cancelled')
        wait_for_status(queue, second.job_id, 'complete')
        assert first.jpeg is None
        assert first.as_dict()['elapsed_seconds'] == first.generation_time_seconds
    finally:
        release.set()
        queue.close()


def test_shared_queue_orders_mixed_work_and_cancels_waiting_job() -> None:
    queue = GenerationQueue()
    started = Event()
    release = Event()
    try:
        first = queue.create("image", lambda progress, cancelled: (started.set(), release.wait(2), b"jpeg")[2])
        assert started.wait(1)
        second = queue.create("video", lambda progress, cancelled: Path("video.mp4"))

        queued = queue.list()
        assert [item["id"] for item in queued] == [second.job_id, first.job_id]
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


def test_retention_keeps_active_jobs_and_leased_video_results(tmp_path) -> None:
    temporary_results = tmp_path / "temporary-results"
    temporary_results.mkdir()
    queue = GenerationQueue(
        RetentionPolicy(max_items=5, max_age_seconds=0, max_bytes=1024),
        video_result_root=temporary_results,
    )
    started = Event()
    release = Event()
    video_path = temporary_results / "generated.mp4"
    try:
        def create_video(_progress, _cancelled) -> Path:
            video_path.write_bytes(b"video")
            return video_path

        finished = queue.create("video", create_video)
        wait_for_status(queue, finished.job_id, "complete")
        assert queue.acquire_media(finished.job_id, "video") is not None

        active = queue.create("image", lambda _progress, _cancelled: (started.set(), release.wait(2), b"jpeg")[2])
        assert started.wait(1)
        finished_at = queue.get(finished.job_id).finished_at
        assert finished_at is not None

        assert queue.prune_completed(now=finished_at + 1) == 0
        assert queue.get(active.job_id) is not None
        assert queue.get(finished.job_id) is not None
        assert video_path.is_file()

        queue.release_media(finished.job_id)
        assert queue.get(finished.job_id) is None
        assert not video_path.exists()
    finally:
        release.set()
        queue.close()


def test_orphan_cleanup_keeps_the_output_path_of_an_active_video_job(tmp_path) -> None:
    temporary_results = tmp_path / "temporary-results"
    temporary_results.mkdir()
    orphan = temporary_results / "ltx-video-orphan.mp4"
    active_output = temporary_results / "ltx-video-active.mp4"
    orphan.write_bytes(b"orphan")
    active_output.write_bytes(b"active")
    queue = GenerationQueue(
        RetentionPolicy(max_items=1, max_age_seconds=0, max_bytes=1),
        video_result_root=temporary_results,
    )
    started = Event()
    release = Event()
    try:
        active = queue.create(
            "video",
            lambda _progress, _cancelled: (started.set(), release.wait(2), active_output)[2],
            temporary_media_path=active_output,
        )
        assert started.wait(1)

        assert queue.cleanup_temporary_video_results(now=time.time() + 1) == 1
        assert not orphan.exists()
        assert active_output.is_file()
        assert queue.get(active.job_id) is not None
    finally:
        release.set()
        queue.close()
