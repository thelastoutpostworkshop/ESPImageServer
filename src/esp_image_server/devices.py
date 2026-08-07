"""In-memory pairing and JPEG delivery for ESP32 displays."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets
from threading import Condition, RLock
import time
from uuid import uuid4


class DeviceError(ValueError):
    """Raised when a requested device or credential is invalid."""


@dataclass(frozen=True)
class QueuedImage:
    image_id: str
    jpeg: bytes
    created_at: float


@dataclass
class Device:
    device_id: str
    name: str
    token: str
    paired_at: float
    last_seen: float
    queue: list[QueuedImage] = field(default_factory=list)


class DeviceManager:
    """Thread-safe, ephemeral device registry and per-device image queues."""

    pairing_code_lifetime_seconds = 600
    max_queued_image_bytes = 10 * 1024 * 1024

    def __init__(self) -> None:
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._devices: dict[str, Device] = {}
        self._pairing_codes: dict[str, float] = {}

    def create_pairing_code(self) -> tuple[str, int]:
        with self._changed:
            self._remove_expired_codes()
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._pairing_codes[code] = time.monotonic() + self.pairing_code_lifetime_seconds
            return code, self.pairing_code_lifetime_seconds

    def register_device(self, pairing_code: str, name: str) -> Device:
        with self._changed:
            self._remove_expired_codes()
            if pairing_code not in self._pairing_codes:
                raise DeviceError("Pairing code is invalid or has expired")
            del self._pairing_codes[pairing_code]
            now = time.monotonic()
            device = Device(
                device_id=uuid4().hex,
                name=name.strip(),
                token=secrets.token_urlsafe(32),
                paired_at=now,
                last_seen=now,
            )
            self._devices[device.device_id] = device
            self._changed.notify_all()
            return device

    def list_devices(self) -> list[dict[str, object]]:
        with self._lock:
            now = time.monotonic()
            return [
                {
                    "id": device.device_id,
                    "name": device.name,
                    "online": now - device.last_seen <= 45,
                    "queued_images": len(device.queue),
                }
                for device in self._devices.values()
            ]

    def heartbeat(self, device_id: str, token: str) -> Device:
        with self._changed:
            device = self._authenticate(device_id, token)
            device.last_seen = time.monotonic()
            self._changed.notify_all()
            return device

    def queue_image(self, device_id: str, jpeg: bytes) -> tuple[QueuedImage, Device]:
        if not jpeg:
            raise DeviceError("The JPEG is empty")
        if len(jpeg) > self.max_queued_image_bytes:
            raise DeviceError("The JPEG is too large")
        with self._changed:
            device = self._get_device(device_id)
            image = QueuedImage(uuid4().hex, jpeg, time.monotonic())
            device.queue.append(image)
            self._changed.notify_all()
            return image, device

    def next_image(self, device_id: str, token: str, wait_seconds: int) -> QueuedImage | None:
        deadline = time.monotonic() + wait_seconds
        with self._changed:
            device = self._authenticate(device_id, token)
            device.last_seen = time.monotonic()
            while not device.queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._changed.wait(remaining)
                device = self._authenticate(device_id, token)
                device.last_seen = time.monotonic()
            return device.queue[0]

    def acknowledge(self, device_id: str, token: str, image_id: str) -> Device:
        with self._changed:
            device = self._authenticate(device_id, token)
            if not device.queue or device.queue[0].image_id != image_id:
                raise DeviceError("Image acknowledgement does not match the queued image")
            device.queue.pop(0)
            device.last_seen = time.monotonic()
            self._changed.notify_all()
            return device

    def _get_device(self, device_id: str) -> Device:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise DeviceError("Device was not found") from exc

    def _authenticate(self, device_id: str, token: str) -> Device:
        device = self._get_device(device_id)
        if not secrets.compare_digest(device.token, token):
            raise DeviceError("Device token is invalid")
        return device

    def _remove_expired_codes(self) -> None:
        now = time.monotonic()
        for code, expires_at in list(self._pairing_codes.items()):
            if expires_at <= now:
                del self._pairing_codes[code]
