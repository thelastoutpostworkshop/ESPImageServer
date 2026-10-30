"""Validate runtime metadata and requirements without importing GPU packages."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("windows_runtime_setup", PROJECT / "installer/runtime-setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def runtime_fixture(tmp_path, monkeypatch):
    prefix = tmp_path / "Private runtime é"
    prefix.mkdir()
    manifest = {"target": "win32-x64", "mode": "management", "python": "3.12.14"}
    (prefix / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(setup.platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(setup.platform, "python_version", lambda: "3.12.14")
    monkeypatch.setattr(setup.sysconfig, "get_platform", lambda: "win-amd64")
    monkeypatch.setattr(setup.sys, "prefix", str(prefix))
    monkeypatch.setattr(setup.sys, "executable", str(prefix / "python.exe"))
    monkeypatch.setattr(setup.sys, "version_info", (3, 12, 14))
    monkeypatch.setattr(setup.importlib, "import_module", lambda name: SimpleNamespace())
    return prefix, manifest


def test_validation_accepts_exact_bundled_interpreter_and_manifest(tmp_path, monkeypatch):
    prefix, manifest = runtime_fixture(tmp_path, monkeypatch)
    assert setup.validate_runtime(prefix) == manifest


@pytest.mark.parametrize("field,value", [("target", "linux-x64"), ("mode", "cuda"), ("python", "3.12.13")])
def test_validation_rejects_wrong_runtime_manifest(tmp_path, monkeypatch, field, value):
    prefix, manifest = runtime_fixture(tmp_path, monkeypatch)
    manifest[field] = value
    (prefix / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        setup.validate_runtime(prefix)


def test_validation_rejects_a_system_interpreter_even_with_matching_version(tmp_path, monkeypatch):
    prefix, _ = runtime_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "system/python.exe"))
    with pytest.raises(ValueError, match="bundled CPython"):
        setup.validate_runtime(prefix)


def test_verification_rejects_server_imports_from_outside_the_installed_source(tmp_path, monkeypatch):
    prefix, _ = runtime_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(setup.importlib, "import_module", lambda name: SimpleNamespace(__file__="unexpected/version.py"))
    with pytest.raises(ValueError, match="installed ESPImageServer source"):
        setup.verify_dependencies(prefix)


def test_requirements_come_from_shipped_application_without_editable_paths(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi>=0.110", "torchvision>=0.20"]\n')
    destination = tmp_path / "requirements.txt"
    setup.write_requirements(tmp_path, destination)
    assert destination.read_text() == "setuptools\nfastapi>=0.110\ntorchvision>=0.20\n"


@pytest.mark.parametrize("requirement", ["--target=outside", "fastapi\n--target=outside"])
def test_requirements_reject_command_options_and_multiline_entries(tmp_path, requirement):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = [' + json.dumps(requirement) + ']\n')
    with pytest.raises(ValueError, match="generation dependencies"):
        setup.write_requirements(tmp_path, tmp_path / "requirements.txt")


@pytest.mark.parametrize("bundled", [False, True])
def test_ffmpeg_verification_requires_the_runtime_bundled_executable(tmp_path, monkeypatch, bundled):
    prefix, _ = runtime_fixture(tmp_path, monkeypatch)
    executable = (prefix if bundled else tmp_path) / "ffmpeg.exe"
    executable.write_bytes(b"fixture, never executed")
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "inherited-system-ffmpeg")
    def import_fixture(name):
        if name == "imageio_ffmpeg":
            return SimpleNamespace(get_ffmpeg_exe=lambda: str(executable))
        if name == "esp_image_server.version":
            return SimpleNamespace(__file__=str(prefix.parent / "src/esp_image_server/version.py"))
        return SimpleNamespace()
    monkeypatch.setattr(setup.importlib, "import_module", import_fixture)
    if bundled:
        setup.verify_dependencies(prefix)
    else:
        with pytest.raises(ValueError, match="bundled FFmpeg"):
            setup.verify_dependencies(prefix)
