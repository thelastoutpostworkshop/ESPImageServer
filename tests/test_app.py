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

    def generate(self, prompt: str) -> Image.Image:
        assert prompt == "a tiny robot"
        return Image.new("RGB", (64, 64), "blue")


def test_generate_returns_jpeg_binary() -> None:
    app = create_app(Settings(output_width=20, output_height=10), FakeGenerator())
    with TestClient(app) as client:
        response = client.post("/generate", json={"prompt": "a tiny robot"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(response.content)).size == (20, 10)
