"""Anonymous, cached notifications for published ESPImageServer installers."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
from math import ceil, isfinite
import platform
import sys
from threading import Lock
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .firmware_updates import version_key
from .version import APP_VERSION


REPOSITORY = "https://github.com/thelastoutpostworkshop/ESPImageServer"
API = "https://api.github.com/repos/thelastoutpostworkshop/ESPImageServer/releases"
SUCCESS_CACHE_SECONDS = 3600
MANUAL_COOLDOWN_SECONDS = 60
ERROR_RETRY_SECONDS = 900
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_RELEASE_PAGES = 10
FETCH_TIMEOUT_SECONDS = 20
INSTALLER_NAMES = {
    "win32-x64": "ESPImageServer-Setup-{version}.exe",
    "linux-x64": "ESPImageServer-{version}-linux-x64.deb",
}


def host_platform(platform_name: str | None = None, machine: str | None = None) -> str:
    """Identify the server host rather than the visiting browser's computer."""
    platform_name = (platform_name or sys.platform).lower()
    platform_name = {"windows": "win32", "darwin": "darwin"}.get(platform_name, platform_name)
    architecture = (machine or platform.machine() or "unknown").lower()
    architecture = "x64" if architecture in {"amd64", "x86_64", "x64"} else architecture
    return f"{platform_name}-{architecture}"


def fetch_releases() -> list[dict[str, object]]:
    """Fetch a bounded public feed without tokens, cookies, or local settings."""
    releases = []
    remaining_bytes = MAX_RESPONSE_BYTES
    deadline = time.monotonic() + FETCH_TIMEOUT_SECONDS
    for page_number in range(1, MAX_RELEASE_PAGES + 1):
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise TimeoutError("Release lookup exceeded its time limit")
        request = Request(f"{API}?per_page=100&page={page_number}", headers={
            "Accept": "application/vnd.github+json", "User-Agent": "ESPImageServer",
        })
        with urlopen(request, timeout=min(10, remaining_time)) as response:
            data = response.read(remaining_bytes + 1)
        if len(data) > remaining_bytes:
            raise ValueError("Release response is too large")
        remaining_bytes -= len(data)
        batch = json.loads(data)
        if not isinstance(batch, list):
            raise ValueError("Invalid release response")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise ValueError("Too many releases")


def latest_release(releases: list[dict[str, object]], target_platform: str) -> dict[str, object] | None:
    """Choose the highest stable version with a verified asset-name/URL pair.

    These checks validate release metadata, not the downloaded installer bytes.
    Unsupported hosts can receive release notes when another supported host
    has a complete installer/checksum pair, but never an unrelated installer.
    """
    latest = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else None
        key = version_key(version)
        if key is None:
            continue
        release_url = f"{REPOSITORY}/releases/tag/{tag}"
        if "html_url" in release and release["html_url"] != release_url:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue

        def asset_url(name: str, maximum_size: int) -> str | None:
            matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
            if len(matches) != 1:
                return None
            asset = matches[0]
            size = asset.get("size")
            url = f"{REPOSITORY}/releases/download/{tag}/{name}"
            if (asset.get("state") == "uploaded" and isinstance(size, int) and not isinstance(size, bool)
                    and 0 < size <= maximum_size and asset.get("browser_download_url") == url):
                return url
            return None

        pairs = {}
        for target, template in INSTALLER_NAMES.items():
            filename = template.format(version=version)
            download = asset_url(filename, 2 * 1024 * 1024 * 1024)
            checksum = asset_url(filename + ".sha256", 64 * 1024)
            if download and checksum:
                pairs[target] = (download, checksum)
        if target_platform in INSTALLER_NAMES and target_platform not in pairs:
            continue
        if not pairs:
            continue
        if latest is None or key > version_key(latest["version"]):
            pair = pairs.get(target_platform, (None, None))
            latest = {"version": version, "release_url": release_url,
                      "download_url": pair[0], "checksum_url": pair[1]}
    return latest


