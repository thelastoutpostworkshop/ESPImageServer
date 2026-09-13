from io import BytesIO
import hashlib
import logging
import os
from pathlib import Path
import re
from threading import Event
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app import create_app, embed_jpeg_metadata
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_settings import DisplaySettingsStore
from esp_image_server.model_settings import ModelSelectionStore
from esp_image_server.generation_jobs import GenerationCancelled
from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.image_library import ImageLibrary
from esp_image_server.image_processor import to_display_jpeg
from esp_image_server.mjpeg_cache import MjpegConversionCache
from esp_image_server.retention import RetentionPolicy
from esp_image_server.video_library import VideoLibrary


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch) -> None:
    """Keep fake generated test images out of the user's real app data."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))


class FakeGenerator:
    device = "test"
    ready = False

    def __init__(self) -> None:
        self.last_size: tuple[int | None, int | None] | None = None
        self.last_steps: int | None = None
        self.last_seed: int | None = None
        self.generate_calls = 0

    def load(self) -> None:
        self.ready = True

    def activate_model(self, settings: Settings, progress=None) -> None:
        self.ready = False
        self.load()

    def unload(self) -> None:
        self.ready = False

    def generate(self, prompt: str, width: int | None = None, height: int | None = None, progress=None, inference_steps=None, seed=None, cancelled=None, negative_prompt=None) -> Image.Image:
        assert prompt == "a tiny robot"
        self.generate_calls += 1
        self.last_size = (width, height)
        self.last_steps, self.last_seed = inference_steps, seed
        if progress is not None:
            progress(1, 1)
        return Image.new("RGB", (64, 64), "blue")


class CancellableFakeGenerator(FakeGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()

    def generate(self, prompt: str, width=None, height=None, progress=None, inference_steps=None, seed=None, cancelled=None, negative_prompt=None) -> Image.Image:
        self.started.set()
        for step in range(100):
            if cancelled is not None and cancelled():
                raise GenerationCancelled()
            if progress is not None:
                progress(step + 1, 100)
            time.sleep(0.005)
        return Image.new("RGB", (64, 64), "blue")


class BlankFakeGenerator(FakeGenerator):
    def generate(self, prompt: str, width=None, height=None, progress=None, inference_steps=None, seed=None, cancelled=None, negative_prompt=None) -> Image.Image:
        return Image.new("RGB", (64, 64), "black")


class FakeVideoGenerator:
    def generate(self, prompt, width, height, num_frames, fps, steps, seed, output_path, progress, cancelled, source_image_path, model_id, rotation=0) -> Path:
        self.last_rotation = rotation
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        return output_path


def test_generate_returns_jpeg_binary() -> None:
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(response.content)).size == (20, 10)


def test_generate_rejects_a_blank_model_result() -> None:
    app = create_app(Settings(), BlankFakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 500
    assert "blank image" in response.json()["detail"]


def test_health_reports_that_no_generation_is_active() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["generating"] is False
    assert response.json()["image_generating"] is False
    assert response.json()["video_generating"] is False
    assert response.json()["active_image_job"] is None
    assert response.json()["active_video_job"] is None


def test_lifespan_cleans_stale_mjpeg_files_on_startup_and_shutdown_without_removing_referenced_files(tmp_path) -> None:
    cache = MjpegConversionCache(
        tmp_path / "display-mjpeg",
        RetentionPolicy(max_items=2, max_age_seconds=0, max_bytes=1024),
    )
    stale_at_startup = cache.output_path("old", 480, 272, 8, 10)
    protected = cache.output_path("in-use", 480, 272, 8, 10)
    stale_at_startup.parent.mkdir(parents=True)
    stale_at_startup.write_bytes(b"old")
    protected.write_bytes(b"in use")
    os.utime(stale_at_startup, (1, 1))
    os.utime(protected, (1, 1))
    cache.acquire(protected)
    app = create_app(Settings(), FakeGenerator(), mjpeg_cache=cache, enable_mdns=False)

    with TestClient(app):
        assert not stale_at_startup.exists()
        assert protected.is_file()
        stale_at_shutdown = cache.output_path("shutdown", 480, 272, 8, 10)
        stale_at_shutdown.write_bytes(b"shutdown")
        os.utime(stale_at_shutdown, (1, 1))

    assert not stale_at_shutdown.exists()
    assert protected.is_file()
    cache.release(protected)
    assert cache.cleanup(now=2) == 1


def test_startup_cleans_orphaned_temporary_generation_videos(tmp_path) -> None:
    temporary_results = tmp_path / "temporary-results"
    temporary_results.mkdir()
    orphan = temporary_results / "ltx-video-orphan.mp4"
    orphan.write_bytes(b"temporary video")
    os.utime(orphan, (1, 1))
    queue = GenerationQueue(
        RetentionPolicy(max_items=2, max_age_seconds=0, max_bytes=1024),
        video_result_root=temporary_results,
    )
    app = create_app(Settings(), FakeGenerator(), generation_queue=queue, enable_mdns=False)

    with TestClient(app):
        assert not orphan.exists()


def test_console_output_mirrors_server_logs_and_redacts_secrets() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        logging.getLogger("esp_image_server.console_test").warning("Console token=very-secret-value")
        output = client.get("/console-output")
        cleared = client.delete("/console-output")
        empty_output = client.get("/console-output")

    assert output.status_code == 200
    assert any("WARNING esp_image_server.console_test: Console token=[redacted]" in line for line in output.json())
    assert all("very-secret-value" not in line for line in output.json())
    assert cleared.status_code == 204
    assert empty_output.json() == []


def test_generation_job_reports_progress_and_returns_its_image() -> None:
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        created = client.post("/generation-jobs", json={"prompt": "a tiny robot", "model_id": "segmind/SSD-1B"})
        job_id = created.json()["id"]
        for _ in range(20):
            job = client.get(f"/generation-jobs/{job_id}").json()
            if job["status"] == "complete":
                break
            time.sleep(0.01)
        image = client.get(f"/generation-jobs/{job_id}/image")

    assert created.status_code == 202
    assert created.json()["metadata"]["model_id"] == "segmind/SSD-1B"
    assert job["metadata"]["model"]["id"] == "segmind/SSD-1B"
    assert job["progress"] == 100
    assert isinstance(job["generation_time_seconds"], float)
    assert job["generation_time_seconds"] >= 0
    assert isinstance(job["metadata"]["generation_time_seconds"], float)
    assert image.status_code == 200
    assert Image.open(BytesIO(image.content)).size == (20, 10)


def test_generation_job_can_be_cancelled() -> None:
    generator = CancellableFakeGenerator()
    app = create_app(Settings(), generator, enable_mdns=False)
    with TestClient(app) as client:
        created = client.post("/generation-jobs", json={"prompt": "a tiny robot"})
        job_id = created.json()["id"]
        assert generator.started.wait(timeout=1)
        cancelled = client.delete(f"/generation-jobs/{job_id}")
        for _ in range(40):
            job = client.get(f"/generation-jobs/{job_id}").json()
            if job["status"] == "cancelled":
                break
            time.sleep(0.01)

    assert cancelled.status_code == 200
    assert job["status"] == "cancelled"


def test_generate_uses_the_server_default_size_without_an_announced_display() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (466, 466)


def test_generate_rejects_client_selected_dimensions() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot", "width": 320})

    assert response.status_code == 422


def test_generate_accepts_valid_steps_and_a_seed() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(), generator, enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot", "steps": 3, "seed": 42})

    assert response.status_code == 200
    assert (generator.last_steps, generator.last_seed) == (3, 42)


def test_latest_image_is_available_to_esp32_displays() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        generated = client.post("/generate", json={"prompt": "a tiny robot"})
        latest = client.get("/latest.jpg")
        unchanged = client.get("/latest.jpg", headers={"If-None-Match": latest.headers["etag"]})

    assert latest.status_code == 200
    assert latest.content == generated.content
    assert latest.headers["content-type"] == "image/jpeg"
    assert unchanged.status_code == 304


def test_active_esp32_display_sets_the_default_generated_image_size() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(), generator, enable_mdns=False)
    with TestClient(app) as client:
        assert client.get("/display").json() == {"connected": False}
        announcement = client.post(
            "/display", json={
                "name": "JC4827W543 display",
                "width": 480,
                "height": 272,
                "firmware_version": "1.0.0",
            }
        )
        active_display = client.get("/display")
        generated = client.post("/generate", json={"prompt": "a tiny robot"})

    assert announcement.status_code == 201
    assert announcement.json()["firmware_version"] == "1.0.0"
    assert active_display.json()["firmware_version"] == "1.0.0"
    assert Image.open(BytesIO(generated.content)).size == (480, 272)
    assert generator.last_size == (512, 288)


def test_display_firmware_version_is_required_and_uses_semantic_versioning() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        missing = client.post("/display", json={"name": "Test display", "width": 480, "height": 272})
        valid = client.post("/display", json={
            "name": "Test display",
            "width": 480,
            "height": 272,
            "firmware_version": "1.0.0-rc.1+build.4",
        })
        invalid = client.post("/display", json={
            "name": "Test display",
            "width": 480,
            "height": 272,
            "firmware_version": "version one",
        })

    assert missing.status_code == 422
    assert valid.status_code == 201
    assert valid.json()["firmware_version"] == "1.0.0-rc.1+build.4"
    assert invalid.status_code == 422


def test_server_side_display_rotation_generates_for_rotated_aspect_ratio(tmp_path) -> None:
    generator = FakeGenerator()
    rotation_store = DisplaySettingsStore(tmp_path / "display_settings.json")
    app = create_app(Settings(), generator, display_settings_store=rotation_store, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272, "firmware_version": "1.0.0"})
        settings = client.put("/display-settings", json={"rotation": 90})
        generated = client.post("/generate", json={"prompt": "a tiny robot"})

    assert settings.json() == {"rotation": 90}
    assert generator.last_size == (288, 512)
    assert Image.open(BytesIO(generated.content)).size == (480, 272)


def test_ssd_1b_uses_a_larger_aspect_matched_generation_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="segmind/SSD-1B"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272, "firmware_version": "1.0.0"})
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert generator.last_size == (1024, 584)


def test_server_info_explains_the_model_in_maker_friendly_terms(monkeypatch) -> None:
    monkeypatch.setattr("esp_image_server.app.active_lan_address", lambda: "192.168.1.90")
    app = create_app(Settings(model_id="stabilityai/sd-turbo"), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/server-info")

    assert response.status_code == 200
    assert response.json()["version"] == app.version
    assert response.json()["model_name"] == "SD-Turbo"
    assert "cuda" not in response.json()["processing"].lower()
    assert response.json()["local_network_url"] == "http://192.168.1.90:8000"


def test_display_sd_card_routes_store_reports_and_queue_commands() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        assert client.get("/display-sd-card").json() == {"available": False, "files": [], "report_version": 0}
        report = client.post(
            "/display-sd-card/report",
            json={
                "available": True,
                "mode": "sd_card",
                "total_bytes": 1024,
                "used_bytes": 256,
                "files": [{"name": "image.jpg", "size": 128}],
            },
        )
        reported_experience = client.get("/display-experience")
        queued = client.post("/display-sd-card/mode/live_images")
        command = client.get("/display-commands/next")
        experience = client.put("/display-experience", json={"offline_experience": "slideshow", "slideshow_interval_ms": 2300, "slideshow_order": "oldest_first"})
        experience_command = client.get("/display-commands/next")
        preview = client.post("/display-experience/preview", json={"offline_experience": "video_loop", "slideshow_interval_ms": 500, "slideshow_order": "newest_first"})
        preview_command = client.get("/display-commands/next")
        stop_preview = client.delete("/display-experience/preview")
        stop_preview_command = client.get("/display-commands/next")
        sd_card_report = client.get("/display-sd-card").json()

    assert report.status_code == 204
    assert sd_card_report["report_version"] == 1
    assert sd_card_report["reported_at"]
    assert reported_experience.json()["current_mode"] == "sd_card"
    assert reported_experience.json()["slideshow_interval_ms"] == 15000
    assert queued.status_code == 202
    assert command.json()["type"] == "set_mode"
    assert command.json()["mode"] == "live_images"
    assert experience.status_code == 202
    assert experience_command.json()["type"] == "set_display_experience"
    assert experience_command.json()["slideshow_interval_ms"] == 2300
    assert experience_command.json()["slideshow_order"] == "oldest_first"
    assert preview.status_code == 202
    assert preview_command.json()["type"] == "preview_display_experience"
    assert preview_command.json()["offline_experience"] == "video_loop"
    assert stop_preview.status_code == 202
    assert stop_preview_command.json()["type"] == "stop_display_experience_preview"


def test_sd_card_refresh_reports_the_inventory_version_it_requires() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        refresh = client.post("/display-sd-card/refresh")
        acknowledgement = client.post(
            f"/display-commands/{refresh.json()['id']}/ack",
            json={"success": True, "detail": "SD card list refreshed"},
        )
        report = client.post(
            "/display-sd-card/report",
            json={
                "available": True,
                "mode": "server_controlled",
                "total_bytes": 1024,
                "used_bytes": 0,
                "files": [],
            },
        )

    assert acknowledgement.json()["report_version"] == 1
    assert report.status_code == 204


def test_model_selection_is_persisted_after_the_model_loads(tmp_path) -> None:
    store = ModelSelectionStore("stabilityai/sd-turbo", tmp_path / "settings.json")
    app = create_app(Settings(), FakeGenerator(), model_selection_store=store, enable_mdns=False)
    with TestClient(app) as client:
        models = client.get("/models")
        selected = client.post("/models/segmind/SSD-1B/select")

    assert models.status_code == 200
    assert len(models.json()) == 4
    assert next(model for model in models.json() if model["id"] == "stabilityai/sd-turbo")["model_card_url"] == "https://huggingface.co/stabilityai/sd-turbo"
    assert selected.status_code == 200
    assert store.get() == "segmind/SSD-1B"


def test_model_selection_is_saved_for_subsequent_jobs_while_queue_is_busy(tmp_path, monkeypatch) -> None:
    store = ModelSelectionStore("stabilityai/sd-turbo", tmp_path / "settings.json")
    queue = GenerationQueue()
    monkeypatch.setattr(queue, "has_active_job", lambda: True)
    app = create_app(Settings(), FakeGenerator(), generation_queue=queue, model_selection_store=store, enable_mdns=False)

    with TestClient(app) as client:
        selected = client.post("/models/segmind/SSD-1B/select")

    assert selected.status_code == 200
    assert selected.json() == {"status": "selected", "model_id": "segmind/SSD-1B"}
    assert store.get() == "segmind/SSD-1B"


def test_image_model_cache_can_be_removed(tmp_path) -> None:
    cache_dir = tmp_path / "models"
    model_cache = cache_dir / "models--stabilityai--sd-turbo" / "snapshots" / "main"
    model_cache.mkdir(parents=True)
    app = create_app(Settings(model_cache_dir=cache_dir), FakeGenerator(), enable_mdns=False)

    with TestClient(app) as client:
        before = client.get("/models")
        removed = client.delete("/models/stabilityai/sd-turbo")
        after = client.get("/models")

    assert next(model for model in before.json() if model["id"] == "stabilityai/sd-turbo")["installed"] is True
    assert removed.status_code == 200
    assert removed.json() == {"removed": True}
    assert not (cache_dir / "models--stabilityai--sd-turbo").exists()
    assert next(model for model in after.json() if model["id"] == "stabilityai/sd-turbo")["installed"] is False


def test_upgrade_preserves_image_library_model_and_rotation(tmp_path, monkeypatch) -> None:
    """Existing per-user settings must be used when a newer app starts."""
    app_data = tmp_path / "ESPImageServer"
    original_library = tmp_path / "old-images"
    upgraded_library = tmp_path / "kept-images"
    app_settings_store = AppSettingsStore(app_data / "app_settings.json")
    model_store = ModelSelectionStore("stabilityai/sd-turbo", app_data / "settings.json")
    rotation_store = DisplaySettingsStore(app_data / "display_settings.json")

    old_app = create_app(
        Settings(),
        FakeGenerator(),
        model_selection_store=model_store,
        display_settings_store=rotation_store,
        image_library=ImageLibrary(original_library, app_data / "image_library_index.json"),
        app_settings_store=app_settings_store,
        enable_mdns=False,
    )
    with TestClient(old_app) as client:
        assert client.put("/app-settings", json={"image_library_location": str(upgraded_library)}).status_code == 200
        assert client.post("/models/Lykon/dreamshaper-8/select").status_code == 200
        assert client.put("/display-settings", json={"rotation": 270}).status_code == 200

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: Settings()))
    upgraded_app = create_app(
        generator=FakeGenerator(),
        model_selection_store=model_store,
        display_settings_store=rotation_store,
        app_settings_store=app_settings_store,
        enable_mdns=False,
    )
    with TestClient(upgraded_app) as client:
        assert client.get("/app-settings").json()["image_library_location"] == str(upgraded_library)
        assert client.get("/server-info").json()["model_id"] == "Lykon/dreamshaper-8"
        assert client.get("/display-settings").json() == {"rotation": 270}


def test_saved_image_can_be_deleted_from_the_creation_library(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    record = library.save(b"\xff\xd8saved image\xff\xd9", {"prompt": "a tiny robot"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        deleted = client.delete(f"/saved-images/{record['id']}")
        missing = client.get(f"/saved-images/{record['id']}/image")

    assert deleted.status_code == 204
    assert library.list() == []
    assert missing.status_code == 404


def test_saved_images_include_their_sd_card_content_key(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    record = library.save(b"\xff\xd8saved image\xff\xd9", {"prompt": "a tiny robot"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        saved_images = client.get("/saved-images")

    assert saved_images.status_code == 200
    assert saved_images.json()[0]["id"] == record["id"]
    assert saved_images.json()[0]["sd_card_content_key"].startswith("v1-")


def test_saved_images_include_their_display_sized_sd_card_content_key(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    source = BytesIO()
    Image.new("RGB", (80, 80), "purple").save(source, format="JPEG", quality=95)
    metadata = {
        "rotation": 90,
        "broadcast_aspect_mode": "crop",
        "display": {"name": "C6", "width": 172, "height": 320},
    }
    original_jpeg = embed_jpeg_metadata(source.getvalue(), metadata)
    record = library.save(original_jpeg, metadata)
    with Image.open(BytesIO(original_jpeg)) as image:
        display_jpeg = to_display_jpeg(
            image, width=172, height=320, rotation=90, quality=85, aspect_mode="crop",
        )
    expected_key = f"v1-{hashlib.sha256(embed_jpeg_metadata(display_jpeg, metadata)).hexdigest()[:16]}"
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        saved_images = client.get("/saved-images")

    saved = saved_images.json()[0]
    assert saved["id"] == record["id"]
    assert saved["sd_card_content_keys"] == [
        f"v1-{hashlib.sha256(original_jpeg).hexdigest()[:16]}", expected_key,
    ]


def test_deletion_confirmation_video_quality_and_auto_save_video_settings_are_saved(tmp_path) -> None:
    app_settings = AppSettingsStore(tmp_path / "app_settings.json")
    app = create_app(Settings(), FakeGenerator(), app_settings_store=app_settings, enable_mdns=False)

    with TestClient(app) as client:
        initial = client.get("/app-settings")
        updated = client.put("/app-settings", json={"confirm_deletion": False, "video_jpeg_quality": 15, "auto_save_videos": False})

    assert initial.json()["confirm_deletion"] is True
    assert initial.json()["video_jpeg_quality"] == 10
    assert initial.json()["auto_save_videos"] is True
    assert updated.json()["confirm_deletion"] is False
    assert updated.json()["video_jpeg_quality"] == 15
    assert updated.json()["auto_save_videos"] is False
    assert app_settings.get()["confirm_deletion"] is False
    assert app_settings.get()["video_jpeg_quality"] == 15
    assert app_settings.get()["auto_save_videos"] is False


def test_saved_video_can_be_deleted_from_the_creation_library(tmp_path, monkeypatch) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    videos = VideoLibrary(library.path)
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: "ffmpeg.exe")
    monkeypatch.setattr("esp_image_server.video_library.subprocess.run", lambda *args, **kwargs: None)
    record = videos.save(source, {"prompt": "a tiny robot"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        deleted = client.delete(f"/saved-videos/{record['id']}")
        missing = client.get(f"/saved-videos/{record['id']}/video")

    assert deleted.status_code == 204
    assert videos.list() == []
    assert missing.status_code == 404


def test_saved_video_can_be_queued_for_sd_card_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    videos = VideoLibrary(library.path)
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: "ffmpeg.exe")
    monkeypatch.setattr("esp_image_server.video_library.subprocess.run", lambda *args, **kwargs: None)
    record = videos.save(source, {"prompt": "a tiny robot", "fps": 12})
    Image.new("RGB", (64, 64), "blue").save(videos.path / record["thumbnail_filename"], format="JPEG")
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)
    ffmpeg_commands: list[list[str]] = []

    def fake_display_conversion(command, **_kwargs):
        ffmpeg_commands.append(command)
        Path(command[-1]).write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr("esp_image_server.app.bundled_ffmpeg_executable", lambda: "ffmpeg.exe")
    monkeypatch.setattr("esp_image_server.app.subprocess.run", fake_display_conversion)

    with TestClient(app) as client:
        assert client.post("/display", json={"name": "Test display", "width": 480, "height": 272, "firmware_version": "1.0.0"}).status_code == 201
        queued = client.post(f"/display-commands/save-saved-video/{record['id']}")
        command = client.get("/display-commands/next")
        thumbnail = client.get(f"/display-sd-card/thumbnails/{command.json()['filename']}")
        mjpeg = client.get(f"/saved-videos/{record['id']}/mjpeg-download?width=480&height=272&fps=12")
        report = client.post(
            "/display-sd-card/report",
            json={
                "available": True,
                "mode": "server_controlled",
                "total_bytes": 1024,
                "used_bytes": 256,
                "files": [{
                    "name": command.json()["filename"],
                    "type": "video",
                    "content_key": command.json()["content_key"],
                }],
            },
        )
        reused = client.post(f"/display-commands/save-saved-video/{record['id']}")

    assert queued.status_code == 202
    assert command.json()["type"] == "save_saved_video"
    assert command.json()["video_url"] == f"/saved-videos/{record['id']}/mjpeg-download"
    assert command.json()["fps"] == 12
    assert re.fullmatch(
        rf"esp-video-\d{{8}}-\d{{6}}-v1-{record['id']}-480x272-fps12\.mjpeg",
        command.json()["filename"],
    )
    assert command.json()["filename"].endswith(f"-v1-{record['id']}-480x272-fps12.mjpeg")
    assert command.json()["content_key"] == f"v1-{record['id']}-480x272-fps12"
    assert report.status_code == 204
    assert reused.json()["status"] == "already_saved"
    assert reused.json()["filename"] == command.json()["filename"]
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert mjpeg.status_code == 200
    assert "-pix_fmt" in ffmpeg_commands[0]
    assert ffmpeg_commands[0][ffmpeg_commands[0].index("-pix_fmt") + 1] == "yuvj420p"
    assert ffmpeg_commands[0][ffmpeg_commands[0].index("-q:v") + 1] == "10"
    assert any("force_original_aspect_ratio=increase" in argument for argument in ffmpeg_commands[0])
    assert any("crop=480:272" in argument for argument in ffmpeg_commands[0])


def test_retired_video_model_is_not_listed_and_cannot_be_queued(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path / "models"))
    generator = FakeGenerator()
    generator.device = "cuda"
    app = create_app(Settings(), generator, video_generator=FakeVideoGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        models = client.get("/video-models").json()
        rejected = client.post("/video-generation-jobs", json={
            "prompt": "a tiny robot", "model_id": "hunyuanvideo-1.5-480p", "steps": 30,
        })
    assert {model["id"] for model in models} == {
        "ltx-2b-0.9.6-distilled", "ltx-2b-0.9.6-dev", "wan-2.1-t2v-1.3b",
    }
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "This video model is not available"


def test_video_generation_metadata_records_the_active_display() -> None:
    generator = FakeGenerator()
    generator.device = "cuda"
    app = create_app(Settings(), generator, video_generator=FakeVideoGenerator(), enable_mdns=False)

    with TestClient(app) as client:
        announced = client.post("/display", json={"name": "Cheap Yellow Display", "width": 240, "height": 320, "firmware_version": "1.0.0"})
        created = client.post("/video-generation-jobs", json={"prompt": "a tiny robot"})

    assert announced.status_code == 201
    assert created.status_code == 202
    assert created.json()["metadata"]["display"] == {
        "name": "Cheap Yellow Display", "width": 240, "height": 320,
    }


def test_queued_jobs_record_the_registered_display_id() -> None:
    generator = FakeGenerator()
    generator.device = "cuda"
    app = create_app(Settings(), generator, video_generator=FakeVideoGenerator(), enable_mdns=False)

    with TestClient(app) as client:
        display = client.post("/displays/register", json={
            "hardware_id": "aa:bb:cc:dd:ee:20",
            "name": "Kitchen",
            "width": 480,
            "height": 272,
            "firmware_version": "1.0.0",
        }).json()
        image = client.post("/generation-jobs", json={
            "prompt": "a tiny robot", "display_ids": [display["id"]],
        })
        image_job_id = image.json()["id"]
        for _ in range(20):
            if client.get(f"/generation-jobs/{image_job_id}").json()["status"] == "complete":
                break
            time.sleep(0.01)
        video = client.post("/video-generation-jobs", json={
            "prompt": "a tiny robot", "display_ids": [display["id"]],
        })

    assert image.status_code == 202
    assert image.json()["metadata"]["display_id"] == display["id"]
    assert video.status_code == 202
    assert video.json()["metadata"]["display_id"] == display["id"]


def test_selecting_a_saved_image_makes_it_available_to_the_esp32(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    source = BytesIO()
    Image.new("RGB", (64, 64), "red").save(source, format="JPEG")
    record = library.save(source.getvalue(), {"prompt": "saved creation"})
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        selected = client.post(f"/saved-images/{record['id']}/display")
        latest = client.get("/latest.jpg")

    assert selected.status_code == 202
    assert Image.open(BytesIO(latest.content)).size == (20, 10)


def test_saved_image_can_be_center_cropped_for_a_display_sd_card(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    source = BytesIO()
    Image.new("RGB", (64, 32), "red").save(source, format="JPEG")
    record = library.save(source.getvalue(), {"prompt": "wide saved creation"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        prepared = client.get(f"/saved-images/{record['id']}/image?width=20&height=20")

    assert prepared.status_code == 200
    assert Image.open(BytesIO(prepared.content)).size == (20, 20)


def test_display_can_acknowledge_a_request_to_save_the_latest_image_to_sd_card() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        assert client.post("/generate", json={"prompt": "a tiny robot"}).status_code == 200
        queued = client.post("/display-commands/save-latest")
        command = client.get("/display-commands/next")
        acknowledged = client.post(
            f"/display-commands/{queued.json()['id']}/ack",
            json={"success": True, "detail": "Saved /ESPImageServer/esp-image.jpg"},
        )

    assert queued.status_code == 202
    assert command.json()["id"] == queued.json()["id"]
    assert acknowledged.json()["status"] == "complete"
    assert acknowledged.json()["detail"] == "Saved /ESPImageServer/esp-image.jpg"


def test_display_can_save_a_specific_creation_library_image_to_sd_card(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    image = BytesIO()
    Image.new("RGB", (64, 64), "blue").save(image, format="JPEG")
    record = library.save(image.getvalue(), {"prompt": "saved creation"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        queued = client.post(f"/display-commands/save-saved-image/{record['id']}")
        command = client.get("/display-commands/next")
        report = client.post(
            "/display-sd-card/report",
            json={
                "available": True,
                "mode": "server_controlled",
                "total_bytes": 1024,
                "used_bytes": 256,
                "files": [{
                    "name": command.json()["filename"],
                    "type": "image",
                    "content_key": command.json()["content_key"],
                }],
            },
        )
        reused = client.post(f"/display-commands/save-saved-image/{record['id']}")

    assert queued.status_code == 202
    assert command.json()["type"] == "save_saved_image"
    assert command.json()["image_id"] == record["id"]
    assert command.json()["thumbnail_url"].endswith(command.json()["filename"])
    assert command.json()["content_key"].startswith("v1-")
    assert re.fullmatch(
        r"esp-image-\d{8}-\d{6}-v1-[0-9a-f]{16}\.jpg", command.json()["filename"],
    )
    assert report.status_code == 204
    assert reused.json()["status"] == "already_saved"
    assert reused.json()["filename"] == command.json()["filename"]


def test_dreamshaper_uses_an_aspect_matched_sd_1_5_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="Lykon/dreamshaper-8"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272, "firmware_version": "1.0.0"})
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert generator.last_size == (512, 288)


def test_sdxl_uses_a_large_aspect_matched_generation_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="stabilityai/stable-diffusion-xl-base-1.0"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272, "firmware_version": "1.0.0"})
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert generator.last_size == (1024, 584)


def test_browser_test_page_is_available() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text
    assert "/ui/assets/" in response.text
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_welcome_hero_is_available() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/assets/welcome-hero-horizontal.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_esp32_can_pair_retrieve_and_acknowledge_an_image() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    jpeg = b"\xff\xd8test jpeg\xff\xd9"
    with TestClient(app) as client:
        pairing = client.post("/pairing-codes")
        assert pairing.status_code == 201
        registration = client.post(
            "/devices/register",
            json={"pairing_code": pairing.json()["code"], "name": "Kitchen display"},
        )
        assert registration.status_code == 201
        device = registration.json()
        headers = {"X-ESPImage-Token": device["token"]}

        devices = client.get("/devices")
        assert devices.json() == [
            {"id": device["id"], "name": "Kitchen display", "online": True, "queued_images": 0}
        ]

        queued = client.post(
            f"/devices/{device['id']}/images",
            content=jpeg,
            headers={"Content-Type": "image/jpeg"},
        )
        assert queued.status_code == 201

        image = client.get(f"/devices/{device['id']}/next-image?wait_seconds=0", headers=headers)
        assert image.status_code == 200
        assert image.content == jpeg
        image_id = image.headers["x-espimage-image-id"]

        acknowledgement = client.post(
            f"/devices/{device['id']}/ack", json={"image_id": image_id}, headers=headers
        )
        assert acknowledgement.status_code == 200
        assert client.get(f"/devices/{device['id']}/next-image?wait_seconds=0", headers=headers).status_code == 204


def test_device_registration_rejects_an_invalid_pairing_code() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post(
            "/devices/register", json={"pairing_code": "000000", "name": "Test display"}
        )

    assert response.status_code == 400


def test_registered_displays_keep_settings_commands_and_sd_card_reports_isolated() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)

    def register(
        client: TestClient, hardware_id: str, name: str, width: int, height: int,
    ) -> dict[str, object]:
        response = client.post("/displays/register", json={
            "hardware_id": hardware_id,
            "name": name,
            "width": width,
            "height": height,
            "firmware_version": "1.0.0",
            "capabilities": {"sd_card": True},
        })
        assert response.status_code == 201
        return response.json()

    with TestClient(app) as client:
        kitchen = register(client, "aa:bb:cc:dd:ee:01", "Kitchen", 480, 272)
        office = register(client, "aa:bb:cc:dd:ee:02", "Office", 320, 820)
        kitchen_id, office_id = str(kitchen["id"]), str(office["id"])

        displays = client.get("/displays")
        kitchen_rotation = client.put(
            f"/displays/{kitchen_id}/display-settings", json={"rotation": 90},
        )
        kitchen_video_rotation = client.put(
            f"/displays/{kitchen_id}/video-display-settings", json={"rotation": 270},
        )
        office_settings = client.get(f"/displays/{office_id}/display-settings")
        kitchen_video_settings = client.get(f"/displays/{kitchen_id}/video-display-settings")
        office_video_settings = client.get(f"/displays/{office_id}/video-display-settings")
        renamed_office = client.patch(f"/displays/{office_id}", json={"name": "Studio"})
        heartbeat = client.post(
            f"/displays/{kitchen_id}/heartbeat",
            json={"firmware_version": "1.0.1", "capabilities": {"sd_card": True, "touch": False}},
        )

        kitchen_command = client.post(
            f"/displays/{kitchen_id}/display-sd-card/mode/live_images",
        )
        office_command = client.post(
            f"/displays/{office_id}/display-sd-card/mode/sd_card",
        )
        kitchen_next = client.get(
            f"/displays/{kitchen_id}/display-commands/next",
        )
        office_next = client.get(
            f"/displays/{office_id}/display-commands/next",
        )
        wrong_acknowledgement = client.post(
            f"/displays/{office_id}/display-commands/{kitchen_command.json()['id']}/ack",
            json={"success": True, "detail": "wrong display"},
        )
        kitchen_acknowledgement = client.post(
            f"/displays/{kitchen_id}/display-commands/{kitchen_command.json()['id']}/ack",
            json={"success": True, "detail": "done"},
        )
        kitchen_report = client.post(
            f"/displays/{kitchen_id}/display-sd-card/report",
            json={
                "available": True, "mode": "server_controlled", "total_bytes": 1024,
                "used_bytes": 100, "files": [{"name": "kitchen.jpg", "type": "image"}],
            },
        )
        office_report = client.post(
            f"/displays/{office_id}/display-sd-card/report",
            json={
                "available": True, "mode": "sd_card", "total_bytes": 2048,
                "used_bytes": 200, "files": [{"name": "office.jpg", "type": "image"}],
            },
        )
        kitchen_sd_card = client.get(f"/displays/{kitchen_id}/display-sd-card")
        office_sd_card = client.get(f"/displays/{office_id}/display-sd-card")

    assert [display["name"] for display in displays.json()] == ["Kitchen", "Office"]
    assert kitchen_rotation.json() == {"rotation": 90}
    assert kitchen_video_rotation.json() == {"rotation": 270}
    assert office_settings.json() == {"rotation": 0}
    assert kitchen_video_settings.json() == {"rotation": 270}
    assert office_video_settings.json() == {"rotation": 0}
    assert renamed_office.json()["name"] == "Studio"
    assert heartbeat.json()["display"]["firmware_version"] == "1.0.1"
    assert kitchen_command.status_code == 202
    assert office_command.status_code == 202
    assert kitchen_next.json()["id"] == kitchen_command.json()["id"]
    assert office_next.json()["id"] == office_command.json()["id"]
    assert wrong_acknowledgement.status_code == 404
    assert kitchen_acknowledgement.json()["status"] == "complete"
    assert kitchen_report.status_code == 204
    assert office_report.status_code == 204
    assert kitchen_sd_card.json()["files"][0]["name"] == "kitchen.jpg"
    assert office_sd_card.json()["files"][0]["name"] == "office.jpg"


def test_registered_displays_receive_native_renditions_with_independent_etags() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(), generator, enable_mdns=False)
    with TestClient(app) as client:
        kitchen = client.post("/displays/register", json={
            "hardware_id": "aa:bb:cc:dd:ee:03",
            "name": "Kitchen",
            "width": 480,
            "height": 272,
            "firmware_version": "1.0.0",
        }).json()
        office = client.post("/displays/register", json={
            "hardware_id": "aa:bb:cc:dd:ee:04",
            "name": "Office",
            "width": 320,
            "height": 820,
            "firmware_version": "1.0.0",
        }).json()
        kitchen_id, office_id = kitchen["id"], office["id"]
        assert client.put(f"/displays/{kitchen_id}/display-settings", json={"rotation": 90}).status_code == 200

        assert client.post("/generate", json={"prompt": "a tiny robot"}).status_code == 200
        kitchen_latest = client.get(f"/displays/{kitchen_id}/latest.jpg")
        office_latest = client.get(f"/displays/{office_id}/latest.jpg")
        kitchen_unchanged = client.get(
            f"/displays/{kitchen_id}/latest.jpg",
            headers={"If-None-Match": kitchen_latest.headers["etag"]},
        )
        assert client.put(f"/displays/{kitchen_id}/display-settings", json={"rotation": 0}).status_code == 200
        kitchen_after_rotation = client.get(
            f"/displays/{kitchen_id}/latest.jpg",
            headers={"If-None-Match": kitchen_latest.headers["etag"]},
        )
        targeted = client.post(
            "/generate",
            json={"prompt": "a tiny robot", "display_ids": [office_id]},
        )
        kitchen_still_unchanged = client.get(
            f"/displays/{kitchen_id}/latest.jpg",
            headers={"If-None-Match": kitchen_after_rotation.headers["etag"]},
        )
        office_after_targeted_generation = client.get(f"/displays/{office_id}/latest.jpg")
        incompatible_targeting = client.post(
            "/generate",
            json={"prompt": "a tiny robot", "display_ids": [kitchen_id, office_id]},
        )
        cropped = client.post(
            "/generate",
            json={
                "prompt": "a tiny robot",
                "display_ids": [kitchen_id, office_id],
                "broadcast_aspect_mode": "crop",
            },
        )
        kitchen_cropped = client.get(f"/displays/{kitchen_id}/latest.jpg")
        office_cropped = client.get(f"/displays/{office_id}/latest.jpg")
        fitted = client.post(
            "/generate",
            json={
                "prompt": "a tiny robot",
                "display_ids": [kitchen_id, office_id],
                "broadcast_aspect_mode": "fit",
            },
        )
        office_fitted = client.get(f"/displays/{office_id}/latest.jpg")
        calls_before_separate = generator.generate_calls
        separate = client.post(
            "/generate",
            json={
                "prompt": "a tiny robot",
                "display_ids": [kitchen_id, office_id],
                "broadcast_aspect_mode": "separate",
            },
        )
        kitchen_separate = client.get(f"/displays/{kitchen_id}/latest.jpg")
        office_separate = client.get(f"/displays/{office_id}/latest.jpg")

    assert kitchen_latest.status_code == 200
    assert Image.open(BytesIO(kitchen_latest.content)).size == (480, 272)
    assert Image.open(BytesIO(office_latest.content)).size == (320, 820)
    assert kitchen_latest.headers["etag"] != office_latest.headers["etag"]
    assert kitchen_unchanged.status_code == 304
    assert kitchen_after_rotation.status_code == 200
    assert kitchen_after_rotation.headers["etag"] != kitchen_latest.headers["etag"]
    assert targeted.status_code == 200
    assert kitchen_still_unchanged.status_code == 304
    assert office_after_targeted_generation.headers["etag"] != office_latest.headers["etag"]
    assert incompatible_targeting.status_code == 422
    assert cropped.status_code == 200
    assert Image.open(BytesIO(kitchen_cropped.content)).size == (480, 272)
    assert Image.open(BytesIO(office_cropped.content)).size == (320, 820)
    assert fitted.status_code == 200
    fitted_pixel = Image.open(BytesIO(office_fitted.content)).convert("RGB").getpixel((0, 0))
    assert max(fitted_pixel) < 8
    assert separate.status_code == 200
    assert generator.generate_calls - calls_before_separate == 2
    assert Image.open(BytesIO(kitchen_separate.content)).size == (480, 272)
    assert Image.open(BytesIO(office_separate.content)).size == (320, 820)


def test_saved_image_can_target_registered_displays_and_use_their_rendition_route(tmp_path) -> None:
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    source = BytesIO()
    Image.new("RGB", (64, 32), "red").save(source, format="JPEG")
    record = library.save(source.getvalue(), {"prompt": "wide saved creation"})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        kitchen = client.post("/displays/register", json={
            "hardware_id": "aa:bb:cc:dd:ee:05",
            "name": "Kitchen",
            "width": 480,
            "height": 272,
            "firmware_version": "1.0.0",
        }).json()
        office = client.post("/displays/register", json={
            "hardware_id": "aa:bb:cc:dd:ee:06",
            "name": "Office",
            "width": 320,
            "height": 820,
            "firmware_version": "1.0.0",
        }).json()
        selected = client.post(
            f"/saved-images/{record['id']}/display",
            json={"display_ids": [office["id"]]},
        )
        kitchen_latest = client.get(f"/displays/{kitchen['id']}/latest.jpg")
        office_latest = client.get(f"/displays/{office['id']}/latest.jpg")
        saved_for_office = client.get(
            f"/displays/{office['id']}/saved-images/{record['id']}/image?width=320&height=820",
        )
        mixed_without_policy = client.post(
            f"/saved-images/{record['id']}/display",
            json={"display_ids": [kitchen['id'], office['id']]},
        )
        mixed_fitted = client.post(
            f"/saved-images/{record['id']}/display",
            json={
                "display_ids": [kitchen['id'], office['id']],
                "broadcast_aspect_mode": "fit",
            },
        )
        kitchen_fitted = client.get(f"/displays/{kitchen['id']}/latest.jpg")

    assert selected.status_code == 202
    assert selected.json()["display_ids"] == [office["id"]]
    assert kitchen_latest.status_code == 204
    assert Image.open(BytesIO(office_latest.content)).size == (320, 820)
    assert Image.open(BytesIO(saved_for_office.content)).size == (320, 820)
    assert mixed_without_policy.status_code == 422
    assert mixed_fitted.status_code == 202
    assert Image.open(BytesIO(kitchen_fitted.content)).size == (480, 272)
    assert max(Image.open(BytesIO(kitchen_fitted.content)).convert("RGB").getpixel((0, 0))) < 8


def test_registered_media_save_progress_cancel_and_validation() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        ids = []
        for hardware in ('screen-a', 'screen-b'):
            response = client.post('/displays/register', json={
                'hardware_id': hardware, 'name': hardware, 'width': 240, 'height': 320,
                'firmware_version': '1.1.6', 'capabilities': {'sd_card': True},
            })
            assert response.status_code == 201
            ids.append(response.json()['id'])
        save = app.state.display_command_store.queue_save('image.jpg', display_id=ids[0])
        path = f"/displays/{ids[0]}/display-commands/{save['id']}"
        wrong = f"/displays/{ids[1]}/display-commands/{save['id']}"
        body = {'stage': 'verifying', 'received_bytes': 100, 'total_bytes': 100}
        assert client.post(wrong + '/progress', json=body).status_code == 404
        assert client.post(wrong + '/cancel').status_code == 404
        assert client.post(path + '/progress', json={**body, 'received_bytes': 101}).status_code == 422
        assert client.post(path + '/progress', json={**body, 'stage': 'complete'}).status_code == 422
        progress = client.post(path + '/progress', json=body)
        assert progress.status_code == 200
        assert progress.json()['status'] == 'pending'
        assert client.post(path + '/cancel').json()['status'] == 'cancelling'
        stop = client.get(f'/displays/{ids[0]}/display-commands/next').json()
        assert stop['type'] == 'cancel_operation'
        ack = client.post(f"/displays/{ids[0]}/display-commands/{stop['id']}/ack", json={'success': True, 'detail': 'Save cancelled'})
        assert ack.status_code == 200
        assert client.get(path).json()['status'] == 'cancelled'
        report_path = f'/displays/{ids[0]}/display-sd-card'
        assert client.post(report_path + '/report', json={'available': True, 'mode': 'server_controlled', 'total_bytes': 1000, 'used_bytes': 100, 'verified_saves': True, 'files': [{'name': 'image.jpg', 'type': 'image', 'verified': True}]}).status_code == 204
        report = client.get(report_path).json()
        assert report['verified_saves'] is True
        assert report['files'][0]['verified'] is True


@pytest.mark.parametrize("registered", [False, True])
def test_missing_ffmpeg_rejects_video_save_before_replacing_display_command(tmp_path, monkeypatch, registered):
    library = ImageLibrary(tmp_path / 'images', tmp_path / 'index.json')
    videos = VideoLibrary(library.path)
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'fake video')
    monkeypatch.setattr('esp_image_server.video_library.bundled_ffmpeg_executable', lambda: None)
    monkeypatch.setattr('esp_image_server.app.bundled_ffmpeg_executable', lambda: None)
    video = videos.save(source, {'fps': 12})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)
    with TestClient(app) as client:
        if registered:
            result = client.post('/displays/register', json={'hardware_id': 'test-screen', 'name': 'Test display', 'width': 480, 'height': 272, 'firmware_version': '1.1.6'})
            assert result.status_code == 201
            display_id = result.json()['id']
            prefix = f'/displays/{display_id}'
        else:
            client.post('/display', json={'name': 'Test display', 'width': 480, 'height': 272, 'firmware_version': '1.1.6'})
            display_id, prefix = '__legacy__', ''
        store = app.state.display_command_store
        previous = store.queue('set_mode', display_id=display_id, mode='live_images')
        response = client.post(f"{prefix}/display-commands/save-saved-video/{video['id']}")
        assert response.status_code == 503
        assert 'FFmpeg is missing' in response.json()['detail']
        assert store.next(display_id) == previous
        assert store.get(previous['id'], display_id=display_id)['status'] == 'pending'
        # Already committed media requires no converter on the computer.
        store.report_sd_card({'available': True, 'verified_saves': True, 'files': [{
            'name': 'existing.mjpeg', 'type': 'video', 'verified': True,
            'content_key': f"v1-{video['id']}-480x272-fps12",
        }]}, display_id=display_id)
        reused = client.post(f"{prefix}/display-commands/save-saved-video/{video['id']}")
        assert reused.status_code == 202
        assert reused.json()['status'] == 'already_saved'
        assert store.next(display_id) == previous
