from io import BytesIO

from PIL import Image

from esp_image_server.image_processor import to_jpeg


def test_to_jpeg_returns_requested_dimensions() -> None:
    source = Image.new("RGBA", (800, 400), "red")
    jpeg = to_jpeg(source, width=466, height=466, quality=85)
    decoded = Image.open(BytesIO(jpeg))

    assert decoded.format == "JPEG"
    assert decoded.size == (466, 466)
