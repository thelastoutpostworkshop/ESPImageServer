from __future__ import annotations

from esp_image_server.display_commands import DisplayCommandStore


def test_commands_reports_and_acknowledgements_are_isolated_per_display() -> None:
    store = DisplayCommandStore()
    kitchen_command = store.queue("set_mode", display_id="kitchen", mode="live_images")
    office_command = store.queue("set_mode", display_id="office", mode="sd_card")

    assert store.next("kitchen") == kitchen_command
    assert store.next("office") == office_command
    assert store.acknowledge(str(kitchen_command["id"]), True, "done", display_id="office") is None
    assert store.acknowledge(str(kitchen_command["id"]), True, "done", display_id="kitchen")
    assert store.next("kitchen") is None
    assert store.next("office") == office_command

    store.report_sd_card({"available": True, "files": [{"name": "kitchen.jpg"}]}, display_id="kitchen")
    store.report_sd_card({"available": True, "files": [{"name": "office.jpg"}]}, display_id="office")

    assert store.sd_card_report("kitchen")["files"] == [{"name": "kitchen.jpg"}]
    assert store.sd_card_report("office")["files"] == [{"name": "office.jpg"}]


def test_pending_video_references_are_retained_for_every_display() -> None:
    store = DisplayCommandStore()
    store.queue("save_saved_video", display_id="kitchen", video_id="kitchen-video")
    store.queue("save_saved_video", display_id="office", video_id="office-video")

    assert store.referenced_video_ids() == {"kitchen-video", "office-video"}
