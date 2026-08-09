from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from esp_image_server.app import create_app
from esp_image_server.config import Settings


class FakeGenerator:
    device = "test"
    ready = False

    def load(self) -> None:
        self.ready = True

    def generate(self, prompt: str, width: int | None = None, height: int | None = None) -> Image.Image:
        assert prompt == "a tiny robot"
        return Image.new("RGB", (64, 64), "blue")


def test_generate_returns_jpeg_binary() -> None:
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(response.content)).size == (20, 10)


def test_generate_uses_requested_esp32_image_size() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot", "width": 320, "height": 240})

    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (320, 240)


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
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        assert client.get("/display").json() == {"connected": False}
        announcement = client.post(
            "/display", json={"name": "JC4827W543 display", "width": 480, "height": 272}
        )
        generated = client.post("/generate", json={"prompt": "a tiny robot"})

    assert announcement.status_code == 201
    assert Image.open(BytesIO(generated.content)).size == (480, 272)


def test_server_info_explains_the_model_in_maker_friendly_terms() -> None:
    app = create_app(Settings(model_id="stabilityai/sd-turbo"), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/server-info")

    assert response.status_code == 200
    assert response.json()["model_name"] == "SD-Turbo"
    assert "cuda" not in response.json()["processing"].lower()


def test_browser_test_page_is_available() -> None:
    app = create_app(Settings(), FakeGenerator(), enable_mdns=False)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Describe an image" in response.text
    assert "/assets/welcome-hero-horizontal.png" in response.text


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
