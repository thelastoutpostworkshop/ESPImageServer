from io import BytesIO
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
        assert client.get("/display-sd-card").json() == {"available": False, "files": []}
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
        queued = client.post("/display-sd-card/mode/live_images")
        command = client.get("/display-commands/next")

    assert report.status_code == 204
    assert queued.status_code == 202
    assert command.json()["type"] == "set_mode"
    assert command.json()["mode"] == "live_images"


def test_model_selection_is_persisted_after_the_model_loads(tmp_path) -> None:
    store = ModelSelectionStore("stabilityai/sd-turbo", tmp_path / "settings.json")
    app = create_app(Settings(), FakeGenerator(), model_selection_store=store, enable_mdns=False)
    with TestClient(app) as client:
        models = client.get("/models")
        selected = client.post("/models/segmind/SSD-1B/select")

    assert models.status_code == 200
    assert len(models.json()) == 4
    assert selected.status_code == 200
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


def test_deletion_confirmation_setting_is_saved(tmp_path) -> None:
    app_settings = AppSettingsStore(tmp_path / "app_settings.json")
    app = create_app(Settings(), FakeGenerator(), app_settings_store=app_settings, enable_mdns=False)

    with TestClient(app) as client:
        initial = client.get("/app-settings")
        updated = client.put("/app-settings", json={"confirm_deletion": False})

    assert initial.json()["confirm_deletion"] is True
    assert updated.json()["confirm_deletion"] is False
    assert app_settings.get()["confirm_deletion"] is False


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
    library = ImageLibrary(tmp_path / "images", tmp_path / "image_library_index.json")
    videos = VideoLibrary(library.path)
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: "ffmpeg.exe")
    monkeypatch.setattr("esp_image_server.video_library.subprocess.run", lambda *args, **kwargs: None)
    record = videos.save(source, {"prompt": "a tiny robot", "fps": 12})
    app = create_app(Settings(), FakeGenerator(), image_library=library, enable_mdns=False)

    with TestClient(app) as client:
        queued = client.post(f"/display-commands/save-saved-video/{record['id']}")
        command = client.get("/display-commands/next")

    assert queued.status_code == 202
    assert command.json()["type"] == "save_saved_video"
    assert command.json()["video_url"] == f"/saved-videos/{record['id']}/mjpeg-download"
    assert command.json()["fps"] == 12
    assert command.json()["filename"].endswith("-fps12.mjpeg")


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

    assert queued.status_code == 202
    assert command.json()["type"] == "save_saved_image"
    assert command.json()["image_id"] == record["id"]
    assert command.json()["thumbnail_url"].endswith(command.json()["filename"])


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
