"""Persistent Creation Gallery storage for generated MP4 files."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

try:
    import imageio_ffmpeg
except ImportError:  # A failed installation still lets the user save videos.
    imageio_ffmpeg = None


def bundled_ffmpeg_executable() -> str | None:
    """Return the FFmpeg binary installed with imageio-ffmpeg, if available."""
    if imageio_ffmpeg is None:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class VideoLibrary:
    def __init__(self, image_library_path: Path) -> None:
        self.path = image_library_path / "videos"

    def save(self, source: Path, metadata: dict[str, object]) -> dict[str, object]:
        self.path.mkdir(parents=True, exist_ok=True)
        video_id = uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        filename = f"{created_at[:19].replace(':', '-')}-{video_id[:8]}.mp4"
        destination = self.path / filename
        shutil.copy2(source, destination)
        thumbnail_filename = f"{destination.stem}.jpg"
        thumbnail_path = self.path / thumbnail_filename
        ffmpeg = bundled_ffmpeg_executable()
        try:
            if ffmpeg is None:
                raise OSError("imageio-ffmpeg is unavailable")
            subprocess.run(
                [ffmpeg, "-y", "-ss", "0.1", "-i", str(destination), "-frames:v", "1", "-q:v", "3", str(thumbnail_path)],
                capture_output=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            thumbnail_filename = ""
        record = {
            "id": video_id, "filename": filename, "thumbnail_filename": thumbnail_filename,
            "created_at": created_at, "metadata": metadata,
        }
        (destination.with_suffix(".json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        if not self.path.is_dir():
            return []
        records = []
        for metadata_path in self.path.glob("*.json"):
            try:
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(record, dict) and (self.path / str(record.get("filename", ""))).is_file():
                    records.append(record)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(records, key=lambda record: str(record.get("created_at", "")), reverse=True)[:limit]

    def find_path(self, video_id: str) -> Path | None:
        for record in self.list(limit=10_000):
            if record.get("id") == video_id:
                path = self.path / str(record.get("filename", ""))
                return path if path.is_file() else None
        return None

    def find_thumbnail_path(self, video_id: str) -> Path | None:
        for record in self.list(limit=10_000):
            if record.get("id") == video_id:
                path = self.path / str(record.get("thumbnail_filename", ""))
                return path if path.is_file() else None
        return None
