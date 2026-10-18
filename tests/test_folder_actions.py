from pathlib import Path
from types import SimpleNamespace

import pytest

from esp_image_server import folder_actions as actions


def platform(monkeypatch, name):
    monkeypatch.setattr(actions, "sys", SimpleNamespace(platform=name))
    monkeypatch.setattr(actions.shutil, "which", lambda command: f"/tools/{command}")


def test_windows_chooser_handles_unicode_quotes_and_cancel(monkeypatch, tmp_path):
    platform(monkeypatch, "win32")
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(actions.subprocess, "run", run)
    assert actions.choose_folder(tmp_path / "User's \u00e9 folder") == ""
    assert "User''s" in calls[0][0][-1]
    assert calls[0][1]["encoding"] == "utf-8"
    monkeypatch.setattr(actions.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=str(tmp_path)))
    assert actions.choose_folder(tmp_path) == str(tmp_path)


def test_windows_reveal_retains_startfile(monkeypatch, tmp_path):
    platform(monkeypatch, "win32")
    opened = []
    monkeypatch.setattr(actions.os, "startfile", opened.append, raising=False)
    folder = tmp_path / "images"
    actions.reveal_folder(folder)
    assert opened == [folder]
    assert folder.is_dir()


@pytest.mark.parametrize("name, command", [("linux", "/tools/xdg-open"), ("darwin", "/usr/bin/open")])
def test_native_open_uses_argument_array(monkeypatch, tmp_path, name, command):
    platform(monkeypatch, name)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    calls = []
    monkeypatch.setattr(actions.subprocess, "run", lambda args, **kwargs: calls.append(args))
    folder = tmp_path / "Images with spaces"
    actions.reveal_folder(folder)
    assert calls == [[command, str(folder)]]
    with pytest.raises(actions.FolderActionUnavailable, match="desktop app to choose a library folder"):
        actions.choose_folder(folder)


def test_headless_linux_has_clear_fallback_without_creating_folders(monkeypatch, tmp_path):
    platform(monkeypatch, "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert actions.capabilities() == {"choose": False, "reveal": False}
    folder = tmp_path / "missing"
    with pytest.raises(actions.FolderActionUnavailable):
        actions.reveal_folder(folder)
    assert not folder.exists()


def test_missing_native_tools_disable_actions(monkeypatch):
    platform(monkeypatch, "win32")
    monkeypatch.setattr(actions.shutil, "which", lambda command: None)
    assert actions.capabilities()["choose"] is False
    platform(monkeypatch, "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(actions.shutil, "which", lambda command: None)
    assert actions.capabilities()["reveal"] is False


def test_wayland_reveal_preserves_unicode_and_shell_characters(monkeypatch, tmp_path):
    platform(monkeypatch, "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    calls = []
    monkeypatch.setattr(actions.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    folder = tmp_path / "User's créations 日本語; $literal"
    assert actions.capabilities() == {"choose": False, "reveal": True}
    actions.reveal_folder(folder)
    assert calls == [(["/tools/xdg-open", str(folder)],
                     {"check": True, "capture_output": True, "timeout": 15})]


def test_missing_macos_opener_disables_reveal(monkeypatch):
    platform(monkeypatch, "darwin")
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert actions.capabilities() == {"choose": False, "reveal": False}
