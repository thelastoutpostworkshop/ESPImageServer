from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from threading import Event
from urllib.error import HTTPError

import pytest

from esp_image_server.app_updates import (
    API, INSTALLER_NAMES, MAX_RELEASE_PAGES, MAX_RESPONSE_BYTES, REPOSITORY,
    AppUpdateChecker, fetch_releases, host_platform, latest_release,
)


def release(version, platforms=("win32-x64", "linux-x64"), **extra):
    names = [INSTALLER_NAMES[target].format(version=version) + suffix
             for target in platforms for suffix in ("", ".sha256")]
    return {
        "tag_name": f"v{version}", "html_url": f"{REPOSITORY}/releases/tag/v{version}",
        "assets": [{"name": name, "state": "uploaded", "size": 100,
                    "browser_download_url": f"{REPOSITORY}/releases/download/v{version}/{name}"}
                   for name in names],
        **extra,
    }


def checker(fetch=lambda: [release("1.0.110")], **kwargs):
    return AppUpdateChecker("1.0.105", platform_name="win32", machine="AMD64", fetch=fetch, **kwargs)


@pytest.mark.parametrize(("system", "architecture", "expected"), [
    ("win32", "AMD64", "win32-x64"), ("Windows", "x86_64", "win32-x64"),
    ("linux", "x86_64", "linux-x64"), ("linux", "aarch64", "linux-aarch64"),
    ("darwin", "arm64", "darwin-arm64"), ("win32", "x86", "win32-x86"),
])
def test_host_platform_uses_server_platform_and_architecture(system, architecture, expected):
    assert host_platform(system, architecture) == expected


def test_selects_highest_numeric_stable_version_with_exact_platform_pair():
    latest = latest_release([
        release("1.0.9"), release("1.0.110"), release("1.0.12"),
        release("2.0.0", draft=True), release("3.0.0", prerelease=True),
        release("4.0.0-rc.1"), release("05.0.0"), release("9.0.0", assets=[]),
        release("8.0.0", tag_name="8.0.0"), release("7.0.0", platforms=("linux-x64",)),
    ], "win32-x64")
    assert latest["version"] == "1.0.110"
    assert latest["download_url"].endswith("ESPImageServer-Setup-1.0.110.exe")
    assert latest["checksum_url"].endswith("ESPImageServer-Setup-1.0.110.exe.sha256")


@pytest.mark.parametrize("defect", ["missing_checksum", "wrong_url", "duplicate", "empty", "size_bool", "not_uploaded", "wrong_release_url"])
def test_rejects_incomplete_or_misleading_release_metadata(defect):
    invalid = release("2.0.0", platforms=("win32-x64",))
    if defect == "missing_checksum":
        invalid["assets"].pop()
    elif defect == "wrong_url":
        invalid["assets"][0]["browser_download_url"] = "https://example.com/installer.exe"
    elif defect == "duplicate":
        invalid["assets"].append(dict(invalid["assets"][0]))
    elif defect == "empty":
        invalid["assets"][0]["size"] = 0
    elif defect == "size_bool":
        invalid["assets"][0]["size"] = True
    elif defect == "not_uploaded":
        invalid["assets"][0]["state"] = "open"
    else:
        invalid["html_url"] = "https://example.com/releases/tag/v2.0.0"
    assert latest_release([release("1.0.110"), invalid], "win32-x64")["version"] == "1.0.110"


def test_linux_receives_linux_installer_and_unsupported_host_only_release_notes():
    linux = AppUpdateChecker("1.0.105", platform_name="linux", machine="x86_64", fetch=lambda: [release("1.0.110")]).check()
    assert linux["status"] == "update_available"
    assert linux["download_url"].endswith("ESPImageServer-1.0.110-linux-x64.deb")
    mac = AppUpdateChecker("1.0.105", platform_name="darwin", machine="arm64", fetch=lambda: [release("1.0.110")]).check()
    assert mac["status"] == "unsupported"
    assert mac["update_available"] is True
    assert mac["release_url"] == f"{REPOSITORY}/releases/tag/v1.0.110"
    assert mac["download_url"] is mac["checksum_url"] is None
    assert mac["supported_platform"] is False


@pytest.mark.parametrize("version", ["1.0.110", "1.0.100"])
def test_equal_or_older_published_release_does_not_notify(version):
    result = checker(lambda: [release(version)]).check()
    assert result["status"] == ("update_available" if version == "1.0.110" else "up_to_date")
    same = AppUpdateChecker(version, platform_name="win32", machine="AMD64", fetch=lambda: [release(version)]).check()
    assert same["status"] == "up_to_date"
    assert same["update_available"] is False
    assert same["download_url"] is None


def test_success_cache_and_manual_minimum_cooldown():
    calls = []
    now = [0]
    instance = checker(lambda: calls.append(True) or [release("1.0.110")], clock=lambda: now[0])
    result = instance.check()
    assert result["installed_version"] == "1.0.105"
    assert result["checked_successfully"] and result["checked_at"]
    assert result["retry_after_seconds"] == 60
    instance.check(force=True)
    now[0] = 59
    instance.check(force=True)
    assert len(calls) == 1
    now[0] = 60
    instance.check()
    assert len(calls) == 1
    instance.check(force=True)
    assert len(calls) == 2
    now[0] = 3659
    instance.check()
    assert len(calls) == 2
    now[0] = 3660
    instance.check()
    assert len(calls) == 3


