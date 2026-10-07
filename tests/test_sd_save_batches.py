from __future__ import annotations

from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from esp_image_server.app import create_app
from esp_image_server.config import Settings
from esp_image_server.display_commands import DisplayCommandBusyError, DisplayCommandStore
from esp_image_server.sd_save_batches import SDSaveBatchStore


def eventually(read, predicate=lambda value: bool(value)):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        sleep(0.005)
    raise AssertionError(f"Condition did not become true: {read()}")


@pytest.fixture
def coordinator():
    commands = DisplayCommandStore()
    online = [True]
    dispatched = []

    def queue_item(display_id, item, batch_id, index, total):
        dispatched.append((display_id, item["id"]))
        if item["id"] == "exists":
            return {"status": "already_saved", "detail": "already saved"}
        return commands.queue(
            "save_saved_image" if item["type"] == "image" else "save_saved_video",
            display_id=display_id, owner_id=batch_id, image_id=item["id"],
            bulk_save_id=batch_id, bulk_save_index=index, bulk_save_total=total,
        )

    batches = SDSaveBatchStore(commands, queue_item, lambda _: online[0], poll_interval=0.005)
    yield commands, batches, dispatched, online
    batches.close()


def refresh(commands, display_id="desk", *, available=True):
    command = commands.next(display_id)
    assert command["type"] == "refresh_sd_card"
    commands.acknowledge(command["id"], True, "refreshed", display_id=display_id)
    commands.report_sd_card({"available": available, "files": []}, display_id=display_id)


def terminal(batches, batch_id, display_id="desk"):
    return eventually(lambda: batches.get(display_id, batch_id), lambda value: value["status"] in {"complete", "cancelled", "failed"})


def test_sequential_deduplicated_mixed_batch_waits_for_inventory_and_each_ack(coordinator):
    commands, batches, dispatched, _ = coordinator
    batch = batches.start("desk", "Desk", [
        {"id": "one", "type": "image"}, {"id": "one", "type": "image"},
        {"id": "exists", "type": "image"}, {"id": "movie", "type": "video"},
    ])
    assert batch["total"] == 3
    assert batch["current_index"] == 0
    assert batches.references("video") == {"movie"}
    initial = commands.next("desk")
    commands.acknowledge(initial["id"], True, "refresh", display_id="desk")
    sleep(0.02)
    assert dispatched == []
    commands.report_sd_card({"available": True, "files": []}, display_id="desk")
    first = eventually(lambda: commands.next("desk"))
    assert first["bulk_save_index"] == 1
    assert first["bulk_save_total"] == 3
    sleep(0.02)
    assert dispatched == [("desk", "one")]
    commands.acknowledge(first["id"], True, "saved", display_id="desk")
    third = eventually(lambda: commands.next("desk"))
    assert third["bulk_save_index"] == 3
    commands.acknowledge(third["id"], True, "saved", display_id="desk")
    finished = terminal(batches, batch["id"])
    assert (finished["completed"], finished["saved"], finished["skipped"]) == (3, 2, 1)
    assert [item["status"] for item in finished["items"]] == ["saved", "already_saved", "saved"]
    assert batches.active("desk") is None
    assert batches.references("video") == set()
    commands.queue("set_mode", display_id="desk")


def test_channel_reservation_is_per_display_and_does_not_replace_existing_operations(coordinator):
    commands, batches, _, _ = coordinator
    commands.queue("set_mode", display_id="busy")
    with pytest.raises(DisplayCommandBusyError):
        batches.start("busy", "Busy", [{"id": "one", "type": "image"}])
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    with pytest.raises(DisplayCommandBusyError):
        commands.queue("delete_sd_file", display_id="desk")
    with pytest.raises(DisplayCommandBusyError):
        commands.cancel(batch["current_command"]["id"], display_id="desk")
    commands.queue("set_mode", display_id="other")
    with pytest.raises(DisplayCommandBusyError):
        batches.start("desk", "Desk", [{"id": "two", "type": "image"}])


def test_cancel_refresh_never_dispatches_an_item(coordinator):
    commands, batches, dispatched, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    cancelled = batches.cancel("desk", batch["id"])
    assert cancelled["status"] == "cancelling"
    cancel = commands.next("desk")
    assert cancel["type"] == "cancel_operation"
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="desk")
    assert terminal(batches, batch["id"])["status"] == "cancelled"
    assert dispatched == []


