"""Queued work keeps its submitted orientation while later preferences change.

The video pipeline and MP4 exporter are stubbed; the real frame sizing and
rotation path runs without loading a model, contacting a board, or using a GPU.
"""

from importlib import import_module
from io import BytesIO
from pathlib import Path
import sys
from threading import Event
from time import monotonic, sleep
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.image_library import ImageLibrary
from esp_image_server.video_generator import LTXVideoGenerator


def quadrant_pattern(width, height):
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for box, color in [
        ((0, 0, width // 2 - 1, height // 2 - 1), "red"),
        ((width // 2, 0, width - 1, height // 2 - 1), "lime"),
        ((0, height // 2, width // 2 - 1, height - 1), "blue"),
        ((width // 2, height // 2, width - 1, height - 1), "yellow"),
    ]:
        draw.rectangle(box, fill=color)
    return image


class RecordingImageGenerator:
    device = "cuda"
    ready = False

    def __init__(self):
        self.sizes = []

    def activate_model(self, settings, progress=None):
        self.ready = True

    def unload(self):
        self.ready = False

    def generate(self, prompt, width, height, **kwargs):
        self.sizes.append((width, height))
        return quadrant_pattern(width, height)


@pytest.fixture
def queue_app(tmp_path, monkeypatch):
    app_module = import_module("esp_image_server.app")
    for variable in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(app_module, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    monkeypatch.setattr("esp_image_server.video_generator.require_video_export_dependencies", lambda: None)

    video_sizes, exported_frames = [], []

    def pipeline(**options):
        video_sizes.append((options["width"], options["height"]))
        return SimpleNamespace(frames=[[quadrant_pattern(options["width"], options["height"])]])

    def export_to_video(frames, filename, fps):
        exported_frames.extend(frame.copy() for frame in frames)
        Path(filename).write_bytes(b"fake MP4: no encoding or model generation")

    # These imports are used only by the real video frame-processing path.
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.export_to_video = export_to_video
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    video = LTXVideoGenerator()
    monkeypatch.setattr(video, "_load", lambda *_: None)
    video._pipeline = pipeline
    video._capabilities = SimpleNamespace(seeded_generator=lambda *_: None)
    monkeypatch.setattr(video, "unload", lambda: None)

    settings = AppSettingsStore(tmp_path / "settings.json")
    settings.set({
        "auto_save_images": True, "auto_save_videos": True,
        "auto_check_firmware_updates": False, "auto_check_app_updates": False,
    })
    queue = GenerationQueue(video_result_root=tmp_path / "cache" / "videos")
    images = RecordingImageGenerator()
    app = app_module.create_app(
        Settings(output_width=240, output_height=320), images,
        image_library=ImageLibrary(tmp_path / "gallery", tmp_path / "index.json"),
        generation_queue=queue, video_generator=video,
        app_settings_store=settings, enable_mdns=False,
    )
    blocked, release = Event(), Event()

    def blocker(progress, cancelled):
        blocked.set()
        assert release.wait(5), "Test did not release the simulated active job"
        return b"completed simulated work"

    with TestClient(app) as client:
        try:
            queue.create("image", blocker)
            assert blocked.wait(2)
            yield SimpleNamespace(
                app=app, client=client, queue=queue, release=release,
                images=images, video_sizes=video_sizes, frames=exported_frames,
            )
        finally:
            release.set()
            queue._executor.shutdown(wait=True, cancel_futures=True)


def register(client, hardware_id, name, width, height, board_target):
    response = client.post("/displays/register", json={
        "hardware_id": hardware_id, "name": name, "width": width, "height": height,
        "board_target": board_target, "firmware_version": "1.1.44",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def wait_complete(client, prefix, job_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        response = client.get(f"/{prefix}-jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        assert job["status"] not in {"failed", "cancelled"}, job
        if job["status"] == "complete":
            return job
        sleep(0.01)
    pytest.fail(f"Simulated {prefix} job did not complete")


def assert_quadrants(image, rotation):
    # Clockwise rotation must preserve all four positions, not just aspect ratio.
    colors = {
        0: [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)],
        90: [(0, 0, 255), (255, 0, 0), (255, 255, 0), (0, 255, 0)],
        180: [(255, 255, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0)],
        270: [(0, 255, 0), (255, 255, 0), (255, 0, 0), (0, 0, 255)],
    }[rotation]
    positions = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
    for (x, y), expected in zip(positions, colors):
        actual = image.getpixel((int(image.width * x), int(image.height * y)))
        assert all(abs(a - e) <= 8 for a, e in zip(actual, expected)), (rotation, actual, expected)


@pytest.mark.parametrize("display_kind", ["registered", "announced", "default"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_waiting_image_and_video_keep_enqueue_rotation_and_native_output(queue_app, display_kind, rotation):
    client = queue_app.client
    prefix, targets = "", {}
    if display_kind == "registered":
        display_id = register(client, "cyd", "CYD", 240, 320, "CHEAP_YELLOW_DISPLAY")
        prefix = f"/displays/{display_id}"
        targets = {"display_ids": [display_id]}
    elif display_kind == "announced":
        assert client.post("/display", json={
            "name": "CYD", "width": 240, "height": 320, "firmware_version": "1.1.44",
        }).status_code == 201

    for setting in ("display-settings", "video-display-settings"):
        assert client.put(f"{prefix}/{setting}", json={"rotation": rotation}).status_code == 200
    image_response = client.post("/generation-jobs", json={"prompt": "quadrants", **targets})
    video_response = client.post("/video-generation-jobs", json={
        "prompt": "quadrants", "width": 240, "height": 320, **targets,
    })
    assert image_response.status_code == 202, image_response.text
    assert video_response.status_code == 202, video_response.text
    image_id, video_id = image_response.json()["id"], video_response.json()["id"]
    assert client.get(f"/generation-jobs/{image_id}").json()["status"] == "queued"
    assert client.get(f"/video-generation-jobs/{video_id}").json()["status"] == "queued"

    # Later selections and a replaced/first announced board must not reinterpret
    # work already in the queue, including 180-degree flips with the same aspect.
    for setting in ("display-settings", "video-display-settings"):
        assert client.put(f"{prefix}/{setting}", json={"rotation": (rotation + 90) % 360}).status_code == 200
    if display_kind != "registered":
        assert client.post("/display", json={
            "name": "Different board", "width": 480, "height": 272, "firmware_version": "1.1.44",
        }).status_code == 201
    queue_app.release.set()
    image_job = wait_complete(client, "generation", image_id)
    video_job = wait_complete(client, "video-generation", video_id)
    for job in (image_job, video_job):
        assert job["metadata"]["rotation"] == rotation

    expected_canvas = (512, 384) if rotation in {90, 270} else (384, 512)
    assert queue_app.images.sizes == [expected_canvas]
    assert queue_app.video_sizes == [expected_canvas]
    response = client.get(f"/generation-jobs/{image_id}/image")
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (240, 320)
        assert_quadrants(image, rotation)
    assert len(queue_app.frames) == 1
    assert queue_app.frames[0].size == (240, 320)
    assert_quadrants(queue_app.frames[0], rotation)
    saved_images, saved_videos = client.get("/saved-images").json(), client.get("/saved-videos").json()
    assert len(saved_images) == len(saved_videos) == 1
    for record in (saved_images[0], saved_videos[0]):
        assert record["metadata"]["rotation"] == rotation
        if display_kind == "default":
            assert record["metadata"]["display"] is None
        else:
            assert record["metadata"]["display"] == {"name": "CYD", "width": 240, "height": 320}
    assert video_job["metadata"]["auto_saved"] is True


def test_separate_broadcast_jobs_keep_each_enqueued_board_rotation(queue_app):
    client = queue_app.client
    cyd = register(client, "cyd", "CYD", 240, 320, "CHEAP_YELLOW_DISPLAY")
    jc = register(client, "jc", "JC", 480, 272, "JC4827W543")
    assert client.put(f"/displays/{cyd}/display-settings", json={"rotation": 90}).status_code == 200
    response = client.post("/generation-jobs", json={
        "prompt": "quadrants", "display_ids": [cyd, jc], "broadcast_aspect_mode": "separate",
    })
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert client.get(f"/generation-jobs/{job_id}").json()["status"] == "queued"
    assert client.put(f"/displays/{cyd}/display-settings", json={"rotation": 270}).status_code == 200
    assert client.put(f"/displays/{jc}/display-settings", json={"rotation": 180}).status_code == 200
    queue_app.release.set()
    job = wait_complete(client, "generation", job_id)
    assert job["metadata"]["rotation"] == 90
    assert queue_app.images.sizes == [(512, 384), (512, 288)]
    images = {image["metadata"]["display_ids"][0]: image for image in client.get("/saved-images").json()}
    assert set(images) == {cyd, jc}
    assert images[cyd]["metadata"]["rotation"] == 90
    assert images[jc]["metadata"]["rotation"] == 0
