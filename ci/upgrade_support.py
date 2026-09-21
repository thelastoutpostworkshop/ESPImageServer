"""Shared upgrade fixtures: real app storage, synthetic older package metadata."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
OLD_VERSION = "0.0.1"


def set_backend_version(backend, version):
    project = backend / "pyproject.toml"
    text, count = re.subn(r'^version\s*=\s*"[^"]+"', f'version = "{version}"', project.read_text(encoding="utf-8"), count=1, flags=re.M)
    assert count == 1
    project.write_text(text, encoding="utf-8")
    manifest = backend / "runtime-manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        data["app_version"] = version
        manifest.write_text(json.dumps(data))


def storage_probe(backend, storage, phase, version):
    storage.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "ESP_IMAGE_MODEL_CACHE", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        env.pop(key, None)
    temporary = storage / "temporary"
    temporary.mkdir(exist_ok=True)
    env.update(PYTHONPATH=str(backend / "src"), PYTHONDONTWRITEBYTECODE="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ESP_IMAGE_OPEN_BROWSER="0",
               ESP_UPGRADE_EXPECTED_VERSION=version, ESP_UPGRADE_SOURCE=str(backend / "src"))
    for key in ("TMP", "TEMP", "TMPDIR"):
        env[key] = str(temporary)
    if sys.platform == "win32":
        env["LOCALAPPDATA"] = str(storage / "LocalAppData")
    subprocess.run([sys.executable, "-B", str(PROJECT / "tests/helpers/native_storage_probe.py"),
                    str(storage), phase, "native-defaults"], env=env, cwd=backend, check=True, timeout=90)


def snapshot(storage):
    return {str(p.relative_to(storage)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in storage.rglob("*") if p.is_file()}


def assert_preserved(storage, expected):
    assert snapshot(storage) == expected, "Upgrade modified or removed user data"
