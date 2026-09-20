"""Subprocess helper; never imported into the installed application."""

import io
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
phase, layout = sys.argv[2:]
Path.home = classmethod(lambda cls: root / "Home é")
# Prevent any installed GPU libraries from probing/loading models in this check.
sys.modules["torch"] = None
violations = []


def writable_path(value):
    if isinstance(value, int) or value is None or value == ":memory:":
        return
    target = Path(os.fsdecode(value)).resolve()
    if not target.is_relative_to(root):
        violations.append(str(target))
        raise PermissionError(f"Storage check blocked a write outside user storage: {target}")


def audit(event, args):
    if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        writable_path(args[0])
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "sqlite3.connect"}:
        writable_path(args[0])
    elif event == "os.rename":
        writable_path(args[0])
        writable_path(args[1])


sys.addaudithook(audit)

from fastapi.testclient import TestClient
from PIL import Image
from esp_image_server import paths
from esp_image_server.app import create_app
from esp_image_server.app_settings import AppSettingsStore
from esp_image_server.models import model_cache_roots
from esp_image_server.video_generator import video_model_cache_dir

home = Path.home()
if sys.platform == "win32":
    expected_config = expected_data = expected_cache = Path(os.environ["LOCALAPPDATA"]) / "ESPImageServer"
    expected_models = home / ".cache" / "ESPImageServer" / "models"
elif sys.platform == "darwin":
    expected_config = expected_data = home / "Library" / "Application Support" / "ESPImageServer"
    expected_cache = home / "Library" / "Caches" / "ESPImageServer"
    expected_models = expected_cache / "models"
else:
    expected_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "ESPImageServer"
    expected_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "ESPImageServer"
    expected_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "ESPImageServer"
    expected_models = expected_cache / "models"
assert (paths.config_dir(), paths.data_dir(), paths.cache_dir()) == (expected_config, expected_data, expected_cache)
assert paths.model_cache_dir() == video_model_cache_dir() == model_cache_roots(None)[0] == expected_models

library = root / "Créations 日本語"
app = create_app(enable_mdns=False)
with TestClient(app) as client:
    assert client.get("/health").status_code == 200
    assert app.state.app_settings_store.path == expected_config / "app_settings.json"
    assert app.state.image_library.index_path == expected_data / "image_library_index.json"
    assert app.state.mjpeg_cache.path == expected_cache / "videos" / "display-mjpeg"
    if phase == "save":
        assert app.state.image_library.path == expected_data / "images"
        response = client.put("/app-settings", json={"image_library_location": str(library),
                              "confirm_deletion": False, "video_jpeg_quality": 17})
        assert response.status_code == 200, response.text
        assert client.put("/display-settings", json={"rotation": 270}).status_code == 200
        # Save a tiny fixture through the real library; no generation or model download.
        jpeg = io.BytesIO()
        Image.new("RGB", (16, 16), "blue").save(jpeg, format="JPEG")
        app.state.image_library.save(jpeg.getvalue(), {"prompt": "Persistence é 日本語"})
        expected_models.mkdir(parents=True, exist_ok=True)
        (expected_models / "storage-probe.txt").write_text("model cache writable", encoding="utf-8")
    else:
        settings = client.get("/app-settings").json()
        assert Path(settings["image_library_location"]) == library
        assert settings["confirm_deletion"] is False
        assert settings["video_jpeg_quality"] == 17
        assert client.get("/display-settings").json()["rotation"] == 270
        records = app.state.image_library.list()
        assert len(records) == 1
        assert records[0]["metadata"]["prompt"] == "Persistence é 日本語"
        image_path = app.state.image_library.find_path(records[0]["id"])
        assert image_path.parent == library
        with Image.open(image_path) as image:
            image.load()
            assert image.size == (16, 16)
        assert (expected_models / "storage-probe.txt").read_text() == "model cache writable"
    assert AppSettingsStore().get()["video_jpeg_quality"] == 17
    assert (expected_data / "displays.sqlite3").is_file()
    assert app.state.mjpeg_cache.path.is_dir()

assert not violations, f"Writes escaped designated user storage: {violations}"
if layout == "xdg-overrides":
    assert not (home / ".config").exists()
    assert not (home / ".local").exists()
    assert not (home / ".cache").exists()
print(f"PASS: {phase} ({sys.platform}, {layout})")
