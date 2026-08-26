from __future__ import annotations

from esp_image_server.display_commands import DisplayCommandStore
from esp_image_server.retention import RetentionPolicy


def test_completed_command_history_is_bounded_while_pending_command_is_kept() -> None:
    store = DisplayCommandStore(RetentionPolicy(max_items=1, max_age_seconds=60, max_bytes=1024))
    first = store.queue("set_mode", mode="live_images")
    store.acknowledge(str(first["id"]), True, "done")
    second = store.queue("set_mode", mode="sd_card")
    store.acknowledge(str(second["id"]), True, "done")

    assert store.get(str(first["id"])) is None
    assert store.get(str(second["id"])) is not None

    pending = store.queue("save_saved_video", video_id="video-123")
    assert store.prune_completed(now=10_000_000_000) == 1
    assert store.get(str(pending["id"])) is not None
    assert store.referenced_video_ids() == {"video-123"}
