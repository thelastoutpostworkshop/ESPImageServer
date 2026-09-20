"""Isolate writable state before collecting tests that import the global app."""

from pathlib import Path
import tempfile

import pytest


def pytest_configure(config):
    directory = tempfile.TemporaryDirectory(prefix="esp-tests-")
    root = Path(directory.name)
    patch = pytest.MonkeyPatch()
    patch.setattr(Path, "home", lambda: root / "home")
    for variable in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                     "ESP_IMAGE_MODEL_CACHE", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        patch.setenv(variable, str(root / variable))
    patch.setenv("ESP_IMAGE_OPEN_BROWSER", "0")
    patch.setenv("HF_HUB_OFFLINE", "1")
    patch.setenv("TRANSFORMERS_OFFLINE", "1")
    config._esp_test_storage = (directory, patch)


def pytest_unconfigure(config):
    storage = getattr(config, "_esp_test_storage", None)
    if storage:
        directory, patch = storage
        patch.undo()
        directory.cleanup()
