"""Persistent display profiles identified by each ESP32's eFuse MAC address."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time

from .display_settings import VALID_ROTATIONS


class DisplayRegistryError(ValueError):
    """Base error for display registry requests."""


class DisplayNotFoundError(DisplayRegistryError):
    """Raised when a requested display does not exist."""


@dataclass(frozen=True)
class DisplayDevice:
    """The persistent profile associated with one physical display."""

    id: str
    hardware_id: str
    name: str
    width: int
    height: int
    firmware_version: str
    rotation: int
    video_rotation: int
    capabilities: dict[str, bool]
    paired_at: float
    last_seen: float
    last_activity_message: str
    last_activity_at: float

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
            "video_rotation": self.video_rotation,
            "capabilities": dict(self.capabilities),
            "online": now - self.last_seen <= DisplayRegistry.online_after_seconds,
            "paired_at": datetime.fromtimestamp(self.paired_at, UTC).isoformat(),
            "last_seen": datetime.fromtimestamp(self.last_seen, UTC).isoformat(),
            "last_activity": {
                "message": self.last_activity_message,
                "at": datetime.fromtimestamp(self.last_activity_at, UTC).isoformat(),
            },
        }


class DisplayRegistry:
    """SQLite-backed display registry for a trusted local network."""

    online_after_seconds = 90

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()
        self._lock = RLock()
        self._initialize_database()

    @staticmethod
    def _default_path() -> Path:
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "displays.sqlite3"

    def register(
        self,
        hardware_id: str,
        name: str,
        width: int,
        height: int,
        firmware_version: str,
        capabilities: dict[str, bool] | None = None,
    ) -> DisplayDevice:
        """Create or refresh a display profile identified by its hardware MAC."""
        normalized_hardware_id = hardware_id.strip().lower()
        normalized_capabilities = self._normalize_capabilities(capabilities)
        now = time.time()
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM displays WHERE hardware_id = ?", (normalized_hardware_id,)
            ).fetchone()
            display_id = str(existing["id"]) if existing is not None else normalized_hardware_id
            connection.execute(
                """
                INSERT INTO displays (
                    id, hardware_id, token_digest, name, width, height,
                    firmware_version, rotation, capabilities, paired_at, last_seen,
                    last_activity_message, last_activity_at
                ) VALUES (?, ?, '', ?, ?, ?, ?, 0, ?, ?, ?, 'Connected to ESPImageServer', ?)
                ON CONFLICT(hardware_id) DO UPDATE SET
                    name = excluded.name,
                    width = excluded.width,
                    height = excluded.height,
                    firmware_version = excluded.firmware_version,
                    capabilities = excluded.capabilities,
                    last_seen = excluded.last_seen
                """,
                (
                    display_id, normalized_hardware_id, name.strip(), width, height,
                    firmware_version, json.dumps(normalized_capabilities, separators=(",", ":")), now, now, now,
                ),
            )
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

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

    def heartbeat(
        self,
        display_id: str,
        firmware_version: str | None = None,
        capabilities: dict[str, bool] | None = None,
    ) -> DisplayDevice:
        """Record that a known display is online and refresh optional details."""
        fields = ["last_seen = ?"]
        values: list[object] = [time.time()]
        if firmware_version is not None:
            fields.append("firmware_version = ?")
            values.append(firmware_version)
        if capabilities is not None:
            fields.append("capabilities = ?")
            values.append(json.dumps(self._normalize_capabilities(capabilities), separators=(",", ":")))
        values.append(display_id)
        with self._lock, self._connection() as connection:
            updated = connection.execute(
                f"UPDATE displays SET {', '.join(fields)} WHERE id = ?", values,
            ).rowcount
            if not updated:
                raise DisplayNotFoundError("Display was not found")
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def record_activity(self, display_id: str, message: str) -> DisplayDevice:
        """Record a meaningful firmware interaction while keeping the display online."""
        now = time.time()
        with self._lock, self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE displays
                SET last_seen = ?, last_activity_message = ?, last_activity_at = ?
                WHERE id = ?
                """,
                (now, message, now, display_id),
            ).rowcount
            if not updated:
                raise DisplayNotFoundError("Display was not found")
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

    def set_video_rotation(self, display_id: str, rotation: int) -> DisplayDevice:
        if rotation not in VALID_ROTATIONS:
            raise DisplayRegistryError("Video rotation must be 0, 90, 180, or 270 degrees")
        with self._lock, self._connection() as connection:
            updated = connection.execute(
                "UPDATE displays SET video_rotation = ? WHERE id = ?", (rotation, display_id)
            ).rowcount
            if not updated:
                raise DisplayNotFoundError("Display was not found")
            row = connection.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        return self._row_to_device(row)

    def _initialize_database(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            # Keep the unused column so databases created by the pairing preview
            # remain readable. MAC registration never writes or reads a token.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS displays (
                    id TEXT PRIMARY KEY,
                    hardware_id TEXT NOT NULL UNIQUE,
                    token_digest TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    firmware_version TEXT NOT NULL,
                    rotation INTEGER NOT NULL DEFAULT 0,
                    video_rotation INTEGER NOT NULL DEFAULT 0,
                    capabilities TEXT NOT NULL DEFAULT '{}',
                    paired_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_activity_message TEXT NOT NULL DEFAULT '',
                    last_activity_at REAL NOT NULL DEFAULT 0
                )
                """
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(displays)")}
            if "video_rotation" not in columns:
                connection.execute("ALTER TABLE displays ADD COLUMN video_rotation INTEGER NOT NULL DEFAULT 0")
            if "last_activity_message" not in columns:
                connection.execute("ALTER TABLE displays ADD COLUMN last_activity_message TEXT NOT NULL DEFAULT ''")
            if "last_activity_at" not in columns:
                connection.execute("ALTER TABLE displays ADD COLUMN last_activity_at REAL NOT NULL DEFAULT 0")
            connection.execute(
                """
                UPDATE displays
                SET last_activity_message = 'Last contact with ESPImageServer', last_activity_at = last_seen
                WHERE last_activity_message = '' OR last_activity_at = 0
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
            video_rotation=int(row["video_rotation"]),
            capabilities={str(key): bool(value) for key, value in capabilities.items()},
            paired_at=float(row["paired_at"]),
            last_seen=float(row["last_seen"]),
            last_activity_message=str(row["last_activity_message"]),
            last_activity_at=float(row["last_activity_at"]),
        )
