"""Writable user locations; resolving a path never creates or moves files."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _xdg_path(variable: str, fallback: Path) -> Path:
    value = os.getenv(variable)
    # XDG relative paths are invalid and must not depend on the working directory.
    return Path(value) if value and Path(value).is_absolute() else fallback


def data_dir() -> Path:
    if sys.platform == "win32":
        # Preserve the existing Windows default, including its unset-env fallback.
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ESPImageServer"
    return _xdg_path("XDG_DATA_HOME", Path.home() / ".local" / "share") / "ESPImageServer"


def config_dir() -> Path:
    if sys.platform in {"win32", "darwin"}:
        return data_dir()
    return _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config") / "ESPImageServer"


def cache_dir() -> Path:
    if sys.platform == "win32":
        return data_dir()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ESPImageServer"
    return _xdg_path("XDG_CACHE_HOME", Path.home() / ".cache") / "ESPImageServer"


def model_cache_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override
    value = os.getenv("ESP_IMAGE_MODEL_CACHE")
    if value:
        return Path(value)
    # Windows model downloads historically used a different root from app data.
    root = Path.home() / ".cache" / "ESPImageServer" if sys.platform == "win32" else cache_dir()
    return root / "models"


def image_model_cache_roots(override: Path | None = None) -> tuple[Path, ...]:
    """Include the existing shared Hugging Face cache for discovery/removal."""
    if override is not None:
        return (override,)
    hub_cache = os.getenv("HUGGINGFACE_HUB_CACHE") or os.getenv("HF_HUB_CACHE")
    hf_home = Path(os.getenv("HF_HOME", _xdg_path("XDG_CACHE_HOME", Path.home() / ".cache") / "huggingface"))
    return (model_cache_dir(), Path(hub_cache) if hub_cache else hf_home / "hub")
