"""Thread-safe storage for the latest generated ESP32 JPEG."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import uuid4


@dataclass(frozen=True)
class LatestImage:
    image_id: str
    jpeg: bytes


class LatestImageStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._image: LatestImage | None = None

    def set(self, jpeg: bytes) -> LatestImage:
        with self._lock:
            self._image = LatestImage(uuid4().hex, jpeg)
            return self._image

    def get(self) -> LatestImage | None:
        with self._lock:
            return self._image
