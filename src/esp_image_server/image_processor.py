"""Conversion of generated images to display-sized JPEGs."""

from __future__ import annotations

from io import BytesIO
from PIL import Image, ImageOps


def to_jpeg(image: Image.Image, *, width: int, height: int, quality: int) -> bytes:
    """Center-crop, resize, and encode an image as a baseline JPEG."""
    fitted = ImageOps.fit(
        image.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
    )
    buffer = BytesIO()
    fitted.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def to_display_jpeg(
    image: Image.Image,
    *,
    width: int,
    height: int,
    rotation: int,
    quality: int,
) -> bytes:
    """Rotate artwork for a physical display, then crop and encode it."""
    if rotation == 90:
        image = image.transpose(Image.Transpose.ROTATE_270)
    elif rotation == 180:
        image = image.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        image = image.transpose(Image.Transpose.ROTATE_90)
    elif rotation != 0:
        raise ValueError("Image rotation must be 0, 90, 180, or 270 degrees")
    return to_jpeg(image, width=width, height=height, quality=quality)
