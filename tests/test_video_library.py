from pathlib import Path

from esp_image_server.video_library import VideoLibrary


def test_video_library_saves_video_and_metadata_when_thumbnail_extraction_fails(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not a real video")
    library = VideoLibrary(tmp_path / "gallery")
    monkeypatch.setattr("esp_image_server.video_library.subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    record = library.save(source, {"prompt": "test video"})

    assert record["thumbnail_filename"] == ""
    assert library.find_path(record["id"]) is not None
    assert library.list() == [record]


def test_video_library_finds_thumbnail(tmp_path) -> None:
    library = VideoLibrary(tmp_path / "gallery")
    library.path.mkdir(parents=True)
    video = library.path / "saved.mp4"
    thumbnail = library.path / "saved.jpg"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"thumbnail")
    (video.with_suffix(".json")).write_text(
        '{"id":"video-id","filename":"saved.mp4","thumbnail_filename":"saved.jpg","created_at":"2026-01-01T00:00:00Z","metadata":{}}',
        encoding="utf-8",
    )

    assert library.find_thumbnail_path("video-id") == thumbnail
