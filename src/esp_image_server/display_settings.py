"""Persistent server-side presentation settings for the active ESP32 display."""

from __future__ import annotations

import json
import os
from pathlib import Path


VALID_ROTATIONS = {0, 90, 180, 270}


class DisplaySettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "display_settings.json"

    def get_rotation(self) -> int:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("image_rotation", 0)
            return value if value in VALID_ROTATIONS else 0
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return 0

    def set_rotation(self, rotation: int) -> int:
        if rotation not in VALID_ROTATIONS:
            raise ValueError("Image rotation must be 0, 90, 180, or 270 degrees")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({"image_rotation": rotation}, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.path)
        return rotation
