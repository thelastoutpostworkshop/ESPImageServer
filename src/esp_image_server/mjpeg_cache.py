"""Bounded cache for display-sized MJPEG conversions."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from time import time
from typing import Iterable

from .retention import MJPEG_CACHE_RETENTION, RetentionPolicy


class MjpegConversionCache:
    """Tracks temporary conversion files and protects files being served."""

    def __init__(self, path: Path, retention: RetentionPolicy = MJPEG_CACHE_RETENTION) -> None:
        self.path = path
        self.retention = retention
        self._lock = Lock()
        self._references: dict[Path, int] = {}

    def output_path(self, video_id: str, width: int, height: int, fps: int, quality: int) -> Path:
        return self.path / f"{video_id}-{width}x{height}-{fps}fps-q{quality}.mjpeg"

    def acquire(self, path: Path) -> None:
        """Prevent a conversion from being removed while an HTTP response uses it."""
        resolved = self._resolve(path)
        with self._lock:
            self._references[resolved] = self._references.get(resolved, 0) + 1

    def release(self, path: Path) -> None:
        resolved = self._resolve(path)
        with self._lock:
            count = self._references.get(resolved, 0)
            if count <= 1:
                self._references.pop(resolved, None)
            else:
                self._references[resolved] = count - 1

    def paths_for_video_ids(self, video_ids: Iterable[str]) -> set[Path]:
        """Return cache files still needed by currently pending display commands."""
        prefixes = tuple(f"{video_id}-" for video_id in video_ids if video_id)
        if not prefixes or not self.path.is_dir():
            return set()
        return {
            self._resolve(candidate)
            for candidate in self.path.glob("*.mjpeg")
            if candidate.name.startswith(prefixes)
        }

    def cleanup(self, referenced_paths: Iterable[Path] = (), now: float | None = None) -> int:
        """Discard only unreferenced, stale or over-limit cache entries."""
        now = time() if now is None else now
        self.path.mkdir(parents=True, exist_ok=True)
        protected = {self._resolve(path) for path in referenced_paths}
        with self._lock:
            protected.update(path for path, count in self._references.items() if count > 0)

        entries = self._entries()
        deletable = [entry for entry in entries if entry[0] not in protected]
        remove: list[Path] = [
            path for path, modified_at, _size in deletable
            if modified_at + self.retention.max_age_seconds < now
        ]

        remaining = [entry for entry in entries if entry[0] not in set(remove)]
        total_bytes = sum(size for _path, _modified_at, size in remaining)
        while len(remaining) > self.retention.max_items or (
            self.retention.max_bytes is not None and total_bytes > self.retention.max_bytes
        ):
            candidate = next((entry for entry in remaining if entry[0] not in protected), None)
            if candidate is None:
                break
            path, _modified_at, size = candidate
            remove.append(path)
            remaining.remove(candidate)
            total_bytes -= size

        removed = 0
        for path in dict.fromkeys(remove):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            removed += 1
        return removed

    def _entries(self) -> list[tuple[Path, float, int]]:
        if not self.path.is_dir():
            return []
        entries: list[tuple[Path, float, int]] = []
        for candidate in self.path.glob("*.mjpeg"):
            try:
                stat = candidate.stat()
            except OSError:
                continue
            entries.append((self._resolve(candidate), stat.st_mtime, stat.st_size))
        return sorted(entries, key=lambda entry: entry[1])

    def _resolve(self, path: Path) -> Path:
        return path.resolve(strict=False)
