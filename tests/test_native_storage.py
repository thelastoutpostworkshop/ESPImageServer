"""Exercise real host paths and backend lifespans in fresh Python processes."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("layout", ["native-defaults", "xdg-overrides"])
def test_native_storage_survives_process_restart(tmp_path, layout):
    if layout == "xdg-overrides" and sys.platform != "linux":
        pytest.skip("XDG overrides apply to Linux")
    project = Path(__file__).resolve().parents[1]
    installation = tmp_path / "Installation lecture seule é"
    shutil.copytree(project / "src", installation / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    storage = tmp_path / "User storage 日本語"
    storage.mkdir()
    helper = project / "tests" / "helpers" / "native_storage_probe.py"
    env = dict(os.environ)
    for key in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "ESP_IMAGE_MODEL_CACHE", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        env.pop(key, None)
    env.update(PYTHONPATH=str(installation / "src"), PYTHONDONTWRITEBYTECODE="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ESP_IMAGE_OPEN_BROWSER="0")
    # Keep Python/native temporary files in the same isolated writable tree.
    temporary = storage / "temporary"
    temporary.mkdir()
    for key in ("TMP", "TEMP", "TMPDIR"):
        env[key] = str(temporary)
    if sys.platform == "win32":
        env["LOCALAPPDATA"] = str(storage / "Local AppData é")
    if layout == "xdg-overrides":
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            env[key] = str(storage / f"Custom {key} é")

    def snapshot():
        return {str(file.relative_to(installation)): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in installation.rglob("*") if file.is_file()}

    before = snapshot()
    entries = list(installation.rglob("*")) + [installation]
    try:
        if os.name == "posix":
            for entry in entries:
                entry.chmod(0o555 if entry.is_dir() else 0o444)
            # Fail rather than claim read-only coverage when run as a privileged user.
            with pytest.raises(PermissionError):
                (installation / "write-probe").write_text("must fail")
        for phase in ("save", "restart"):
            result = subprocess.run(
                [sys.executable, "-B", str(helper), str(storage), phase, layout],
                cwd=installation, env=env, capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert f"PASS: {phase}" in result.stdout
        assert snapshot() == before, "Application must not modify the installation"
    finally:
        if os.name == "posix":
            for entry in entries:
                entry.chmod(0o755 if entry.is_dir() else 0o644)
