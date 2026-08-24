from io import BytesIO
import logging
from pathlib import Path
from threading import Event
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app import create_app
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.display_settings import DisplaySettingsStore
from esp_image_server.model_settings import ModelSelectionStore
from esp_image_server.generation_jobs import GenerationCancelled
from esp_image_server.generation_queue import GenerationQueue
from esp_image_server.image_library import ImageLibrary
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

    def load(self) -> None:
        self.ready = True

    def activate_model(self, settings: Settings, progress=None) -> None:
        self.ready = False
        self.load()

    def unload(self) -> None:
        self.ready = False

    def generate(self, prompt: str, width: int | None = None, height: int | None = None, progress=None, inference_steps=None, seed=None, cancelled=None, negative_prompt=None) -> Image.Image:
        assert prompt == "a tiny robot"
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
    def generate(self, prompt, width, height, num_frames, fps, steps, seed, output_path, progress, cancelled, source_image_path, model_id) -> Path:
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
        created = client.post("/generation-jobs", json={"prompt": "a tiny robot"})
        job_id = created.json()["id"]
        for _ in range(20):
            job = client.get(f"/generation-jobs/{job_id}").json()
            if job["status"] == "complete":
                break
            time.sleep(0.01)
        image = client.get(f"/generation-jobs/{job_id}/image")

    assert created.status_code == 202
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
            "/display", json={"name": "JC4827W543 display", "width": 480, "height": 272}
        )
        generated = client.post("/generate", json={"prompt": "a tiny robot"})

    assert announcement.status_code == 201
    assert Image.open(BytesIO(generated.content)).size == (480, 272)
    assert generator.last_size == (512, 288)


def test_server_side_display_rotation_generates_for_rotated_aspect_ratio(tmp_path) -> None:
    generator = FakeGenerator()
    rotation_store = DisplaySettingsStore(tmp_path / "display_settings.json")
    app = create_app(Settings(), generator, display_settings_store=rotation_store, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272})
        settings = client.put("/display-settings", json={"rotation": 90})
        generated = client.post("/generate", json={"prompt": "a tiny robot"})

    assert settings.json() == {"rotation": 90}
    assert generator.last_size == (288, 512)
    assert Image.open(BytesIO(generated.content)).size == (480, 272)


def test_ssd_1b_uses_a_larger_aspect_matched_generation_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="segmind/SSD-1B"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272})
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert generator.last_size == (1024, 584)


def test_server_info_explains_the_model_in_maker_friendly_terms() -> None:
    app = create_app(Settings(model_id="stabilityai/sd-turbo"), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/server-info")

    assert response.status_code == 200
    assert response.json()["version"] == app.version
    assert response.json()["model_name"] == "SD-Turbo"
    assert "cuda" not in response.json()["processing"].lower()


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
        assert client.post("/display", json={"name": "Test display", "width": 480, "height": 272}).status_code == 201
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


def test_video_generation_metadata_records_the_active_display() -> None:
    generator = FakeGenerator()
    generator.device = "cuda"
    app = create_app(Settings(), generator, video_generator=FakeVideoGenerator(), enable_mdns=False)

    with TestClient(app) as client:
        announced = client.post("/display", json={"name": "Cheap Yellow Display", "width": 240, "height": 320})
        created = client.post("/video-generation-jobs", json={"prompt": "a tiny robot"})

    assert announced.status_code == 201
    assert created.status_code == 202
    assert created.json()["metadata"]["display"] == {
        "name": "Cheap Yellow Display", "width": 240, "height": 320,
    }


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
    assert report.status_code == 204
    assert reused.json()["status"] == "already_saved"
    assert reused.json()["filename"] == command.json()["filename"]


def test_dreamshaper_uses_an_aspect_matched_sd_1_5_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="Lykon/dreamshaper-8"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272})
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert generator.last_size == (512, 288)


def test_sdxl_uses_a_large_aspect_matched_generation_canvas() -> None:
    generator = FakeGenerator()
    app = create_app(Settings(model_id="stabilityai/stable-diffusion-xl-base-1.0"), generator, enable_mdns=False)
    with TestClient(app) as client:
        client.post("/display", json={"name": "JC4827W543 display", "width": 480, "height": 272})
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
