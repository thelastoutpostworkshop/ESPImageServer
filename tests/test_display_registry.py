from __future__ import annotations

import pytest

from esp_image_server.display_registry import DisplayAuthenticationError, DisplayRegistry


def test_display_registry_persists_profiles_credentials_and_per_display_rotation(tmp_path) -> None:
    path = tmp_path / "displays.sqlite3"
    registry = DisplayRegistry(path)
    pairing_code, _ = registry.create_pairing_code()
    display, token = registry.register(
        pairing_code,
        "aa:bb:cc:dd:ee:ff",
        "Kitchen display",
        480,
        272,
        "1.2.3",
        {"sd_card": True},
    )
    registry.set_rotation(display.id, 90)

    restarted_registry = DisplayRegistry(path)
    restored = restarted_registry.get(display.id)

    assert restored.name == "Kitchen display"
    assert restored.hardware_id == "aa:bb:cc:dd:ee:ff"
    assert restored.rotation == 90
    assert restored.capabilities == {"sd_card": True}
    updated = restarted_registry.heartbeat(
        display.id, token, "1.2.4", {"sd_card": True, "touch": False},
    )
    assert updated.firmware_version == "1.2.4"
    assert updated.capabilities == {"sd_card": True, "touch": False}
    with pytest.raises(DisplayAuthenticationError):
        restarted_registry.authenticate(display.id, "wrong-token")


def test_repairing_a_hardware_id_keeps_its_display_id_and_rotates_the_token(tmp_path) -> None:
    registry = DisplayRegistry(tmp_path / "displays.sqlite3")
    first_code, _ = registry.create_pairing_code()
    first_display, first_token = registry.register(
        first_code, "123456", "Office", 320, 820, "1.0.0",
    )
    registry.set_rotation(first_display.id, 270)
    second_code, _ = registry.create_pairing_code()
    second_display, second_token = registry.register(
        second_code, "123456", "Office screen", 320, 820, "1.1.0",
    )

    assert second_display.id == first_display.id
    assert second_display.name == "Office screen"
    assert second_display.rotation == 270
    with pytest.raises(DisplayAuthenticationError):
        registry.authenticate(first_display.id, first_token)
    assert registry.authenticate(second_display.id, second_token).firmware_version == "1.1.0"
