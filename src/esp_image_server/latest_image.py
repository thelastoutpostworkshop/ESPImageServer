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
class LatestImageAssignment:
    """Source artwork and the display-aspect treatment assigned to it."""

    image: LatestImage
    aspect_mode: str = "crop"


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
        self._broadcast_assignment: LatestImageAssignment | None = None
        self._display_assignments: dict[str, LatestImageAssignment] = {}
        self._renditions: dict[tuple[str, int, int, int, int, str], LatestImageRendition] = {}

    def set(
        self,
        jpeg: bytes,
        display_ids: Iterable[str] | None = None,
        *,
        aspect_mode: str = "crop",
    ) -> LatestImage:
        """Store source artwork globally or assign it to selected displays."""
        if aspect_mode not in {"crop", "fit"}:
            raise ValueError("Display aspect mode must be 'crop' or 'fit'")
        targets = None if display_ids is None else tuple(dict.fromkeys(display_ids))
        if targets == ():
            raise ValueError("At least one target display is required")
        with self._lock:
            image = LatestImage(uuid4().hex, jpeg)
            assignment = LatestImageAssignment(image, aspect_mode)
            if targets is None:
                self._broadcast_assignment = assignment
                self._display_assignments.clear()
            else:
                for display_id in targets:
                    self._display_assignments[display_id] = assignment
            # Source revisions are part of every cache key. Clearing keeps
            # memory bounded after repeated generations and target changes.
            self._renditions.clear()
            return image

    def get(self, display_id: str | None = None) -> LatestImage | None:
        """Return only the assigned source image for legacy callers."""
        assignment = self.get_assignment(display_id)
        return assignment.image if assignment is not None else None

    def get_assignment(self, display_id: str | None = None) -> LatestImageAssignment | None:
        """Return a source image together with its crop/fit treatment."""
        with self._lock:
            if display_id is not None and display_id in self._display_assignments:
                return self._display_assignments[display_id]
            return self._broadcast_assignment

    def rendition(
        self,
        image: LatestImage,
        *,
        width: int,
        height: int,
        rotation: int,
        quality: int,
        aspect_mode: str = "crop",
    ) -> LatestImageRendition:
        """Return a physical-display JPEG and an ETag for its exact settings."""
        if rotation not in {0, 90, 180, 270}:
            raise ValueError("Image rotation must be 0, 90, 180, or 270 degrees")
        if aspect_mode not in {"crop", "fit"}:
            raise ValueError("Display aspect mode must be 'crop' or 'fit'")
        key = (image.image_id, width, height, rotation, quality, aspect_mode)
        with self._lock:
            cached = self._renditions.get(key)
            if cached is not None:
                return cached
            with Image.open(BytesIO(image.jpeg)) as source:
                jpeg = to_display_jpeg(
                    source,
                    width=width,
                    height=height,
                    rotation=rotation,
                    quality=quality,
                    aspect_mode=aspect_mode,
                )
            rendition = LatestImageRendition(
                image_id=image.image_id,
                etag=f'"{image.image_id}-{width}x{height}-r{rotation}-q{quality}-m{aspect_mode}"',
                jpeg=jpeg,
            )
            self._renditions[key] = rendition
            return rendition
