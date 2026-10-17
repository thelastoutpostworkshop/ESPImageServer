"""Issue reports expose useful server details without copying private state."""

import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from esp_image_server import support_report
from esp_image_server.app import create_app
from esp_image_server.config import Settings


@pytest.fixture
def environment(monkeypatch):
    values = {
        "system": "Windows", "release": "11", "version": "10.0.26100",
        "machine": "AMD64", "python_version": "3.12.10",
    }
    for function, value in values.items():
        monkeypatch.setattr(support_report.platform, function, lambda value=value: value)
    monkeypatch.setattr(support_report.metadata, "version", lambda package: f"1.2.3+{package}")
    properties = SimpleNamespace(name="NVIDIA Test GPU", total_memory=12 * 1024 ** 3)
    cuda = SimpleNamespace(is_available=lambda: True, get_device_properties=lambda index: properties)
    torch = SimpleNamespace(version=SimpleNamespace(cuda="12.8"), cuda=cuda)
    monkeypatch.setattr(support_report.importlib, "import_module", lambda name: torch)
    return torch


def test_report_allowlists_useful_server_environment(environment):
    # Arbitrary module attributes must never become report fields.
    environment.private_path = r"C:\Users\Private\models"
    environment.password = "a private credential"
    report = support_report.create_support_report(app_version="1.2.3", device="cuda")
    assert report == {
        "app_version": "1.2.3",
        "system": {
            "os": "Windows", "release": "11", "version": "10.0.26100",
            "architecture": "AMD64", "python": "3.12.10",
        },
        "generation": {
            "device": "cuda", "cuda_available": True, "cuda_version": "12.8",
            "gpu_name": "NVIDIA Test GPU", "gpu_memory_bytes": 12 * 1024 ** 3,
        },
        "packages": {
            "torch": "1.2.3+torch", "diffusers": "1.2.3+diffusers",
            "transformers": "1.2.3+transformers", "accelerate": "1.2.3+accelerate",
            "fastapi": "1.2.3+fastapi", "imageio_ffmpeg": "1.2.3+imageio-ffmpeg",
        },
        "logs": [],
    }


@pytest.mark.parametrize("exception", [ImportError, RuntimeError, OSError])
def test_missing_or_broken_torch_keeps_other_environment_details(environment, monkeypatch, exception):
    def broken_import(name):
        raise exception("private installation details must not be serialized")
    monkeypatch.setattr(support_report.importlib, "import_module", broken_import)
    report = support_report.create_support_report(app_version="1.2.3", device="cpu")
    assert report["system"]["os"] == "Windows"
    assert report["packages"]["fastapi"] == "1.2.3+fastapi"
    assert report["generation"] == {
        "device": "cpu", "cuda_available": False, "cuda_version": None,
        "gpu_name": None, "gpu_memory_bytes": None,
    }
    assert "private installation" not in str(report)


def test_failed_package_platform_and_gpu_queries_have_bounded_fallbacks(environment, monkeypatch):
    def unavailable(*args):
        raise OSError("C:\\Users\\Private\\broken-file")
    monkeypatch.setattr(support_report.platform, "version", unavailable)
    monkeypatch.setattr(support_report.metadata, "version", unavailable)
    environment.cuda.get_device_properties = unavailable
    report = support_report.create_support_report(app_version="1.2.3", device="cuda")
    assert report["system"]["version"] == "Unknown"
    assert report["system"]["os"] == "Windows"
    assert set(report["packages"].values()) == {None}
    assert report["generation"] == {
        "device": "cuda", "cuda_available": True, "cuda_version": "12.8",
        "gpu_name": None, "gpu_memory_bytes": None,
    }
    assert "Private" not in str(report)


def test_failed_cuda_availability_query_keeps_the_runtime_version(environment):
    def unavailable():
        raise RuntimeError("driver query failed")
    environment.cuda.is_available = unavailable
    report = support_report.create_support_report(app_version="1.2.3", device="cpu")
    assert report["generation"]["cuda_available"] is False
    assert report["generation"]["cuda_version"] == "12.8"
    assert report["generation"]["gpu_name"] is None


def test_default_report_does_not_inspect_logs(environment):
    class UnreadableLogs:
        def __iter__(self):
            raise AssertionError("Default report must not inspect log contents")
    report = support_report.create_support_report(
        app_version="1.2.3", device="cuda", diagnostic_entries=UnreadableLogs(), console_lines=UnreadableLogs(),
    )
    assert report["logs"] == []


