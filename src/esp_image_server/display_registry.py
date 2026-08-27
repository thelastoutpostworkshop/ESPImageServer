"""Persistent identities, profiles, and credentials for ESP32 displays."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
import time
from uuid import uuid4

from .display_settings import VALID_ROTATIONS


class DisplayRegistryError(ValueError):
    """Base error for display registry requests."""


class PairingCodeError(DisplayRegistryError):
    """Raised when a display pairing code is invalid or expired."""


class DisplayNotFoundError(DisplayRegistryError):
    """Raised when a requested display does not exist."""


class DisplayAuthenticationError(DisplayRegistryError):
    """Raised when a display credential is invalid."""


@dataclass(frozen=True)
class DisplayDevice:
    """The non-secret state associated with one paired physical display."""

    id: str
    hardware_id: str
    name: str
    width: int
    height: int
    firmware_version: str
    rotation: int
    capabilities: dict[str, bool]
    paired_at: float
    last_seen: float

    def as_dict(self, now: float | None = None) -> dict[str, object]:
        now = time.time() if now is None else now
        return {
            "id": self.id,
            "hardware_id": self.hardware_id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "firmware_version": self.firmware_version,
            "rotation": self.rotation,
            "capabilities": dict(self.capabilities),
            "online": now - self.last_seen <= DisplayRegistry.online_after_seconds,
            "paired_at": datetime.fromtimestamp(self.paired_at, UTC).isoformat(),
            "last_seen": datetime.fromtimestamp(self.last_seen, UTC).isoformat(),
        }


class DisplayRegistry:
    """SQLite-backed registry for displays that survive server restarts."""

    pairing_code_lifetime_seconds = 600
    online_after_seconds = 90

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()
        self._lock = RLock()
        self._pairing_codes: dict[str, float] = {}
        self._initialize_database()

    @staticmethod
    def _default_path() -> Path:
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "displays.sqlite3"

    def create_pairing_code(self) -> tuple[str, int]:
        with self._lock:
            self._remove_expired_codes()
            while True:
                code = f"{secrets.randbelow(1_000_000):06d}"
                if code not in self._pairing_codes:
                    break
            self._pairing_codes[code] = time.monotonic() + self.pairing_code_lifetime_seconds
            return code, self.pairing_code_lifetime_seconds

    def register(
        self,
        pairing_code: str,
        hardware_id: str,
        name: str,
        width: int,
        height: int,
        firmware_version: str,
        capabilities: dict[str, bool] | None = None,
    ) -> tuple[DisplayDevice, str]:
        """Pair a display and rotate its credential if it was paired before."""
        with self._lock:
            self._remove_expired_codes()
            if pairing_code not in self._pairing_codes:
                raise PairingCodeError("Pairing code is invalid or has expired")
            del self._pairing_codes[pairing_code]

            now = time.time()
            token = secrets.token_urlsafe(32)
            token_digest = self._token_digest(token)
            normalized_capabilities = self._normalize_capabilities(capabilities)
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT id FROM displays WHERE hardware_id = ?", (hardware_id,)
                ).fetchone()
                display_id = str(existing["id"]) if existing is not None else uuid4().hex
                connection.execute(
                    """
                    INSERT INTO displays (
                        id, hardware_id, token_digest, name, width, height,
                        firmware_version, rotation, capabilities, paired_at, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    ON CONFLICT(hardware_id) DO UPDATE SET
                        token_digest = excluded.token_digest,
                        name = excluded.name,
                        width = excluded.width,
                        height = excluded.height,
                        firmware_version = excluded.firmware_version,
                        capabilities = excluded.capabilities,
                        paired_at = excluded.paired_at,
                        last_seen = excluded.last_seen
                    """,
                    (
                        display_id, hardware_id, token_digest, name.strip(), width, height,
                        firmware_version, json.dumps(normalized_capabilities, separators=(",", ":")), now, now,
                    ),
                )
                row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
            return self._row_to_device(row), token

    def list(self) -> list[DisplayDevice]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT * FROM displays ORDER BY name COLLATE NOCASE, id").fetchall()
        return [self._row_to_device(row) for row in rows]

    def get(self, display_id: str) -> DisplayDevice:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        if row is None:
            raise DisplayNotFoundError("Display was not found")
        return self._row_to_device(row)

    def authenticate(self, display_id: str, token: str) -> DisplayDevice:
        """Check a device credential and record that the board is online."""
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
            if row is None or not token or not secrets.compare_digest(
                str(row["token_digest"]), self._token_digest(token)
            ):
                raise DisplayAuthenticationError("Display credential is invalid")
            now = time.time()
            connection.execute("UPDATE displays SET last_seen = ? WHERE id = ?", (now, display_id))
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def heartbeat(
        self,
        display_id: str,
        token: str,
        firmware_version: str | None = None,
        capabilities: dict[str, bool] | None = None,
    ) -> DisplayDevice:
        """Authenticate a display and update details that may change after a flash."""
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
            if row is None or not token or not secrets.compare_digest(
                str(row["token_digest"]), self._token_digest(token)
            ):
                raise DisplayAuthenticationError("Display credential is invalid")
            now = time.time()
            if firmware_version is None and capabilities is None:
                connection.execute("UPDATE displays SET last_seen = ? WHERE id = ?", (now, display_id))
            elif capabilities is None:
                connection.execute(
                    "UPDATE displays SET last_seen = ?, firmware_version = ? WHERE id = ?",
                    (now, firmware_version, display_id),
                )
            elif firmware_version is None:
                connection.execute(
                    "UPDATE displays SET last_seen = ?, capabilities = ? WHERE id = ?",
                    (now, json.dumps(self._normalize_capabilities(capabilities), separators=(",", ":")), display_id),
                )
            else:
                connection.execute(
                    "UPDATE displays SET last_seen = ?, firmware_version = ?, capabilities = ? WHERE id = ?",
                    (
                        now, firmware_version,
                        json.dumps(self._normalize_capabilities(capabilities), separators=(",", ":")), display_id,
                    ),
                )
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def set_name(self, display_id: str, name: str) -> DisplayDevice:
        with self._lock, self._connection() as connection:
            updated = connection.execute(
                "UPDATE displays SET name = ? WHERE id = ?", (name.strip(), display_id)
            ).rowcount
            if not updated:
                raise DisplayNotFoundError("Display was not found")
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def set_rotation(self, display_id: str, rotation: int) -> DisplayDevice:
        if rotation not in VALID_ROTATIONS:
            raise DisplayRegistryError("Image rotation must be 0, 90, 180, or 270 degrees")
        with self._lock, self._connection() as connection:
            updated = connection.execute(
                "UPDATE displays SET rotation = ? WHERE id = ?", (rotation, display_id)
            ).rowcount
            if not updated:
                raise DisplayNotFoundError("Display was not found")
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def _initialize_database(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS displays (
                    id TEXT PRIMARY KEY,
                    hardware_id TEXT NOT NULL UNIQUE,
                    token_digest TEXT NOT NULL,
                    name TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    firmware_version TEXT NOT NULL,
                    rotation INTEGER NOT NULL DEFAULT 0,
                    capabilities TEXT NOT NULL DEFAULT '{}',
                    paired_at REAL NOT NULL,
                    last_seen REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _remove_expired_codes(self) -> None:
        now = time.monotonic()
        for code, expires_at in list(self._pairing_codes.items()):
            if expires_at <= now:
                del self._pairing_codes[code]

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_capabilities(capabilities: dict[str, bool] | None) -> dict[str, bool]:
        if capabilities is None:
            return {}
        return {str(key): bool(value) for key, value in capabilities.items()}

    @staticmethod
    def _row_to_device(row: sqlite3.Row | None) -> DisplayDevice:
        if row is None:
            raise DisplayNotFoundError("Display was not found")
        try:
            capabilities = json.loads(str(row["capabilities"]))
        except (TypeError, ValueError):
            capabilities = {}
        if not isinstance(capabilities, dict):
            capabilities = {}
        return DisplayDevice(
            id=str(row["id"]),
            hardware_id=str(row["hardware_id"]),
            name=str(row["name"]),
            width=int(row["width"]),
            height=int(row["height"]),
            firmware_version=str(row["firmware_version"]),
            rotation=int(row["rotation"]),
            capabilities={str(key): bool(value) for key, value in capabilities.items()},
            paired_at=float(row["paired_at"]),
            last_seen=float(row["last_seen"]),
        )