def _error_retry_seconds(error: HTTPError) -> float:
    """Respect GitHub's retry/reset headers, including on a manual check."""
    retry = float(ERROR_RETRY_SECONDS)
    headers = error.headers or {}
    value = headers.get("Retry-After")
    if value:
        try:
            seconds = float(value)
            if isfinite(seconds):
                retry = max(retry, seconds)
        except (TypeError, ValueError):
            try:
                retry = max(retry, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    if headers.get("X-RateLimit-Remaining") == "0":
        try:
            seconds = float(headers.get("X-RateLimit-Reset", "0")) - time.time()
            if isfinite(seconds):
                retry = max(retry, seconds)
        except (TypeError, ValueError):
            pass
    return retry


class AppUpdateChecker:
    def __init__(
        self,
        installed_version: str = APP_VERSION,
        *,
        platform_name: str | None = None,
        machine: str | None = None,
        fetch=None,
        clock=time.monotonic,
    ) -> None:
        self.installed_version = installed_version
        self.platform = host_platform(platform_name, machine)
        self.fetch = fetch or fetch_releases
        self.clock = clock
        self.lock = Lock()
        self.latest = None
        self.checked_at = None
        self.next_check = 0.0
        self.manual_check_after = 0.0
        self.outcome = "not_checked"
        self.error = ""

    def disabled_result(self) -> dict[str, object]:
        return {
            "status": "disabled", "installed_version": self.installed_version,
            "latest_version": None, "update_available": False, "release_url": None,
            "download_url": None, "checksum_url": None, "platform": self.platform,
            "supported_platform": self.platform in INSTALLER_NAMES,
            "checked_at": None, "checked_successfully": False, "error": "",
            "retry_after_seconds": 0, "stale": False,
        }

    def check(self, force: bool = False) -> dict[str, object]:
        with self.lock:
            if version_key(self.installed_version) is None:
                result = self.disabled_result()
                result.update(status="error", error="The installed app version is not recorded; releases cannot be compared.")
                return result
            next_allowed = self.manual_check_after if force else self.next_check
            if self.clock() >= next_allowed:
                self._refresh_locked()
            return self._result_locked()

    def _refresh_locked(self) -> None:
        retry = ERROR_RETRY_SECONDS
        try:
            releases = self.fetch()
            if not isinstance(releases, list):
                raise ValueError("Invalid release response")
            self.latest = latest_release(releases, self.platform)
            self.checked_at = datetime.now(UTC).isoformat()
            self.outcome = "ok" if self.latest else "unavailable"
            self.error = "" if self.latest else "No published app release with a complete installer is publicly available yet."
            self.next_check = self.clock() + SUCCESS_CACHE_SECONDS
            self.manual_check_after = self.clock() + MANUAL_COOLDOWN_SECONDS
            return
        except HTTPError as exc:
            retry = _error_retry_seconds(exc)
            if exc.code in {401, 404}:
                self.outcome = "unavailable"
                self.error = "Public app releases are unavailable. The repository may still be private."
            elif exc.code in {403, 429}:
                self.outcome = "error"
                self.error = "GitHub could not accept another update check. The app will retry later."
            else:
                self.outcome = "error"
                self.error = "Could not check app releases. The app will retry later."
        except (OSError, ValueError):
            self.outcome = "error"
            self.error = "Could not check app releases. Check your internet connection or try again later."
        self.next_check = self.manual_check_after = self.clock() + retry

    def _result_locked(self) -> dict[str, object]:
        result = self.disabled_result()
        newer = self.latest is not None and version_key(self.latest["version"]) > version_key(self.installed_version)
        supported = self.platform in INSTALLER_NAMES
        successful = self.outcome == "ok"
        result.update(
            status=("update_available" if newer else "up_to_date") if successful and supported else "unsupported" if successful else self.outcome,
            update_available=newer, latest_version=self.latest["version"] if self.latest else None,
            release_url=self.latest["release_url"] if self.latest else None,
            download_url=self.latest["download_url"] if newer and self.latest else None,
            checksum_url=self.latest["checksum_url"] if newer and self.latest else None,
            checked_at=self.checked_at, checked_successfully=successful, error=self.error,
            retry_after_seconds=max(0, ceil(self.manual_check_after - self.clock())),
            stale=self.latest is not None and not successful,
        )
        return result
