"""Persistent local library of generated images and their settings."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from threading import Lock
from uuid import uuid4

from .paths import data_dir


class ImageLibrary:
    def __init__(self, path: Path | None = None, index_path: Path | None = None) -> None:
        self.path = path or self._default_path()
        self.index_path = index_path or self._default_index_path()
        self.legacy_index_path = self.path / "index.json"
        self._lock = Lock()
        self._migrate_legacy_index()

    @staticmethod
    def _default_path() -> Path:
        return data_dir() / "images"

    @staticmethod
    def _default_index_path() -> Path:
        return data_dir() / "image_library_index.json"

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
                "source_sha256": hashlib.sha256(jpeg).hexdigest(),
            }
            records = self._read_index()
            records.insert(0, record)
            self._write_index(records)
            return record

    def remember_sd_card_rendition(self, source_jpeg: bytes, content_key: str) -> bool:
        """Associate bytes sent to a display with their exact saved source JPEG.

        Metadata alone cannot identify a creation: two images can share the
        same settings. Older index records are lazily given their full source
        hash so they can participate without changing the image files.
        """
        source_sha256 = hashlib.sha256(source_jpeg).hexdigest()
        changed = False
        matched = False
        with self._lock:
            records = self._read_index()
            for record in records:
                if not record.get("source_sha256"):
                    image_path = self.path / str(record.get("filename", ""))
                    try:
                        # Exact source bytes must have the same length. Avoid
                        # reading every old image just to find one creation.
                        if image_path.stat().st_size != len(source_jpeg):
                            continue
                        jpeg = image_path.read_bytes()
                    except OSError:
                        continue
                    if hashlib.sha256(jpeg).hexdigest() != source_sha256:
                        continue
                    record["source_sha256"] = source_sha256
                    changed = True
                if record.get("source_sha256") != source_sha256:
                    continue
                matched = True
                keys = record.get("sd_card_rendition_keys", [])
                keys = list(keys) if isinstance(keys, list) else []
                if content_key not in keys:
                    keys.append(content_key)
                    record["sd_card_rendition_keys"] = keys
                    changed = True
            if changed:
                self._write_index(records)
        return matched

    def list(self, limit: int | None = 50) -> list[dict[str, object]]:
        with self._lock:
            return self._read_index()[:limit]

    def find_path(self, image_id: str) -> Path | None:
        with self._lock:
            for record in self._read_index():
                if record.get("id") == image_id:
                    path = self.path / str(record.get("filename", ""))
                    return path if path.is_file() else None
        return None

    def delete(self, image_id: str) -> bool:
        """Remove a saved image and its library record."""
        with self._lock:
            records = self._read_index()
            record = next((item for item in records if item.get("id") == image_id), None)
            if record is None:
                return False
            image_path = self.path / str(record.get("filename", ""))
            try:
                image_path.unlink(missing_ok=True)
            except OSError as exc:
                raise OSError(f"Could not remove saved image: {exc}") from exc
            self._write_index([item for item in records if item.get("id") != image_id])
            return True

    def relocate(self, target: Path) -> Path:
        """Move the whole library so its index and existing images stay together."""
        with self._lock:
            target = target.expanduser().resolve()
            current = self.path.resolve()
            if target == current:
                return self.path
            if current in target.parents:
                raise ValueError("The new image library location cannot be inside the current library")
            if target.exists() and any(target.iterdir()):
                raise ValueError("Choose an empty folder for the image library")
            if target.exists():
                target.rmdir()
            target.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                shutil.move(str(self.path), str(target))
            else:
                target.mkdir(parents=True, exist_ok=True)
            self.path = target
            self.legacy_index_path = self.path / "index.json"
            return self.path

    def _read_index(self) -> list[dict[str, object]]:
        for path in (self.index_path, self.legacy_index_path):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(records, list):
                    return records
            except (FileNotFoundError, OSError, ValueError, TypeError):
                continue
        return []

    def _migrate_legacy_index(self) -> None:
        """Move indexes created by older releases out of the image folder."""
        if self.index_path.is_file() or not self.legacy_index_path.is_file():
            return
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.legacy_index_path.replace(self.index_path)
        except OSError:
            # The old index remains usable as a fallback until it can be moved.
            pass

    def _write_index(self, records: list[dict[str, object]]) -> None:
        temporary_path = self.index_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.index_path)
