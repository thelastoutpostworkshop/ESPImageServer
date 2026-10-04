"""Queued videos retain their own files even when enqueued in the same second."""

from datetime import UTC, datetime
from importlib import import_module
from io import BytesIO
from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.image_library import ImageLibrary


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 3, 12, 0, 0, tzinfo=UTC).astimezone(tz) if tz else cls(2026, 10, 3, 12, 0, 0)


class FakeImageGenerator:
    device = "cuda"
    ready = False

    def unload(self):
        self.ready = False


class BlockingVideoGenerator:
    def __init__(self):
        self.first_written = Event()
        self.release_first = Event()
        self.outputs = {}
        self.sources = {}

    def generate(self, prompt, width, height, num_frames, fps, steps, seed, output_path,
                 progress, cancelled, source_image_path, model_id, rotation=0, negative_prompt=None):
        self.outputs[prompt] = output_path
        self.sources[prompt] = source_image_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"video:{prompt}".encode())
        if prompt == "first":
            self.first_written.set()
            assert self.release_first.wait(3), "Test did not release the first fake video"
        return output_path


@pytest.fixture
def video_app(tmp_path, monkeypatch):
    app_module = import_module("esp_image_server.app")
    monkeypatch.setattr(app_module, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(app_module, "datetime", FrozenDatetime)
    # Fake MP4 bytes must never reach an external thumbnail extractor.
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    for variable in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    settings = AppSettingsStore(tmp_path / "app-settings.json")
    settings.set({"auto_save_videos": False, "auto_check_firmware_updates": False})
    images = ImageLibrary(tmp_path / "gallery", tmp_path / "image-index.json")
    queue = GenerationQueue(video_result_root=tmp_path / "cache" / "videos")
    generator = BlockingVideoGenerator()
    app = app_module.create_app(
        Settings(), FakeImageGenerator(), image_library=images,
        app_settings_store=settings, generation_queue=queue,
        video_generator=generator, enable_mdns=False,
    )
    with TestClient(app) as client:
        try:
            yield SimpleNamespace(client=client, queue=queue, generator=generator, images=images)
        finally:
            generator.release_first.set()
            # The app's close() cancels queued futures without joining its worker.
            # Join here so failed assertions cannot leave writes past fixture cleanup.
            queue._executor.shutdown(wait=True, cancel_futures=True)


def queue_video(client, prompt, source_image_id=None):
    response = client.post("/video-generation-jobs", json={"prompt": prompt, "source_image_id": source_image_id})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def wait_for_complete(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/video-generation-jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        assert job["status"] not in {"failed", "cancelled"}, job
        if job["status"] == "complete":
            return job
        time.sleep(0.01)
    raise AssertionError(f"Fake video {job_id} did not complete")


def save_reference_image(library, color):
    jpeg = BytesIO()
    Image.new("RGB", (4, 4), color).save(jpeg, format="JPEG")
    return library.save(jpeg.getvalue(), {"prompt": color})["id"]


def test_same_second_queued_videos_keep_downloads_and_manual_saves_separate(video_app):
    client, queue, generator = video_app.client, video_app.queue, video_app.generator
    first_source = save_reference_image(video_app.images, "red")
    second_source = save_reference_image(video_app.images, "blue")
    first_id = queue_video(client, "first", first_source)
    assert generator.first_written.wait(1)
    second_id = queue_video(client, "second", second_source)
    assert client.get(f"/video-generation-jobs/{second_id}").json()["status"] == "queued"

    first_path = queue.get(first_id).temporary_media_path
    second_path = queue.get(second_id).temporary_media_path
    assert first_path != second_path
    assert first_path == generator.outputs["first"]
    assert first_path.match("ltx-video-*.mp4") and second_path.match("ltx-video-*.mp4")
    generator.release_first.set()
    wait_for_complete(client, first_id)
    wait_for_complete(client, second_id)
    assert second_path == generator.outputs["second"]
    assert generator.sources["first"] == video_app.images.find_path(first_source)
    assert generator.sources["second"] == video_app.images.find_path(second_source)
    assert client.get("/saved-videos").json() == [], "Automatic saving is disabled"

    saved = []
    for job_id, prompt, source_id in [(first_id, "first", first_source), (second_id, "second", second_source)]:
        download = client.get(f"/video-generation-jobs/{job_id}/video")
        assert download.status_code == 200
        assert download.content == f"video:{prompt}".encode()
        response = client.post(f"/video-generation-jobs/{job_id}/save")
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["metadata"]["prompt"] == prompt
        assert record["metadata"]["source_image_id"] == source_id
        saved.append(record)

    assert saved[0]["filename"] != saved[1]["filename"]
    assert client.delete("/generation-queue").json() == {"cleared": 2}
    assert not first_path.exists() and not second_path.exists()
    for record, prompt in zip(saved, ["first", "second"]):
        download = client.get(f"/saved-videos/{record['id']}/video")
        assert download.status_code == 200
        assert download.content == f"video:{prompt}".encode()


def test_clearing_cancelled_queued_video_cannot_delete_an_active_video_output(video_app):
    client, queue, generator = video_app.client, video_app.queue, video_app.generator
    first_id = queue_video(client, "first")
    assert generator.first_written.wait(1)
    second_id = queue_video(client, "second")
    first_path = queue.get(first_id).temporary_media_path
    second_path = queue.get(second_id).temporary_media_path
    assert queue.get(second_id).status == "queued"

    cancelled = client.delete(f"/video-generation-jobs/{second_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete("/generation-queue").json() == {"cleared": 1}
    assert queue.get(second_id) is None
    assert queue.get(first_id).status == "running"
    assert first_path.read_bytes() == b"video:first"
    assert not second_path.exists()
    assert "second" not in generator.outputs

    generator.release_first.set()
    wait_for_complete(client, first_id)
    assert client.get(f"/video-generation-jobs/{first_id}/video").content == b"video:first"
