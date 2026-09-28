from esp_image_server.firmware_updates import (
    SUPPORTED_BOARD_TARGETS, REPOSITORY, FirmwareUpdateChecker, latest_releases,
)


def release(version, boards=("JC4827W543",), **extra):
    names = ["SHA256SUMS.txt", *[f"ESPImageDisplay-{board}-{version}.zip" for board in boards]]
    return {"tag_name": f"v{version}", "assets": [
        {"name": name, "state": "uploaded", "size": 100,
         "browser_download_url": f"{REPOSITORY}/releases/download/v{version}/{name}"}
        for name in names], **extra}


def display(version="1.1.9", **extra):
    return {"id": "one", "name": "Renamed board", "width": 480, "height": 272,
            "online": True, "firmware_version": version, "board_target": "JC4827W543", **extra}


def test_latest_is_numeric_and_per_board_with_stable_complete_assets_only():
    releases = [release("1.1.9", SUPPORTED_BOARD_TARGETS), release("1.1.38"),
                release("1.2.0", prerelease=True), release("1.3.0", draft=True),
                release("2.0.0-rc.1"), release("3.0.0", assets=[])]
    wrong_url = release("4.0.0")
    wrong_url["assets"][1]["browser_download_url"] = "https://example.com/firmware.zip"
    releases.append(wrong_url)
    latest = latest_releases(releases)
    assert latest["JC4827W543"]["version"] == "1.1.38"
    assert latest["ST7701_320X820"]["version"] == "1.1.9"
    assert len(latest) == 5


def test_only_online_supported_older_versions_notify_and_cache_is_shared():
    calls = []
    now = [0]
    def fetch():
        calls.append(True)
        return [release("1.1.38")]
    checker = FirmwareUpdateChecker(fetch, lambda: now[0])
    assert checker.check([display(online=False)])["updates"] == []
    assert not calls
    targets = [display(), display("1.1.38", id="same"), display("2.0.0", id="newer"),
               display("unknown", id="unknown"), display(board_target="UNSUPPORTED", id="unsupported"), display(board_target=None, id="missing")]
    updates = checker.check(targets)["updates"]
    assert [u["display_id"] for u in updates] == ["one"]
    assert updates[0]["name"] == "Renamed board"
    checker.check(targets)
    assert len(calls) == 1
    now[0] = 3600
    checker.check(targets)
    assert len(calls) == 2


def test_failure_retries_without_repeated_requests_or_losing_last_success():
    now = [0]
    calls = []
    def fetch():
        calls.append(True)
        if len(calls) > 1:
            raise OSError("Offline")
        return [release("1.1.38")]
    checker = FirmwareUpdateChecker(fetch, lambda: now[0])
    assert checker.check([display()])["updates"]
    now[0] = 3600
    result = checker.check([display()])
    assert result["error"] and result["checked_at"] and result["updates"]
    checker.check([display()])
    assert len(calls) == 2
    now[0] += 900
    checker.check([display()])
    assert len(calls) == 3


def test_board_identifier_wins_over_matching_dimensions_and_name():
    checker = FirmwareUpdateChecker(lambda: [release("1.1.38"), release("1.1.20", ("ST7701_320X820",))])
    result = checker.check([display(board_target="ST7701_320X820"),
                            display(id="missing", board_target=""),
                            display(id="unknown", board_target="FUTURE_BOARD")])
    assert len(result["updates"]) == 1
    assert result["updates"][0]["board"] == "ST7701_320X820"
    assert result["updates"][0]["version"] == "1.1.20"
