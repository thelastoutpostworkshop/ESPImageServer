"""Run with the relocated bundle's Python, never the build host's interpreter."""

import importlib.util
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

bundle = Path(sys.argv[1]).resolve()
assert Path(sys.prefix).resolve() == bundle / ".venv"
assert Path(sys.base_prefix).resolve() == bundle / ".venv"
assert importlib.util.find_spec("torch") is None
assert importlib.util.find_spec("diffusers") is None
import esp_image_server
assert Path(esp_image_server.__file__).resolve().is_relative_to(bundle)
from esp_image_server.version import APP_VERSION
assert APP_VERSION == json.loads((bundle / "runtime-manifest.json").read_text())["app_version"]
from esp_image_server.video_library import bundled_ffmpeg_executable
assert Path(bundled_ffmpeg_executable()).resolve().is_relative_to(bundle)

with tempfile.TemporaryDirectory(prefix="esp-bundle-check-") as temporary:
    storage = Path(temporary)
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "IMAGEIO_FFMPEG_EXE"):
        env.pop(key, None)
    env.update(PATH="", PYTHONDONTWRITEBYTECODE="1", ESP_IMAGE_OPEN_BROWSER="0",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for key in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "ESP_IMAGE_MODEL_CACHE"):
        env[key] = str(storage / key)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code = """
import sys
from pathlib import Path
Path.home = classmethod(lambda cls: Path(sys.argv[1]) / 'home')
import numpy as np
import imageio.v2 as imageio
output = Path(sys.argv[1]) / 'fixture.mp4'
with imageio.get_writer(output, fps=4) as writer:
    for value in (0, 80, 160, 255):
        writer.append_data(np.full((32, 32, 3), value, dtype=np.uint8))
with imageio.get_reader(output) as reader:
    assert reader.count_frames() == 4
from esp_image_server.app import create_app
import uvicorn
uvicorn.run(create_app(enable_mdns=False), host='127.0.0.1', port=int(sys.argv[2]))
"""
    log = storage / "server.log"
    with log.open("w") as output:
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(storage), str(port)],
                                 env=env, cwd=storage, stdout=output, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        assert json.load(response)["device"] == "cpu"
                    break
                except OSError:
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(log.read_text())
                    time.sleep(0.2)
            for endpoint in ("/", "/app-settings", "/models", "/displays"):
                with urllib.request.urlopen(base + endpoint, timeout=5) as response:
                    assert response.status == 200
                    if endpoint == "/":
                        page = response.read().decode()
            assets = re.findall(r'(?:src|href)="(/ui/[^" ]+)"', page)
            assert assets, "The bundled frontend must reference built assets"
            for asset in assets:
                with urllib.request.urlopen(base + asset, timeout=5) as response:
                    assert response.status == 200
            request = urllib.request.Request(base + "/models/Lykon/dreamshaper-8/select", method="POST")
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                assert error.code == 400
                assert "NVIDIA" in json.load(error)["detail"]
            else:
                raise AssertionError("Management runtime must reject generation model loading")
            print("PASS: relocated standalone Python, bundled FFmpeg, web UI, management API; no system Python or GPU stack")
        finally:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            print(log.read_text())
