"""Cached, advisory release notifications; USB identity still controls installation."""

from datetime import UTC, datetime
import json
import re
from threading import Lock
import time
from urllib.request import Request, urlopen

REPOSITORY = "https://github.com/thelastoutpostworkshop/ESPImageFirmware"
API = "https://api.github.com/repos/thelastoutpostworkshop/ESPImageFirmware/releases"
# Native dimensions distinguish the currently supported profiles, even after renaming.
# This is only a notification hint, never authority to choose or flash a binary.
BOARD_PROFILES = {
    (480, 272): "JC4827W543",
    (320, 820): "ST7701_320X820",
    (172, 320): "ESP32_C6_LCD_147",
    (240, 320): "CHEAP_YELLOW_DISPLAY",
    (466, 466): "ESP32_S3_AMOLED_143",
}


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        return None
    return tuple(map(int, value.split(".")))


def fetch_releases():
    releases = []
    for page in range(1, 11):
        request = Request(f"{API}?per_page=100&page={page}", headers={
            "Accept": "application/vnd.github+json", "User-Agent": "ESPImageServer",
        })
        with urlopen(request, timeout=10) as response:
            data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("Release response is too large")
        batch = json.loads(data)
        if not isinstance(batch, list):
            raise ValueError("Invalid release response")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise ValueError("Too many releases")


def latest_releases(releases):
    latest = {}
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else ""
        key = version_key(version)
        if key is None:
            continue
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            continue

        def has_asset(name, limit):
            matches = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
            if len(matches) != 1:
                return False
            asset = matches[0]
            size = asset.get("size")
            return (asset.get("state") == "uploaded" and isinstance(size, int) and 0 < size <= limit
                    and asset.get("browser_download_url") == f"{REPOSITORY}/releases/download/{tag}/{name}")

        if not has_asset("SHA256SUMS.txt", 65536):
            continue
        for board in BOARD_PROFILES.values():
            if has_asset(f"ESPImageDisplay-{board}-{version}.zip", 32 * 1024 * 1024):
                if board not in latest or key > version_key(latest[board]["version"]):
                    latest[board] = {"version": version, "release_url": f"{REPOSITORY}/releases/tag/{tag}"}
    return latest


class FirmwareUpdateChecker:
    def __init__(self, fetch=fetch_releases, clock=time.monotonic):
        self.fetch = fetch
        self.clock = clock
        self.lock = Lock()
        self.next_check = 0
        self.latest = {}
        self.checked_at = None
        self.error = ""

    def check(self, displays):
        candidates = [d for d in displays if d.get("online")
                      and (d.get("width"), d.get("height")) in BOARD_PROFILES
                      and version_key(d.get("firmware_version")) is not None]
        if not candidates:
            return {"updates": [], "checked_at": self.checked_at, "error": ""}
        with self.lock:
            if self.clock() >= self.next_check:
                try:
                    self.latest = latest_releases(self.fetch())
                    self.checked_at = datetime.now(UTC).isoformat()
                    self.error = ""
                    self.next_check = self.clock() + 3600
                except (OSError, ValueError):
                    self.error = "Could not check firmware releases. Will retry automatically in 15 minutes."
                    self.next_check = self.clock() + 900
            updates = []
            for display in candidates:
                board = BOARD_PROFILES[(display["width"], display["height"])]
                release = self.latest.get(board)
                if release and version_key(release["version"]) > version_key(display["firmware_version"]):
                    updates.append({"display_id": display["id"], "name": display["name"],
                                    "board": board, "installed_version": display["firmware_version"], **release})
            return {"updates": updates, "checked_at": self.checked_at, "error": self.error}