def test_cancel_completed_save_race_counts_save_but_waits_for_cancel_ack(coordinator):
    commands, batches, dispatched, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}, {"id": "two", "type": "video"}])
    refresh(commands)
    saving = eventually(lambda: commands.next("desk"))
    batches.cancel("desk", batch["id"])
    cancel = commands.next("desk")
    commands.acknowledge(saving["id"], True, "file already committed", display_id="desk")
    sleep(0.02)
    assert batches.get("desk", batch["id"])["status"] == "cancelling"
    assert dispatched == [("desk", "one")]
    with pytest.raises(DisplayCommandBusyError):
        commands.queue("set_mode", display_id="desk")
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="desk")
    finished = terminal(batches, batch["id"])
    assert finished["status"] == "cancelled"
    assert finished["saved"] == finished["completed"] == 1
    assert [item["status"] for item in finished["items"]] == ["saved", "cancelled"]
    commands.queue("set_mode", display_id="desk")


@pytest.mark.parametrize("reason", ["disconnect", "timeout"])
def test_lost_board_or_timeout_stops_dispatch_and_holds_channel_until_cleanup(coordinator, reason):
    commands, batches, dispatched, online = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}, {"id": "two", "type": "image"}])
    refresh(commands)
    eventually(lambda: commands.next("desk"))
    if reason == "disconnect":
        online[0] = False
    else:
        batches._command_timeout = 0.02
        # The current command already has a deadline, so start the timeout at
        # its next wait by completing the first and timing out the second.
        first = commands.next("desk")
        commands.acknowledge(first["id"], True, "saved", display_id="desk")
        eventually(lambda: commands.next("desk"), lambda value: value and value.get("bulk_save_index") == 2)
    eventually(lambda: batches.get("desk", batch["id"]), lambda value: value["status"] == "cancelling")
    before = list(dispatched)
    sleep(0.03)
    assert dispatched == before
    with pytest.raises(DisplayCommandBusyError):
        commands.queue("set_mode", display_id="desk")
    cancel = commands.next("desk")
    assert cancel["type"] == "cancel_operation"
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="desk")
    finished = terminal(batches, batch["id"])
    assert finished["status"] == "failed"
    assert ("disconnected" if reason == "disconnect" else "in time") in finished["detail"]


def test_failed_save_stops_remaining_items_and_retains_retry_information(coordinator):
    commands, batches, dispatched, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}, {"id": "two", "type": "video"}])
    refresh(commands)
    saving = eventually(lambda: commands.next("desk"))
    commands.acknowledge(saving["id"], False, "SD card is full", display_id="desk")
    finished = terminal(batches, batch["id"])
    assert finished["status"] == "failed"
    assert [item["status"] for item in finished["items"]] == ["failed", "queued"]
    assert dispatched == [("desk", "one")]


def test_unavailable_refreshed_card_fails_before_saving(coordinator):
    commands, batches, dispatched, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    refresh(commands, available=False)
    assert terminal(batches, batch["id"])["status"] == "failed"
    assert dispatched == []


def test_bulk_api_scopes_to_target_blocks_interference_and_pins_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    app = create_app(Settings(), SimpleNamespace(device="cpu", ready=False), enable_mdns=False)
    jpeg = BytesIO()
    Image.new("RGB", (64, 64), "red").save(jpeg, "JPEG")
    saved = app.state.image_library.save(jpeg.getvalue(), {"prompt": "red"})
    with TestClient(app) as client:
        display = client.post("/displays/register", json={
            "hardware_id": "abc", "name": "Desk", "width": 240, "height": 320,
            "firmware_version": "1.1.39", "board_target": "CHEAP_YELLOW_DISPLAY",
        }).json()
        path = f"/displays/{display['id']}"
        response = client.post(path + "/sd-card-save-batches", json={"items": [{"id": saved["id"], "type": "image"}]})
        assert response.status_code == 202
        batch = response.json()
        assert client.get(path + "/sd-card-save-batches/active").json()["id"] == batch["id"]
        assert client.post(path + "/display-sd-card/refresh").status_code == 409
        assert client.delete(f"/saved-images/{saved['id']}").status_code == 409
        assert client.put("/app-settings", json={"image_library_location": str(tmp_path / "moved")}).status_code == 409
        assert client.get("/sd-card-save-batches/" + batch["id"]).status_code == 404
        assert client.post(path + f"/sd-card-save-batches/{batch['id']}/cancel").json()["status"] == "cancelling"
        cancel = client.get(path + "/display-commands/next").json()
        assert client.post(path + f"/display-commands/{cancel['id']}/ack", json={"success": True}).status_code == 200
        finished = eventually(lambda: client.get(path + f"/sd-card-save-batches/{batch['id']}").json(), lambda value: value["status"] == "cancelled")
        assert finished["completed"] == 0
        assert client.delete(f"/saved-images/{saved['id']}").status_code == 204


