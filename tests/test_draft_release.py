import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location("draft_release", Path(__file__).parents[1] / "ci/draft_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def assets(tmp_path):
    for target, name in (
        ("win32-x64", "ESPImageServer-Setup-1.2.3.exe"),
        ("linux-x64", "ESPImageServer-1.2.3-linux-x64.deb"),
    ):
        folder = tmp_path / f"installer-{target}"
        folder.mkdir()
        (folder / name).write_bytes(b"installer fixture")
        (folder / (name + ".sha256")).write_text(
            f"{hashlib.sha256(b'installer fixture').hexdigest()}  {name}\n", encoding="utf-8")
    return tmp_path


def test_complete_installers(assets):
    assert len(release.validate_assets(assets, "1.2.3")) == 4


@pytest.mark.parametrize("damage", ["missing", "extra", "modified", "version", "empty"])
def test_reject_incomplete_or_corrupt_installers(assets, damage):
    installer = next(assets.rglob("*.exe"))
    if damage == "missing":
        installer.unlink()
    elif damage == "extra":
        (assets / "unexpected.exe").write_bytes(b"extra")
    elif damage == "modified":
        installer.write_bytes(b"changed")
    elif damage == "empty":
        installer.write_bytes(b"")
    with pytest.raises(ValueError):
        release.validate_assets(assets, "2.0.0" if damage == "version" else "1.2.3")


def test_existing_draft_is_never_replaced(monkeypatch):
    monkeypatch.setattr(release.subprocess, "check_output", lambda *a, **k: '[[{"tag_name": "v1.2.3", "draft": true}]]')
    with pytest.raises(ValueError, match="already exists"):
        release.ensure_unused_version("owner/repo", "v1.2.3", "a" * 40)


@pytest.mark.parametrize("code, stdout, error", [
    (0, "a" * 40 + "\trefs/tags/v1.2.3\n", None),
    (0, "b" * 40 + "\trefs/tags/v1.2.3\n" + "a" * 40 + "\trefs/tags/v1.2.3^{}\n", None),
    (0, "b" * 40 + "\trefs/tags/v1.2.3\n", ValueError),
    (128, "", RuntimeError), (2, "", RuntimeError),
])
def test_tag_check_fails_closed(monkeypatch, code, stdout, error):
    monkeypatch.setattr(release.subprocess, "check_output", lambda *a, **k: '[[]]')
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, "failure"))
    if error:
        with pytest.raises(error):
            release.ensure_unused_version("owner/repo", "v1.2.3", "a" * 40)
    else:
        release.ensure_unused_version("owner/repo", "v1.2.3", "a" * 40)


@pytest.mark.parametrize("event, ref_type, tag, valid", [
    ("push", "tag", "v1.2.3", True),
    ("push", "tag", "v1.2.4", False),
    ("push", "tag", "v1.2.3-rc1", False),
    ("push", "branch", "v1.2.3", False),
    ("workflow_dispatch", "tag", "v1.2.3", False),
])
def test_release_tag_must_match_project(monkeypatch, event, ref_type, tag, valid):
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": event,
                       "GITHUB_REF_TYPE": ref_type, "GITHUB_REF_NAME": tag}.items():
        monkeypatch.setenv(key, value)
    if valid:
        assert release.release_tag("1.2.3") == tag
    else:
        with pytest.raises((ValueError, RuntimeError)):
            release.release_tag("1.2.3")


def test_create_is_draft_for_tested_commit(assets, monkeypatch):
    monkeypatch.chdir(assets)
    (assets / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    # Keep metadata outside the downloaded artifact tree.
    payload = assets / "payload"
    payload.mkdir()
    for folder in assets.glob("installer-*"):
        folder.rename(payload / folder.name)
    for key, value in {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v1.2.3",
        "GITHUB_REPOSITORY": "owner/repo", "GITHUB_SHA": "a" * 40,
        "GITHUB_STEP_SUMMARY": str(assets / "summary.md"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(release.sys, "argv", ["draft_release.py", str(payload)])
    monkeypatch.setattr(release, "ensure_unused_version", lambda *a: None)
    commands = []
    monkeypatch.setattr(release.subprocess, "run", lambda args, **kwargs: commands.append(args))
    release.main()
    assert len(commands) == 1
    command = commands[0]
    assert command[:4] == ["gh", "release", "create", "v1.2.3"]
    assert "--verify-tag" in command
    assert "--draft" in command
    assert command[command.index("--target") + 1] == "a" * 40
