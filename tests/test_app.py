from io import BytesIO
import time

from fastapi.testclient import TestClient
from PIL import Image

from esp_image_server.app import create_app
from esp_image_server.config import Settings
from esp_image_server.model_settings import ModelSelectionStore


class FakeGenerator:
    device = "test"
    ready = False

    def __init__(self) -> None:
        self.last_size: tuple[int | None, int | None] | None = None
        self.last_steps: int | None = None
        self.last_seed: int | None = None

    def load(self) -> None:
        self.ready = True

    def activate_model(self, settings: Settings) -> None:
        self.ready = False
        self.load()

    def generate(self, prompt: str, width: int | None = None, height: int | None = None, progress=None, inference_steps=None, seed=None) -> Image.Image:
        assert prompt == "a tiny robot"
        self.last_size = (width, height)
        self.last_steps, self.last_seed = inference_steps, seed
        if progress is not None:
            progress(1, 1)
        return Image.new("RGB", (64, 64), "blue")


def test_generate_returns_jpeg_binary() -> None:
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(response.content)).size == (20, 10)


def test_health_reports_that_no_generation_is_active() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["generating"] is False


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
    assert response.json()["model_name"] == "SD-Turbo"
    assert "cuda" not in response.json()["processing"].lower()


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
