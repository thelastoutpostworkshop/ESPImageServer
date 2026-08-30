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
        {"sd_card": True},
    )
    registry.set_rotation(display.id, 90)
    registry.set_video_rotation(display.id, 270)

    restarted_registry = DisplayRegistry(path)
    restored = restarted_registry.get(display.id)

    assert restored.name == "Kitchen display"
    assert restored.hardware_id == "aa:bb:cc:dd:ee:ff"
    assert restored.rotation == 90
    assert restored.video_rotation == 270
    assert restored.capabilities == {"sd_card": True}
    updated = restarted_registry.heartbeat(display.id, "1.2.4", {"sd_card": True, "touch": False})
    assert updated.firmware_version == "1.2.4"
    assert updated.capabilities == {"sd_card": True, "touch": False}


def test_registering_a_hardware_id_keeps_its_display_id_and_rotation(tmp_path) -> None:
    registry = DisplayRegistry(tmp_path / "displays.sqlite3")
    first_display = registry.register("123456", "Office", 320, 820, "1.0.0")
    registry.set_rotation(first_display.id, 270)
    registry.set_video_rotation(first_display.id, 90)
    second_display = registry.register("123456", "Office screen", 320, 820, "1.1.0")

    assert second_display.id == first_display.id
    assert second_display.name == "Office screen"
    assert second_display.rotation == 270
    assert second_display.video_rotation == 90
    assert second_display.firmware_version == "1.1.0"


def test_display_activity_is_persisted_with_the_display_profile(tmp_path) -> None:
    path = tmp_path / "displays.sqlite3"
    registry = DisplayRegistry(path)
    display = registry.register("abcdef", "Office", 320, 820, "1.0.0")

    updated = registry.record_activity(display.id, "SD-card list received")

    assert updated.last_activity_message == "SD-card list received"
    assert updated.last_activity_at >= updated.paired_at
    restarted = DisplayRegistry(path).get(display.id)
    assert restarted.last_activity_message == "SD-card list received"
