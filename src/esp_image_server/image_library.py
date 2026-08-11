"""Persistent local library of generated images and their settings."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4


class ImageLibrary:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()
        self.index_path = self.path / "index.json"
        self._lock = Lock()

    @staticmethod
    def _default_path() -> Path:
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "images"

    def save(self, jpeg: bytes, metadata: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self.path.mkdir(parents=True, exist_ok=True)
            image_id = uuid4().hex
            created_at = datetime.now(UTC).isoformat()
            filename = f"{created_at[:19].replace(':', '-')}-{image_id[:8]}.jpg"
            image_path = self.path / filename
            temporary_path = image_path.with_suffix(".tmp")
            temporary_path.write_bytes(jpeg)
            temporary_path.replace(image_path)

            record = {
                "id": image_id,
                "filename": filename,
                "created_at": created_at,
                "metadata": metadata,
            }
            records = self._read_index()
            records.insert(0, record)
            self._write_index(records)
            return record

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        with self._lock:
            return self._read_index()[:limit]

    def find_path(self, image_id: str) -> Path | None:
        with self._lock:
            for record in self._read_index():
                if record.get("id") == image_id:
                    path = self.path / str(record.get("filename", ""))
                    return path if path.is_file() else None
        return None

    def _read_index(self) -> list[dict[str, object]]:
        try:
            records = json.loads(self.index_path.read_text(encoding="utf-8"))
            return records if isinstance(records, list) else []
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return []

    def _write_index(self, records: list[dict[str, object]]) -> None:
        temporary_path = self.index_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.index_path)
