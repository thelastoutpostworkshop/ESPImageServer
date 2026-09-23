from __future__ import annotations

import os

from esp_image_server.mjpeg_cache import MjpegConversionCache
from esp_image_server.retention import RetentionPolicy


def test_cache_cleanup_keeps_referenced_conversion_and_never_touches_saved_media(tmp_path) -> None:
    cache = MjpegConversionCache(
        tmp_path / "display-mjpeg",
        RetentionPolicy(max_items=1, max_age_seconds=0, max_bytes=1),
    )
    conversion = cache.output_path("video-123", 480, 272, 8, 10)
    conversion.parent.mkdir(parents=True)
    conversion.write_bytes(b"conversion")
    os.utime(conversion, (1, 1))
    saved_video = tmp_path / "creation-gallery" / "saved.mp4"
    saved_video.parent.mkdir()
    saved_video.write_bytes(b"user video")

    cache.acquire(conversion)
    assert cache.cleanup(now=2) == 0
    assert conversion.is_file()
    assert saved_video.is_file()

    cache.release(conversion)
    assert cache.cleanup(now=2) == 1
    assert not conversion.exists()
    assert saved_video.is_file()


def test_cleanup_enforces_byte_limit_oldest_first(tmp_path):
    cache = MjpegConversionCache(tmp_path, RetentionPolicy(10, 1000, 8))
    old = cache.output_path("old", 1, 1, 1, 1)
    recent = cache.output_path("recent", 1, 1, 1, 1)
    for path, modified in ((old, 1), (recent, 2)):
        path.write_bytes(b"123456")
        os.utime(path, (modified, modified))
    assert cache.cleanup(now=3) == 1
    assert not old.exists()
    assert recent.exists()


def test_cache_does_not_follow_symlinks(tmp_path):
    import pytest
    saved = tmp_path / "saved.mp4"
    saved.write_bytes(b"saved creation")
    cache = MjpegConversionCache(tmp_path / "cache", RetentionPolicy(1, 0, 1))
    cache.path.mkdir()
    link = cache.path / "linked.mjpeg"
    try:
        link.symlink_to(saved)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    assert cache.cleanup(now=10_000_000_000) == 0
    assert saved.read_bytes() == b"saved creation"
