"""Persistent per-user model selection for the local server."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import config_dir


class ModelSelectionStore:
    def __init__(self, default_model_id: str, path: Path | None = None) -> None:
        self.default_model_id = default_model_id
        self.path = path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        return config_dir() / "settings.json"

    def get(self) -> str:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("active_model_id")
            return value if isinstance(value, str) and value else self.default_model_id
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return self.default_model_id

    def set(self, model_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({"active_model_id": model_id}, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.path)
