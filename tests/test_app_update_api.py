"""Application update checks stay optional and independent of generation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from esp_image_server.app import create_app
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.config import Settings
from esp_image_server.version import APP_VERSION


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))


def update_result(status="update_available"):
    repository = "https://github.com/thelastoutpostworkshop/ESPImageServer"
    filename = "ESPImageServer-Setup-99.0.0.exe"
    return {
        "status": status,
        "installed_version": APP_VERSION,
        "latest_version": "99.0.0",
        "release_url": f"{repository}/releases/tag/v99.0.0",
        "download_url": f"{repository}/releases/download/v99.0.0/{filename}",
        "checksum_url": f"{repository}/releases/download/v99.0.0/{filename}.sha256",
        "platform": "windows-x64",
        "checked_at": "2026-10-07T12:00:00Z",
        "checked_successfully": True,
        "error": "",
        "retry_after_seconds": 0,
        "stale": False,
    }


class StubUpdateChecker:
    platform = "windows-x64"

    def __init__(self):
        self.calls = []

    def check(self, force=False):
        self.calls.append(force)
        return update_result()

    def disabled_result(self):
        return {
            **update_result("disabled"),
            "latest_version": None,
            "release_url": None,
            "download_url": None,
            "checksum_url": None,
            "checked_at": None,
            "checked_successfully": False,
        }


def make_app(checker, store=None):
    def unexpected_generation(*args, **kwargs):
        raise AssertionError("An update check must not load or generate artwork")

    return create_app(
        Settings(),
        SimpleNamespace(device="cpu", ready=False, load=unexpected_generation, generate=unexpected_generation),
        app_settings_store=store,
        app_update_checker=checker,
        enable_mdns=False,
    )


def test_automatic_checks_default_on_and_return_server_result_without_browser_caching():
    checker = StubUpdateChecker()
    with TestClient(make_app(checker)) as client:
        assert client.get("/app-settings").json()["auto_check_app_updates"] is True
        # The browser can run on a different OS from the application server.
        response = client.get("/app-updates", headers={"User-Agent": "Linux browser"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["enabled"] is True
        assert response.json()["platform"] == "windows-x64"
        assert response.json()["status"] == "update_available"
        assert response.json()["download_url"] == update_result()["download_url"]
        assert checker.calls == [False]
        assert client.get("/health").status_code == 200


def test_opt_out_survives_other_settings_and_restart_but_manual_check_still_works(tmp_path):
    store = AppSettingsStore(tmp_path / "settings.json")
    checker = StubUpdateChecker()
    with TestClient(make_app(checker, store)) as client:
        assert client.put("/app-settings", json={"auto_check_app_updates": False}).status_code == 200
        assert client.put("/app-settings", json={"jpeg_quality": 80}).status_code == 200
        assert store.get()["auto_check_app_updates"] is False
        disabled = client.get("/app-updates")
        assert disabled.headers["cache-control"] == "no-store"
        assert disabled.json()["status"] == "disabled"
        assert disabled.json()["enabled"] is False
        assert disabled.json()["download_url"] is None
        assert not checker.calls

    with TestClient(make_app(checker, store)) as client:
        assert client.get("/app-settings").json()["auto_check_app_updates"] is False
        assert client.get("/app-updates").json()["status"] == "disabled"
        assert not checker.calls
        manual = client.post("/app-updates/check")
        assert manual.status_code == 200
        assert manual.headers["cache-control"] == "no-store"
        assert manual.json()["status"] == "update_available"
        assert manual.json()["enabled"] is False
        assert checker.calls == [True]
        assert store.get()["auto_check_app_updates"] is False
        assert client.get("/app-updates").json()["status"] == "disabled"
        assert checker.calls == [True]
        client.put("/app-settings", json={"auto_check_app_updates": True})
        assert client.get("/app-updates").json()["status"] == "update_available"
        assert checker.calls == [True, False]


def test_disabling_checks_during_request_suppresses_automatic_notification():
    started, release = Event(), Event()

    class BlockingChecker(StubUpdateChecker):
        def check(self, force=False):
            started.set()
            assert release.wait(5), "Timed out waiting for test to release update check"
            return super().check(force)

    checker = BlockingChecker()
    with TestClient(make_app(checker)) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.get, "/app-updates")
        try:
            assert started.wait(5), "The automatic update check did not start"
            assert client.put("/app-settings", json={"auto_check_app_updates": False}).status_code == 200
        finally:
            release.set()
        response = future.result(timeout=5)
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"
        assert response.json()["enabled"] is False
        assert response.json()["download_url"] is None
