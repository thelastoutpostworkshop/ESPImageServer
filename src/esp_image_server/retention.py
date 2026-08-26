"""Shared, bounded-retention settings for temporary server data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    """Limits for disposable completed work, command history, or cache files."""

    max_items: int
    max_age_seconds: float
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_items < 1:
            raise ValueError("max_items must be at least 1")
        if self.max_age_seconds < 0:
            raise ValueError("max_age_seconds cannot be negative")
        if self.max_bytes is not None and self.max_bytes < 1:
            raise ValueError("max_bytes must be at least 1 when set")


# These are intentionally generous enough for a person to inspect recent work,
# while preventing a long-running server from retaining temporary results forever.
COMPLETED_JOB_RETENTION = RetentionPolicy(
    max_items=50,
    max_age_seconds=12 * 60 * 60,
    max_bytes=512 * 1024 * 1024,
)
DISPLAY_COMMAND_RETENTION = RetentionPolicy(
    max_items=200,
    max_age_seconds=24 * 60 * 60,
    max_bytes=2 * 1024 * 1024,
)
MJPEG_CACHE_RETENTION = RetentionPolicy(
    max_items=64,
    max_age_seconds=7 * 24 * 60 * 60,
    max_bytes=1024 * 1024 * 1024,
)
