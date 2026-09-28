from __future__ import annotations

from esp_image_server.display_registry import DisplayRegistry


def test_display_registry_persists_mac_profiles_and_per_display_rotation(tmp_path) -> None:
    path = tmp_path / "displays.sqlite3"
    registry = DisplayRegistry(path)
    display = registry.register(
        "aa:bb:cc:dd:ee:ff",
        "Kitchen display",
        480,
        272,
        "1.2.3",
        {"sd_card": True}, board_target="JC4827W543",
    )
    registry.set_rotation(display.id, 90)
    registry.set_video_rotation(display.id, 270)

    restarted_registry = DisplayRegistry(path)
    restored = restarted_registry.get(display.id)

    assert restored.name == "Kitchen display"
    assert restored.board_target == "JC4827W543"
    assert restored.as_dict()["board_target"] == "JC4827W543"
    assert restored.hardware_id == "aa:bb:cc:dd:ee:ff"
    assert restored.rotation == 90
    assert restored.video_rotation == 270
    assert restored.capabilities == {"sd_card": True}
    assert restored.as_dict()["seen_this_session"] is False
    assert restored.as_dict()["online"] is False
    assert restarted_registry.set_name(display.id, "Kitchen display").as_dict()["seen_this_session"] is False
    assert restarted_registry.set_rotation(display.id, 90).as_dict()["online"] is False
    updated = restarted_registry.heartbeat(display.id, "1.2.4", {"sd_card": True, "touch": False})
    assert updated.firmware_version == "1.2.4"
    assert updated.capabilities == {"sd_card": True, "touch": False}
    assert updated.as_dict()["seen_this_session"] is True
    assert updated.as_dict()["online"] is True
    assert updated.as_dict(now=updated.last_seen + 91)["online"] is False
    assert updated.as_dict(now=updated.last_seen + 91)["seen_this_session"] is True


def test_registering_a_hardware_id_keeps_its_display_id_and_rotation(tmp_path) -> None:
    registry = DisplayRegistry(tmp_path / "displays.sqlite3")
    first_display = registry.register("123456", "Office", 320, 820, "1.0.0", board_target="JC4827W543")
    registry.set_rotation(first_display.id, 270)
    registry.set_video_rotation(first_display.id, 90)
    second_display = registry.register("123456", "Office screen", 320, 820, "1.1.0", board_target="ST7701_320X820")

    assert second_display.id == first_display.id
    assert second_display.board_target == "ST7701_320X820"
    assert second_display.name == "Office screen"
    assert second_display.rotation == 270
    assert second_display.video_rotation == 90
    assert second_display.firmware_version == "1.1.0"


def test_display_activity_is_persisted_with_the_display_profile(tmp_path) -> None:
    path = tmp_path / "displays.sqlite3"
    registry = DisplayRegistry(path)
    display = registry.register("abcdef", "Office", 320, 820, "1.0.0", board_target="JC4827W543")

    updated = registry.record_activity(display.id, "SD-card list received")

    assert updated.last_activity_message == "SD-card list received"
    assert updated.last_activity_at >= updated.paired_at
    restarted = DisplayRegistry(path).get(display.id)
    assert restarted.last_activity_message == "SD-card list received"
    assert restarted.as_dict()["seen_this_session"] is False


def test_firmware_contact_marks_a_restored_display_seen(tmp_path) -> None:
    path = tmp_path / "displays.sqlite3"
    DisplayRegistry(path).register("abcdef", "Office", 320, 820, "1.0.0", board_target="JC4827W543")
    registry = DisplayRegistry(path)
    assert registry.record_activity("abcdef", "SD-card list received").as_dict()["online"] is True
    registry = DisplayRegistry(path)
    assert registry.register("abcdef", "Office", 320, 820, "1.0.0", board_target="JC4827W543").as_dict()["seen_this_session"] is True
