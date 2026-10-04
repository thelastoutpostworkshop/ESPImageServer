"""Video negative prompts follow model capabilities, defaults, and saved settings."""

from importlib import import_module
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.image_library import ImageLibrary
from esp_image_server.video_generator import DEFAULT_VIDEO_NEGATIVE_PROMPT, LTXVideoGenerator
from esp_image_server.video_library import VideoLibrary


DISTILLED = "ltx-2b-0.9.6-distilled"
QUALITY = "ltx-2b-0.9.6-dev"
WAN = "wan-2.1-t2v-1.3b"


class FakeImageGenerator:
    device = "cuda"
    ready = False

    def __init__(self):
        self.unload_calls = 0

    def unload(self):
        self.unload_calls += 1


class RecordingVideoGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, width, height, num_frames, fps, steps, seed, output_path,
                 progress, cancelled, source_image_path, model_id, rotation=0, negative_prompt=None):
        self.calls.append({"model_id": model_id, "negative_prompt": negative_prompt})
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake video; no model or GPU work")
        return output_path


@pytest.fixture
def video_app(tmp_path, monkeypatch):
    app_module = import_module("esp_image_server.app")
    monkeypatch.setattr(app_module, "cache_dir", lambda: tmp_path / "cache")
    # Fake MP4 data must never be handed to the thumbnail executable.
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    for variable in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "ESP_IMAGE_MODEL_CACHE"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    settings = AppSettingsStore(tmp_path / "app-settings.json")
    settings.set({"auto_save_videos": True, "auto_check_firmware_updates": False})
    images = ImageLibrary(tmp_path / "gallery", tmp_path / "image-index.json")
    queue = GenerationQueue(video_result_root=tmp_path / "cache" / "videos")
    image_generator = FakeImageGenerator()
    generator = RecordingVideoGenerator()
    app = app_module.create_app(
        Settings(), image_generator, image_library=images,
        app_settings_store=settings, generation_queue=queue,
        video_generator=generator, enable_mdns=False,
    )
    with TestClient(app) as client:
        try:
            yield SimpleNamespace(
                client=client, queue=queue, generator=generator,
                image_generator=image_generator, settings=settings, images=images,
            )
        finally:
            queue._executor.shutdown(wait=True, cancel_futures=True)


def create_video(video_app, model_id, extra=None):
    response = video_app.client.post("/video-generation-jobs", json={
        "prompt": "a robot walking through a garden", "model_id": model_id,
        "steps": 8 if model_id == DISTILLED else 30, **(extra or {}),
    })
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = video_app.client.get(f"/video-generation-jobs/{job_id}").json()
        assert job["status"] not in {"failed", "cancelled"}, job
        if job["status"] == "complete":
            return job
        time.sleep(0.01)
    pytest.fail("Fake video generation did not complete")


@pytest.mark.parametrize("model_id", [QUALITY, WAN])
@pytest.mark.parametrize("extra,expected", [
    ({}, DEFAULT_VIDEO_NEGATIVE_PROMPT),
    ({"negative_prompt": " visible captions, flashing lights "}, " visible captions, flashing lights "),
    ({"negative_prompt": ""}, ""),
    ({"negative_prompt": None}, None),
    ({"negative_prompt": "  \n "}, ""),
])
def test_capable_models_forward_and_save_effective_negative_prompt(video_app, model_id, extra, expected):
    job = create_video(video_app, model_id, extra)
    assert job["metadata"]["negative_prompt"] == expected
    assert video_app.generator.calls == [{"model_id": model_id, "negative_prompt": expected}]
    assert video_app.image_generator.unload_calls == 1
    saved = video_app.client.get("/saved-videos").json()
    assert len(saved) == 1
    assert saved[0]["metadata"]["negative_prompt"] == expected
    # Reading a fresh library instance proves the setting is durable on disk.
    assert VideoLibrary(video_app.images.path).list()[0]["metadata"]["negative_prompt"] == expected


@pytest.mark.parametrize("extra", [{}, {"negative_prompt": None}, {"negative_prompt": ""}, {"negative_prompt": "  \n "}])
def test_distilled_omitted_or_cleared_negative_prompt_has_no_effective_value(video_app, extra):
    job = create_video(video_app, DISTILLED, extra)
    assert video_app.generator.calls == [{"model_id": DISTILLED, "negative_prompt": None}]
    assert job["metadata"]["negative_prompt"] is None
    assert video_app.client.get("/saved-videos").json()[0]["metadata"]["negative_prompt"] is None


