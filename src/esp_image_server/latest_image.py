"""Master artwork and cached display-specific JPEG renditions."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from threading import Lock
from typing import Iterable
from uuid import uuid4

from PIL import Image

from .image_processor import to_display_jpeg


@dataclass(frozen=True)
class LatestImage:
    """One source JPEG which can be fitted for several physical displays."""

    image_id: str
    jpeg: bytes


@dataclass(frozen=True)
class LatestImageRendition:
    """A cached JPEG for a particular revision and display configuration."""

    image_id: str
    etag: str
    jpeg: bytes


class LatestImageStore:
    """Keep master artwork once and derive display-sized JPEGs on demand.

    A source set without explicit targets is the broadcast image. An explicitly
    targeted source overrides only those displays, leaving every other screen
    on its prior broadcast or targeted artwork.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._broadcast_image: LatestImage | None = None
        self._display_images: dict[str, LatestImage] = {}
        self._renditions: dict[tuple[str, int, int, int, int], LatestImageRendition] = {}

    def set(self, jpeg: bytes, display_ids: Iterable[str] | None = None) -> LatestImage:
        """Store source artwork globally or assign it to selected displays."""
        targets = None if display_ids is None else tuple(dict.fromkeys(display_ids))
        if targets == ():
            raise ValueError("At least one target display is required")
        with self._lock:
            image = LatestImage(uuid4().hex, jpeg)
            if targets is None:
                self._broadcast_image = image
                self._display_images.clear()
            else:
                for display_id in targets:
                    self._display_images[display_id] = image
            # Source revisions are part of every cache key. Clearing keeps
            # memory bounded after repeated generations and target changes.
            self._renditions.clear()
            return image

    def get(self, display_id: str | None = None) -> LatestImage | None:
        with self._lock:
            if display_id is not None and display_id in self._display_images:
                return self._display_images[display_id]
            return self._broadcast_image

    def rendition(
        self,
        image: LatestImage,
        *,
        width: int,
        height: int,
        rotation: int,
        quality: int,
    ) -> LatestImageRendition:
        """Return a physical-display JPEG and an ETag for its exact settings."""
        if rotation not in {0, 90, 180, 270}:
            raise ValueError("Image rotation must be 0, 90, 180, or 270 degrees")
        key = (image.image_id, width, height, rotation, quality)
        with self._lock:
            cached = self._renditions.get(key)
            if cached is not None:
                return cached
            with Image.open(BytesIO(image.jpeg)) as source:
                jpeg = to_display_jpeg(
                    source, width=width, height=height, rotation=rotation, quality=quality,
                )
            rendition = LatestImageRendition(
                image_id=image.image_id,
                etag=f'"{image.image_id}-{width}x{height}-r{rotation}-q{quality}"',
                jpeg=jpeg,
            )
            self._renditions[key] = rendition
            return rendition
