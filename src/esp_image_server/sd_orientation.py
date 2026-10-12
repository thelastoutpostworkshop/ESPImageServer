"""Orientation labels for SD media; unknown files are never guessed by size."""

from __future__ import annotations

import re


def valid_media_rotation(value: object) -> int | None:
    """Accept only an explicitly recorded quarter-turn angle."""
    return value if type(value) is int and value in (0, 90, 180, 270) else None


def sd_media_rotation(filename: str) -> int | None:
    """Read the orientation token preceding the unchanged content-key prefix."""
    if len(filename) > 160:
        return None
    match = re.fullmatch(
        r"esp-(?:image-\d{8}-\d{6}-r(0|90|180|270)-v1-[0-9a-f]{16}\.jpg"
        r"|video-\d{8}-\d{6}-r(0|90|180|270)-v1-[A-Za-z0-9]+-\d+x\d+-fps\d+\.mjpeg)",
        filename,
        flags=re.ASCII,
    )
    return int(match.group(1) or match.group(2)) if match else None


def video_media_rotation(metadata: object) -> int | None:
    """Videos already contain their generation rotation; do not rotate again."""
    if not isinstance(metadata, dict):
        return None
    return valid_media_rotation(metadata.get("rotation"))