@pytest.mark.parametrize("model_id,negative_prompt", [
    (DISTILLED, "watermarks"), (QUALITY, "x" * 1001), (WAN, "x" * 1001),
])
def test_invalid_video_negative_prompt_is_rejected_before_queue_or_handoff(video_app, model_id, negative_prompt):
    response = video_app.client.post("/video-generation-jobs", json={
        "prompt": "a robot", "model_id": model_id,
        "steps": 8 if model_id == DISTILLED else 30,
        "negative_prompt": negative_prompt,
    })
    assert response.status_code == 422, response.text
    if model_id == DISTILLED:
        assert "does not support negative prompts" in response.json()["detail"]
    assert video_app.client.get("/generation-queue").json() == []
    assert video_app.generator.calls == []
    assert video_app.image_generator.unload_calls == 0


def test_manual_video_save_preserves_maximum_length_negative_prompt(video_app):
    assert video_app.client.put("/app-settings", json={"auto_save_videos": False}).status_code == 200
    expected = "x" * 1000
    job = create_video(video_app, QUALITY, {"negative_prompt": expected})
    assert video_app.client.get("/saved-videos").json() == []
    response = video_app.client.post(f"/video-generation-jobs/{job['id']}/save")
    assert response.status_code == 201, response.text
    assert response.json()["metadata"]["negative_prompt"] == expected
    assert VideoLibrary(video_app.images.path).list()[0]["metadata"]["negative_prompt"] == expected


def test_video_model_catalog_exposes_usable_negative_prompt_defaults(video_app):
    response = video_app.client.get("/video-models")
    assert response.status_code == 200
    models = {model["id"]: model for model in response.json()}
    assert models[DISTILLED]["supports_negative_prompt"] is False
    assert models[DISTILLED]["default_negative_prompt"] is None
    for model_id in (QUALITY, WAN):
        assert models[model_id]["supports_negative_prompt"] is True
        assert models[model_id]["default_negative_prompt"] == DEFAULT_VIDEO_NEGATIVE_PROMPT


@pytest.mark.parametrize("model_id,negative_prompt,reference", [
    (QUALITY, "watermarks", False), (QUALITY, "watermarks", True),
    (WAN, "watermarks", False), (QUALITY, "", False), (WAN, None, False),
    (DISTILLED, None, False),
])
def test_video_generator_forwards_negative_prompt_to_selected_pipeline(tmp_path, monkeypatch, model_id, negative_prompt, reference):
    """Exercise real generator glue with fake pipelines, tensors, and exporter."""
    module = import_module("esp_image_server.video_generator")
    calls = []

    class Pipeline:
        scheduler = vae = text_encoder = tokenizer = transformer = object()

        def __init__(self, kind):
            self.kind = kind

        def __call__(self, **kwargs):
            calls.append((self.kind, kwargs))
            return SimpleNamespace(frames=[[Image.new("RGB", (8, 8), "blue")]])

    fake_diffusers = ModuleType("diffusers")
    fake_diffusers.LTXImageToVideoPipeline = lambda **kwargs: Pipeline("image-to-video")
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.export_to_video = lambda frames, path, fps: Path(path).write_bytes(b"fake export")
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    monkeypatch.setattr(module, "require_video_export_dependencies", lambda: None)
    generator = LTXVideoGenerator()
    generator._pipeline = Pipeline("text-to-video")
    generator._capabilities = SimpleNamespace(seeded_generator=lambda *args: None)
    monkeypatch.setattr(generator, "_load", lambda *args: None)
    source = None
    if reference:
        source = tmp_path / "source.jpg"
        Image.new("RGB", (16, 16), "red").save(source)
    output = tmp_path / "fake-output.mp4"
    result = generator.generate(
        "a robot", 64, 64, 9, 8, 8 if model_id == DISTILLED else 30,
        None, output, lambda *args: None, lambda: False,
        source_image_path=source, model_id=model_id, negative_prompt=negative_prompt,
    )
    assert result == output and output.read_bytes() == b"fake export"
    assert len(calls) == 1
    kind, options = calls[0]
    assert kind == ("image-to-video" if reference else "text-to-video")
    assert options["negative_prompt"] == negative_prompt
    assert options["guidance_scale"] == {DISTILLED: 1.0, QUALITY: 3.0, WAN: 6.0}[model_id]
