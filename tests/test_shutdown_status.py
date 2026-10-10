from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from esp_image_server.app import create_app
from esp_image_server.config import Settings
from esp_image_server.display_commands import DisplayCommandStore, LEGACY_DISPLAY_ID
from esp_image_server.retention import RetentionPolicy
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

    def queue_item(display_id, item, batch_id, index, total):
        return commands.queue(
            "save_saved_image" if item["type"] == "image" else "save_saved_video",
            display_id=display_id, owner_id=batch_id, bulk_save_id=batch_id,
            bulk_save_index=index, bulk_save_total=total,
        )

    batches = SDSaveBatchStore(commands, queue_item, lambda _: online[0], poll_interval=0.005)
    yield commands, batches, online
    batches.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    commands = DisplayCommandStore()
    app = create_app(
        Settings(), SimpleNamespace(device="cpu", ready=False),
        display_command_store=commands, enable_mdns=False,
    )
    with TestClient(app) as client:
        yield client, commands, app.state.sd_save_batches


def test_save_snapshot_includes_all_boards_and_legacy_without_payloads():
    commands = DisplayCommandStore()
    expected = [
        commands.queue_save("latest.jpg"),
        commands.queue_save("saved.jpg", image_id="image", display_id="inactive"),
        commands.queue("save_saved_video", display_id="offline", filename="movie.mjpeg", raw_data=b"private"),
    ]
    commands.queue("delete_sd_file", display_id="other", filename="old.jpg")
    commands.queue("set_mode", display_id="another", mode="live_images")

    saves = commands.active_sd_card_saves()
    assert {save["id"] for save in saves} == {command["id"] for command in expected}
    assert {save["display_id"] for save in saves} == {LEGACY_DISPLAY_ID, "inactive", "offline"}
    assert all("raw_data" not in save and "image_id" not in save for save in saves)
    saves[0]["status"] = "complete"
    assert commands.active_sd_card_saves()[0]["status"] == "pending"


@pytest.mark.parametrize("success", [True, False])
def test_acknowledged_save_is_no_longer_active(success):
    commands = DisplayCommandStore()
    save = commands.queue_save("image.jpg", display_id="desk")
    commands.acknowledge(save["id"], success, "finished", display_id="desk")
    assert commands.active_sd_card_saves() == []


@pytest.mark.parametrize("original_success", [None, True, False])
@pytest.mark.parametrize("cancel_success", [True, False])
def test_cancel_waits_for_its_own_ack_even_if_original_finishes_and_history_prunes(original_success, cancel_success):
    commands = DisplayCommandStore(RetentionPolicy(max_items=1, max_age_seconds=0, max_bytes=1024))
    save = commands.queue("save_saved_video", display_id="desk", filename="movie.mjpeg")
    commands.cancel(save["id"], display_id="desk")
    cancel = commands.next("desk")
    assert cancel["type"] == "cancel_operation"
    if original_success is not None:
        commands.acknowledge(save["id"], original_success, "original finished", display_id="desk")
    commands.prune_completed(now=10_000_000_000)

    assert commands.active_sd_card_saves() == [{
        "id": cancel["id"], "display_id": "desk", "type": "cancel_operation",
        "status": "pending", "cancelled_command_id": save["id"],
    }]
    commands.acknowledge(cancel["id"], cancel_success, "cancel finished", display_id="desk")
    assert commands.active_sd_card_saves() == []


def test_cancel_for_an_unrelated_refresh_does_not_claim_a_single_save():
    commands = DisplayCommandStore()
    refresh = commands.queue("refresh_sd_card", display_id="desk")
    commands.cancel(refresh["id"], display_id="desk")
    assert commands.active_sd_card_saves() == []


@pytest.mark.parametrize("cancel_first", [True, False])
@pytest.mark.parametrize("replacement_success", [True, False])
def test_superseded_save_remains_protected_until_replacement_ack(cancel_first, replacement_success):
    commands = DisplayCommandStore(RetentionPolicy(max_items=1, max_age_seconds=0, max_bytes=1024))
    save = commands.queue_save("image.jpg", display_id="desk")
    if cancel_first:
        commands.cancel(save["id"], display_id="desk")
        # Even if a completed save ACK won this race, the board still owes an
        # acknowledgement for the pending cancellation/replacement.
        commands.acknowledge(save["id"], True, "already committed", display_id="desk")
    replacement = commands.queue("set_mode", display_id="desk", mode="live_images")
    commands.prune_completed(now=10_000_000_000)

    saves = commands.active_sd_card_saves()
    assert len(saves) == 1
    assert saves[0]["id"] == save["id"] and saves[0]["status"] == "cancelling"
    assert saves[0]["replacement_command_id"] == replacement["id"]
    commands.acknowledge(replacement["id"], replacement_success, "processed", display_id="desk")
    assert commands.active_sd_card_saves() == []


def test_chained_replacements_and_late_ack_cannot_clear_current_save_protection():
    commands = DisplayCommandStore()
    first_save = commands.queue_save("first.jpg", display_id="desk")
    second_save = commands.queue("save_saved_video", display_id="desk", filename="second.mjpeg")
    assert len(commands.active_sd_card_saves()) == 1
    commands.cancel(second_save["id"], display_id="desk")
    cancellation = commands.next("desk")
    commands.acknowledge(second_save["id"], True, "committed", display_id="desk")
    first_replacement = commands.queue("set_mode", display_id="desk", mode="live_images")
    current_replacement = commands.queue("refresh_sd_card", display_id="desk")

    for late in (first_save, cancellation, first_replacement):
        commands.acknowledge(late["id"], True, "late", display_id="desk")
        saves = commands.active_sd_card_saves()
        assert len(saves) == 1
        assert saves[0]["replacement_command_id"] == current_replacement["id"]
    commands.acknowledge(current_replacement["id"], True, "processed", display_id="desk")
    assert commands.active_sd_card_saves() == []


