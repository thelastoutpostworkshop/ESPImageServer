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
