import sys

from fastapi.testclient import TestClient

from esp_image_server.app import create_app
from esp_image_server.config import Settings


def test_management_starts_without_torch_and_keeps_generation_disabled(monkeypatch, tmp_path):
    # Exercise the real generator's detection, not FakeGenerator's device label.
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = create_app(Settings(), enable_mdns=False)
    with TestClient(app) as client:
        assert client.get("/health").json()["device"] == "cpu"
        assert client.get("/app-settings").status_code == 200
        assert client.get("/displays").status_code == 200
        assert client.get("/models").status_code == 200
        response = client.post("/models/Lykon/dreamshaper-8/select")
        assert response.status_code == 400
        assert "NVIDIA" in response.json()["detail"]
