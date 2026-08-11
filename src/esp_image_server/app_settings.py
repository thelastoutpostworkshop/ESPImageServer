"""Persistent user-configurable application settings."""

from __future__ import annotations

import json
import os
from pathlib import Path


class AppSettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "app_settings.json"

    def get(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}

    def set(self, values: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.path)