@pytest.mark.parametrize("entry,secrets", [
    ('Network setup {"ssid": "My private network", "password": "spaces and \\\"quotes\\\""}', ["My private network", "spaces and"]),
    ("Wi-Fi password = ('a long\nmultiline private secret')", ["multiline private secret", "a long"]),
    ("'Wi-Fi SSID': 'Private workshop'", ["Private workshop"]),
    ('"api key" = "private key with spaces"', ["private key with spaces"]),
    ('HF_TOKEN = "private token with spaces"', ["private token with spaces"]),
    ('HUGGING_FACE_HUB_TOKEN = "another private token"', ["another private token"]),
    ('user_name = "private person"', ["private person"]),
    ('pa\x1b[31mssword = "private colored secret"', ["private colored secret"]),
    ("Authorization: Bearer private.authorization.value", ["private.authorization.value"]),
    ("Request used Bearer private.bearer.value", ["private.bearer.value"]),
    ("Using hf_private123456 and sk-private123456 and github_pat_private123456", ["hf_private123456", "sk-private123456", "github_pat_private123456"]),
    ('Cannot open "C:\\Users\\PrivatePerson\\My images\\photo.jpg"', ["PrivatePerson", "photo.jpg"]),
    ('Cannot open "\\\\PrivateHost\\PrivateShare\\My images\\photo.jpg"', ["PrivateHost", "PrivateShare", "photo.jpg"]),
    ('Cannot open "//PrivateHost/PrivateShare/My images/photo.jpg"', ["PrivateHost", "PrivateShare", "photo.jpg"]),
    ('Cannot open "/home/privateperson/My images/photo.jpg"', ["privateperson", "photo.jpg"]),
    ("Connected to 192.168.25.123:8000", ["192.168.25.123"]),
    ("Connected to http://privatehost.local:8000/latest.jpg", ["privatehost.local", "latest.jpg"]),
    ("Connected to private-machine.local:8000", ["private-machine.local"]),
    ("Connected to [2001:db8::1234]:8000", ["2001:db8::1234"]),
    ("Connected to fe80::1234%private-interface", ["fe80::1234", "private-interface"]),
    ("Device aa:bb:cc:dd:ee:ff hardware aabbccddeeff", ["aa:bb:cc:dd:ee:ff", "aabbccddeeff"]),
    ('{"device_id": "private-device-identifier"}', ["private-device-identifier"]),
    ("Serial number = PRIVATE123456", ["PRIVATE123456"]),
    ("Operation 12345678-abcd-1234-abcd-123456789abc failed", ["12345678-abcd-1234-abcd-123456789abc"]),
    ("Active display announced: Private bedroom display (480x272)", ["Private bedroom display"]),
])
def test_optional_log_redaction_covers_private_values(entry, secrets):
    output = "\n".join(support_report.sanitize_report_log(entry))
    assert output
    for secret in secrets:
        assert secret not in output


@pytest.mark.parametrize("entry", [
    'Prompt: a very private painting',
    '{"negative_prompt": "private excluded subject"}',
    'Generation failed\nnegativePrompt = private excluded subject\nprivate continuation',
])
def test_prompt_bearing_entries_are_entirely_omitted(entry):
    assert support_report.sanitize_report_log(entry) == []


def test_logs_preserve_useful_errors_and_bound_recent_physical_lines():
    assert support_report.sanitize_report_log("2026-10-17 12:34:56 ERROR: CUDA out of memory") == [
        "2026-10-17 12:34:56 ERROR: CUDA out of memory",
    ]
    logs = support_report.report_logs([], [f"Event {index}" for index in range(75)])
    assert logs == [f"Event {index}" for index in range(25, 75)]
    assert len(support_report.report_logs([], ["\n".join(f"Traceback {index}" for index in range(75))])) == 50
    assert len(support_report.sanitize_report_log("x" * 2_000)[0]) == 1_000
    assert support_report.report_logs([{"message": "newest"}, {"message": "older"}], []) == ["older", "newest"]


class _ManagementGenerator:
    device = "cpu"
    ready = False

    def generate(self, *args, **kwargs):
        raise AssertionError("Report must not generate images")

    def load(self):
        raise AssertionError("Report must not load a model")


def test_report_endpoint_defaults_to_no_logs_and_explicit_logs_are_sanitized(environment, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    app = create_app(Settings(), _ManagementGenerator(), enable_mdns=False)
    app.version = "9.8.7"
    with TestClient(app) as client:
        app.state.diagnostics.clear()
        app.state.console_output.clear()
        for message in (
            "CUDA driver check failed", 'password = "private credential with spaces"',
            "Prompt: private painting", 'Cannot open "C:\\Users\\PrivatePerson\\file.jpg"',
        ):
            record = logging.LogRecord("support-test", logging.ERROR, "", 0, message, (), None)
            app.state.diagnostics.emit(record)
            app.state.console_output.emit(record)
        default = client.get("/diagnostics/report")
        assert default.status_code == 200
        assert default.headers["cache-control"] == "no-store"
        assert default.json()["app_version"] == "9.8.7"
        assert default.json()["generation"]["device"] == "cpu"
        assert default.json()["logs"] == []
        explicit = client.get("/diagnostics/report?include_logs=true")
        assert explicit.status_code == 200
        assert any("CUDA driver check failed" in line for line in explicit.json()["logs"])
        output = str(explicit.json())
        for value in ("private credential", "private painting", "PrivatePerson", "file.jpg"):
            assert value not in output
        # Existing raw diagnostic APIs retain their previous behavior.
        raw = client.get("/diagnostics").json()
        assert any("private painting" in entry["message"] for entry in raw)
        assert client.get("/diagnostics/report?include_logs=invalid").status_code == 422