def test_bulk_api_saves_mixed_sources_and_skips_verified_duplicate_from_fresh_report(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("esp_image_server.app.bundled_ffmpeg_executable", lambda: "bundled-ffmpeg")
    monkeypatch.setattr("esp_image_server.video_library.bundled_ffmpeg_executable", lambda: None)
    app = create_app(Settings(), SimpleNamespace(device="cpu", ready=False), enable_mdns=False)
    jpeg = BytesIO()
    Image.new("RGB", (64, 64), "red").save(jpeg, "JPEG")
    image = app.state.image_library.save(jpeg.getvalue(), {"prompt": "red"})
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"fake mp4, conversion not run")
    video = app.state.video_library.save(source, {"fps": 12})
    with TestClient(app) as client:
        display = client.post("/displays/register", json={
            "hardware_id": "mixed", "name": "Mixed Desk", "width": 240, "height": 320,
            "firmware_version": "1.1.39", "board_target": "CHEAP_YELLOW_DISPLAY",
        }).json()
        prefix = f"/displays/{display['id']}"
        assert client.post(prefix + "/sd-card-save-batches", json={"items": [{"id": "missing", "type": "image"}]}).status_code == 404
        request = {"items": [{"id": image["id"], "type": "image"}, {"id": video["id"], "type": "video"}, {"id": image["id"], "type": "image"}]}
        response = client.post(prefix + "/sd-card-save-batches", json=request)
        assert response.status_code == 202
        batch = response.json()
        batch_path = prefix + "/sd-card-save-batches/" + batch["id"]
        assert batch["total"] == 2
        refresh_command = client.get(prefix + "/display-commands/next").json()
        client.post(prefix + f"/display-commands/{refresh_command['id']}/ack", json={"success": True})
        # A previously cached report is insufficient; the next confirmed report
        # is what tells the coordinator which content is already present.
        report = {"available": True, "mode": "server_controlled", "total_bytes": 100000,
                  "used_bytes": 0, "files": [], "verified_saves": True}
        assert client.post(prefix + "/display-sd-card/report", json=report).status_code == 204
        saving = eventually(lambda: client.get(prefix + "/display-commands/next"), lambda value: value.status_code == 200).json()
        assert saving["type"] == "save_saved_image"
        assert saving["bulk_save_id"] == batch["id"]
        assert saving["bulk_save_index"] == 1
        assert saving["bulk_save_total"] == 2
        assert client.delete(f"/saved-videos/{video['id']}").status_code == 409
        rendered = client.get(prefix + f"/saved-images/{image['id']}/image")
        assert rendered.status_code == 200
        assert Image.open(BytesIO(rendered.content)).size == (240, 320)
        client.post(prefix + f"/display-commands/{saving['id']}/ack", json={"success": True, "detail": "image committed"})
        movie = eventually(lambda: client.get(prefix + "/display-commands/next"), lambda value: value.status_code == 200 and value.json().get("type") == "save_saved_video").json()
        assert movie["content_key"] == f"v1-{video['id']}-240x320-fps12"
        assert movie["fps"] == 12 and movie["bulk_save_index"] == 2
        client.post(prefix + f"/display-commands/{movie['id']}/ack", json={"success": True, "detail": "video committed"})
        finished = eventually(lambda: client.get(batch_path).json(), lambda value: value["status"] == "complete")
        assert (finished["completed"], finished["saved"], finished["skipped"]) == (2, 2, 0)
        assert client.get(prefix + "/sd-card-save-batches/active").json() is None

        # A second batch refreshes again and skips verified content without
        # issuing either a save command or a conversion request.
        second = client.post(prefix + "/sd-card-save-batches", json=request).json()
        refresh_command = client.get(prefix + "/display-commands/next").json()
        client.post(prefix + f"/display-commands/{refresh_command['id']}/ack", json={"success": True})
        report["files"] = [{"name": item["filename"], "type": kind, "content_key": item["content_key"], "verified": True}
                           for item, kind in ((saving, "image"), (movie, "video"))]
        client.post(prefix + "/display-sd-card/report", json=report)
        skipped = eventually(lambda: client.get(prefix + "/sd-card-save-batches/" + second["id"]).json(), lambda value: value["status"] == "complete")
        assert (skipped["completed"], skipped["saved"], skipped["skipped"]) == (2, 0, 2)
        assert client.get(prefix + "/display-commands/next").status_code == 204
