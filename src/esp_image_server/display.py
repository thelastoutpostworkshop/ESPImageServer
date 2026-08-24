"""In-memory profile for the single ESP32 board and its integrated display."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class DisplayProfile:
    name: str
    width: int
    height: int
    firmware_version: str


class ActiveDisplayStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._profile: DisplayProfile | None = None

    def set(
        self, name: str, width: int, height: int, firmware_version: str,
    ) -> DisplayProfile:
        profile = DisplayProfile(
            name=name,
            width=width,
            height=height,
            firmware_version=firmware_version,
        )
        with self._lock:
            self._profile = profile
        return profile

    def get(self) -> DisplayProfile | None:
        with self._lock:
            return self._profile