@pytest.mark.parametrize("success", [True, False])
def test_bulk_save_protects_refresh_and_inventory_gap_then_releases_on_terminal_ack(coordinator, success):
    commands, batches, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    expected = {
        "id": batch["id"], "display_id": "desk", "type": "sd_card_save_batch",
        "status": "running", "display_name": "Desk", "total": 1,
        "completed": 0, "current_index": 0,
    }
    assert batches.active_saves() == [expected]
    refresh = commands.next("desk")
    commands.acknowledge(refresh["id"], True, "refreshed", display_id="desk")
    assert commands.next("desk") is None
    assert commands.active_sd_card_saves() == []
    assert batches.active_saves() == [expected]

    commands.report_sd_card({"available": True, "files": []}, display_id="desk")
    saving = eventually(lambda: commands.next("desk"))
    assert saving["type"] == "save_saved_image"
    snapshot = batches.active_saves()
    assert len(snapshot) == 1 and snapshot[0]["id"] == batch["id"]
    snapshot[0]["status"] = "complete"
    assert batches.active_saves()[0]["status"] == "running"
    commands.acknowledge(saving["id"], success, "saved" if success else "card full", display_id="desk")
    eventually(lambda: batches.active_saves(), lambda value: value == [])
    assert batches.get("desk", batch["id"])["status"] == ("complete" if success else "failed")


def test_bulk_cancel_stays_active_after_original_commit_until_cancel_ack(coordinator):
    commands, batches, _ = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    refresh = commands.next("desk")
    commands.acknowledge(refresh["id"], True, "refreshed", display_id="desk")
    commands.report_sd_card({"available": True, "files": []}, display_id="desk")
    saving = eventually(lambda: commands.next("desk"))
    batches.cancel("desk", batch["id"])
    cancel = commands.next("desk")
    commands.acknowledge(saving["id"], True, "already committed", display_id="desk")

    saves = batches.active_saves()
    assert len(saves) == 1
    assert saves[0]["id"] == batch["id"] and saves[0]["status"] == "cancelling"
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="desk")
    eventually(lambda: batches.active_saves(), lambda value: value == [])
    assert batches.get("desk", batch["id"])["saved"] == 1


def test_offline_batch_cancellation_and_other_boards_are_all_reported(coordinator):
    commands, batches, online = coordinator
    batch = batches.start("desk", "Desk", [{"id": "one", "type": "image"}])
    legacy = commands.queue_save("legacy.jpg")
    other = commands.queue("save_saved_video", display_id="other", filename="movie.mjpeg")
    online[0] = False
    eventually(lambda: batches.get("desk", batch["id"]), lambda value: value["status"] == "cancelling")

    saves = batches.active_saves()
    assert {save["id"] for save in saves} == {batch["id"], legacy["id"], other["id"]}
    assert next(save for save in saves if save["id"] == batch["id"])["status"] == "cancelling"
    cancel = commands.next("desk")
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="desk")
    eventually(lambda: batches.active("desk"), lambda value: value is None)
    assert {save["id"] for save in batches.active_saves()} == {legacy["id"], other["id"]}


def test_shutdown_status_endpoint_is_uncached_and_independent_of_active_display(client):
    http, commands, _ = client
    response = http.get("/shutdown-status")
    assert response.status_code == 200
    assert response.json() == {"sd_card_saves": []}
    assert response.headers["cache-control"] == "no-store"
    legacy = commands.queue_save("legacy.jpg")
    image = commands.queue_save("image.jpg", image_id="image", display_id="unregistered-board")
    video = commands.queue("save_saved_video", display_id="offline-board", filename="video.mjpeg")
    commands.queue("refresh_sd_card", display_id="other")

    saves = http.get("/shutdown-status").json()["sd_card_saves"]
    assert {save["id"] for save in saves} == {legacy["id"], image["id"], video["id"]}
    commands.cancel(video["id"], display_id="offline-board")
    cancel = commands.next("offline-board")
    commands.acknowledge(video["id"], True, "already committed", display_id="offline-board")
    saves = http.get("/shutdown-status").json()["sd_card_saves"]
    assert {save["id"] for save in saves} == {legacy["id"], image["id"], cancel["id"]}
    commands.acknowledge(cancel["id"], True, "cancelled", display_id="offline-board")
    commands.acknowledge(image["id"], False, "failed", display_id="unregistered-board")
    assert http.post(f"/display-commands/{legacy['id']}/ack", json={"success": True}).status_code == 200
    assert http.get("/shutdown-status").json() == {"sd_card_saves": []}


def test_shutdown_status_endpoint_reports_initial_bulk_refresh_and_cancel(client):
    http, commands, batches = client
    board = http.post("/displays/register", json={
        "hardware_id": "bulk-board", "name": "Desk", "width": 240, "height": 320,
        "board_target": "CHEAP_YELLOW_DISPLAY", "firmware_version": "1.1.39",
    }).json()
    batch = batches.start(board["id"], "Desk", [{"id": "one", "type": "image"}])
    saves = http.get("/shutdown-status").json()["sd_card_saves"]
    assert len(saves) == 1 and saves[0]["id"] == batch["id"]
    batches.cancel(board["id"], batch["id"])
    assert http.get("/shutdown-status").json()["sd_card_saves"][0]["status"] == "cancelling"
    cancel = commands.next(board["id"])
    assert http.post(f"/displays/{board['id']}/display-commands/{cancel['id']}/ack", json={"success": True}).status_code == 200
    eventually(lambda: http.get("/shutdown-status").json()["sd_card_saves"], lambda value: value == [])