def test_concurrent_checks_coalesce_into_one_request():
    started, finish = Event(), Event()
    calls = []

    def fetch():
        calls.append(True)
        started.set()
        assert finish.wait(3)
        return [release("1.0.110")]

    instance = checker(fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(instance.check)
        assert started.wait(3)
        second = pool.submit(instance.check, True)
        finish.set()
        assert first.result()["update_available"] and second.result()["update_available"]
    assert len(calls) == 1


@pytest.mark.parametrize("code", [401, 404])
def test_private_or_inaccessible_repository_is_unavailable_not_up_to_date(code):
    calls = []
    now = [0]

    def fetch():
        calls.append(True)
        raise HTTPError(API, code, "not public", {}, None)

    instance = checker(fetch, clock=lambda: now[0])
    result = instance.check()
    assert result["status"] == "unavailable"
    assert not result["update_available"] and not result["checked_successfully"]
    assert result["checked_at"] is None
    assert "private" in result["error"]
    now[0] = 899
    instance.check(force=True)
    assert len(calls) == 1
    now[0] = 900
    instance.check(force=True)
    assert len(calls) == 2


def test_offline_failure_retains_previous_known_update_as_stale_and_respects_retry():
    calls = []
    now = [0]

    def fetch():
        calls.append(True)
        if len(calls) > 1:
            raise OSError("offline")
        return [release("1.0.110")]

    instance = checker(fetch, clock=lambda: now[0])
    success = instance.check()
    now[0] = 3600
    failed = instance.check()
    assert failed["status"] == "error"
    assert failed["update_available"] and failed["stale"]
    assert not failed["checked_successfully"]
    assert failed["checked_at"] == success["checked_at"]
    assert failed["download_url"] == success["download_url"]
    instance.check(force=True)
    assert len(calls) == 2
    now[0] = 4500
    instance.check(force=True)
    assert len(calls) == 3


@pytest.mark.parametrize(("code", "headers", "expected_retry"), [
    (429, {"Retry-After": "1800"}, 1800),
    (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "8200"}, 7200),
    (429, {"Retry-After": "invalid"}, 900),
    (429, {"Retry-After": "inf"}, 900),
    (429, {"Retry-After": "1e9999"}, 900),
    (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "inf"}, 900),
])
def test_rate_limit_backoff_cannot_be_bypassed_manually(monkeypatch, code, headers, expected_retry):
    monkeypatch.setattr("esp_image_server.app_updates.time.time", lambda: 1000)
    now = [0]
    calls = []

    def fetch():
        calls.append(True)
        raise HTTPError(API, code, "rate limit", headers, None)

    instance = checker(fetch, clock=lambda: now[0])
    assert instance.check()["retry_after_seconds"] == expected_retry
    now[0] = expected_retry - 1
    instance.check(force=True)
    assert len(calls) == 1
    now[0] = expected_retry
    instance.check(force=True)
    assert len(calls) == 2


def test_empty_feed_and_unknown_installed_version_never_claim_up_to_date():
    empty = checker(lambda: []).check()
    assert empty["status"] == "unavailable"
    assert empty["latest_version"] is None
    assert empty["error"]
    calls = []
    unknown = AppUpdateChecker("unknown", fetch=lambda: calls.append(True)).check()
    assert unknown["status"] == "error"
    assert calls == []


def test_disabled_result_has_no_network_calls_or_cached_update_metadata():
    calls = []
    instance = checker(lambda: calls.append(True) or [release("1.0.110")])
    assert instance.disabled_result()["status"] == "disabled"
    assert not calls
    assert instance.check()["update_available"]
    disabled = instance.disabled_result()
    assert disabled["installed_version"] == "1.0.105"
    assert disabled["platform"] == "win32-x64"
    assert not disabled["update_available"]
    assert disabled["latest_version"] is disabled["release_url"] is disabled["download_url"] is None


def test_anonymous_fetch_is_bounded_paginated_and_sends_no_credentials(monkeypatch):
    calls = []

    def open_url(request, timeout):
        calls.append(request)
        assert 0 < timeout <= 10
        headers = {key.lower(): value for key, value in request.header_items()}
        assert headers == {"accept": "application/vnd.github+json", "user-agent": "ESPImageServer"}
        return BytesIO(json.dumps([release("1.0.110")] * (100 if len(calls) == 1 else 1)).encode())

    monkeypatch.setattr("esp_image_server.app_updates.urlopen", open_url)
    assert len(fetch_releases()) == 101
    assert [request.full_url for request in calls] == [f"{API}?per_page=100&page=1", f"{API}?per_page=100&page=2"]


@pytest.mark.parametrize("payload", [b"{}", b"invalid JSON", b"x" * (MAX_RESPONSE_BYTES + 1)], ids=["object", "invalid-json", "oversized"])
def test_fetch_rejects_invalid_or_oversized_responses(monkeypatch, payload):
    monkeypatch.setattr("esp_image_server.app_updates.urlopen", lambda *args, **kwargs: BytesIO(payload))
    with pytest.raises(ValueError):
        fetch_releases()


def test_fetch_page_limit_fails_instead_of_silently_missing_releases(monkeypatch):
    calls = []
    monkeypatch.setattr("esp_image_server.app_updates.urlopen", lambda *args, **kwargs: calls.append(True) or BytesIO(b"[{}]".replace(b"{}", b"{}," * 99 + b"{}")))
    with pytest.raises(ValueError, match="Too many releases"):
        fetch_releases()
    assert len(calls) == MAX_RELEASE_PAGES


def test_fetch_obeys_total_lookup_deadline(monkeypatch):
    times = iter([0, 0, 21])
    monkeypatch.setattr("esp_image_server.app_updates.time.monotonic", lambda: next(times))
    calls = []
    monkeypatch.setattr("esp_image_server.app_updates.urlopen", lambda *args, **kwargs: calls.append(True) or BytesIO(json.dumps([{}] * 100).encode()))
    with pytest.raises(TimeoutError):
        fetch_releases()
    assert len(calls) == 1
