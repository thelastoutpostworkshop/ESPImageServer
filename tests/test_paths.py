from pathlib import Path
from types import SimpleNamespace

import pytest

from esp_image_server import paths
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.display_registry import DisplayRegistry
from esp_image_server.display_settings import DisplaySettingsStore
from esp_image_server.image_library import ImageLibrary
from esp_image_server.model_settings import ModelSelectionStore
from esp_image_server.models import model_cache_roots
from esp_image_server.video_generator import video_model_cache_dir


@pytest.fixture
def home(tmp_path, monkeypatch):
    user_home = tmp_path / "User with spaces \u00e9"
    monkeypatch.setattr(Path, "home", lambda: user_home)
    for key in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "ESP_IMAGE_MODEL_CACHE", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        monkeypatch.delenv(key, raising=False)
    return user_home


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_platform_defaults_are_pure_and_independent_of_working_directory(home, monkeypatch, tmp_path, platform):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform=platform))
    monkeypatch.chdir(tmp_path)
    if platform == "win32":
        expected = (home / ".local" / "ESPImageServer",) * 3
        models = home / ".cache" / "ESPImageServer" / "models"
    elif platform == "darwin":
        support = home / "Library" / "Application Support" / "ESPImageServer"
        expected = (support, support, home / "Library" / "Caches" / "ESPImageServer")
        models = expected[2] / "models"
    else:
        expected = (home / ".config" / "ESPImageServer", home / ".local" / "share" / "ESPImageServer",
                    home / ".cache" / "ESPImageServer")
        models = expected[2] / "models"
    assert (paths.config_dir(), paths.data_dir(), paths.cache_dir()) == expected
    assert paths.model_cache_dir() == models
    assert video_model_cache_dir() == models
    assert model_cache_roots(None)[0] == models
    assert not home.exists()  # Resolving defaults never writes into user storage.


def test_windows_existing_locations_are_preserved(home, monkeypatch):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform="win32"))
    local = home / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "ignored"))
    root = local / "ESPImageServer"
    assert paths.config_dir() == paths.data_dir() == paths.cache_dir() == root
    assert paths.model_cache_dir() == home / ".cache" / "ESPImageServer" / "models"


def test_linux_xdg_overrides_and_invalid_relative_values(home, monkeypatch):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform="linux"))
    for variable, resolver, default in [
        ("XDG_CONFIG_HOME", paths.config_dir, home / ".config"),
        ("XDG_DATA_HOME", paths.data_dir, home / ".local" / "share"),
        ("XDG_CACHE_HOME", paths.cache_dir, home / ".cache"),
    ]:
        custom = home / variable
        monkeypatch.setenv(variable, str(custom))
        assert resolver() == custom / "ESPImageServer"
        for invalid in ("relative/path", ""):
            monkeypatch.setenv(variable, invalid)
            assert resolver() == default / "ESPImageServer"


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_explicit_paths_and_model_cache_overrides(home, monkeypatch, platform):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform=platform))
    models = home / "Models"
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(models))
    assert video_model_cache_dir() == paths.model_cache_dir() == model_cache_roots(None)[0] == models
    explicit = home / "other models"
    assert paths.model_cache_dir(explicit) == explicit
    assert model_cache_roots(explicit) == (explicit,)
    library = ImageLibrary(home / "Chosen images", home / "index.json")
    assert library.path == home / "Chosen images"
    assert library.index_path == home / "index.json"
    assert AppSettingsStore(home / "settings.json").path == home / "settings.json"
    assert not home.exists()


def test_stores_share_platform_locations_and_preserve_existing_data(home, monkeypatch):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform="linux"))
    assert AppSettingsStore().path == paths.config_dir() / "app_settings.json"
    assert DisplaySettingsStore().path == paths.config_dir() / "display_settings.json"
    assert ModelSelectionStore("default").path == paths.config_dir() / "settings.json"
    assert DisplayRegistry._default_path() == paths.data_dir() / "displays.sqlite3"
    library = ImageLibrary()
    assert library.path == paths.data_dir() / "images"
    assert library.index_path == paths.data_dir() / "image_library_index.json"
    store = AppSettingsStore()
    store.set({"image_library_location": str(home / "Custom library")})
    original = store.path.read_bytes()
    assert AppSettingsStore().get()["image_library_location"] == str(home / "Custom library")
    assert store.path.read_bytes() == original


def test_shared_huggingface_cache_overrides_remain_discoverable(home, monkeypatch):
    monkeypatch.setattr(paths, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("HF_HOME", str(home / "hf"))
    assert model_cache_roots(None)[1] == home / "hf" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(home / "hub"))
    assert model_cache_roots(None)[1] == home / "hub"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(home / "legacy hub"))
    assert model_cache_roots(None)[1] == home / "legacy hub"
