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
