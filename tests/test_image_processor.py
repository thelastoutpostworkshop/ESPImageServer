from io import BytesIO

from PIL import Image

from esp_image_server.image_processor import to_display_jpeg, to_jpeg


def test_to_jpeg_returns_requested_dimensions() -> None:
    source = Image.new("RGBA", (800, 400), "red")
    jpeg = to_jpeg(source, width=466, height=466, quality=85)
    decoded = Image.open(BytesIO(jpeg))

    assert decoded.format == "JPEG"
    assert decoded.size == (466, 466)


def test_to_display_jpeg_fit_adds_black_borders_instead_of_cropping() -> None:
    source = Image.new("RGB", (80, 40), "red")
    jpeg = to_display_jpeg(
        source,
        width=40,
        height=40,
        rotation=0,
        quality=85,
        aspect_mode="fit",
    )
    decoded = Image.open(BytesIO(jpeg)).convert("RGB")

    assert max(decoded.getpixel((0, 0))) < 8
    red, green, blue = decoded.getpixel((20, 20))
    assert red > 180
    assert green < 30
    assert blue < 30
