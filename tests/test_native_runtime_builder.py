import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tarfile

import pytest

builder = runpy.run_path(str(Path(__file__).resolve().parents[1] / "installer/build-native-runtime.py"))


@pytest.mark.parametrize("target", ["darwin-arm64", "linux-arm64", "win32-x64"])
def test_cuda_build_rejects_unsupported_targets(target):
    with pytest.raises(ValueError, match="Linux x64"):
        builder["dependency_arguments"](target, "cuda")


def test_cuda_uses_project_dependencies_and_linux_constraints():
    arguments = builder["dependency_arguments"]("linux-x64", "cuda")
    assert "https://download.pytorch.org/whl/cu128" in arguments
    assert any(value.endswith("constraints-linux-cuda.txt") for value in arguments)
    assert "torch" in arguments
    assert any(value.startswith("diffusers") for value in arguments)
    assert not any(value.endswith("requirements-management.txt") for value in arguments)


def test_management_dependencies_remain_separate():
    arguments = builder["dependency_arguments"]("darwin-arm64", "management")
    assert len(arguments) == 2
    assert arguments[1].endswith("requirements-management.txt")


def archive_with(tmp_path, name, link=None):
    archive = tmp_path / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        entry = tarfile.TarInfo(name)
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = link
            output.addfile(entry)
        else:
            entry.size = 4
            output.addfile(entry, io.BytesIO(b"test"))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_runtime_archive_requires_matching_checksum(tmp_path):
    archive, _ = archive_with(tmp_path, "python/bin/python3")
    with pytest.raises(ValueError, match="checksum"):
        builder["extract_python"](archive, tmp_path / "output", "0" * 64)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("name, link", [("../outside", None), ("python/../../outside", None),
                                      ("python/bin/python", "../../../outside")])
def test_runtime_archive_rejects_escaping_entries(tmp_path, name, link):
    archive, digest = archive_with(tmp_path, name, link)
    with pytest.raises((ValueError, tarfile.FilterError)):
        builder["extract_python"](archive, tmp_path / "output", digest)
    assert not (tmp_path / "outside").exists()


def test_runtime_archive_extracts_expected_layout(tmp_path):
    archive, digest = archive_with(tmp_path, "python/bin/python3")
    builder["extract_python"](archive, tmp_path / "output", digest)
    assert (tmp_path / "output/python/bin/python3").read_bytes() == b"test"


def test_build_environment_ignores_python_and_pip_overrides_without_mutating_parent():
    environment = {
        "PYTHONHOME": "unrelated Python", "PythonPath": "unrelated packages",
        "PYTHONUSERBASE": "user library", "PYTHONOPTIMIZE": "2",
        "PIP_TARGET": "other installation", "pip_index_url": "https://wrong.invalid",
        "PIP_CONFIG_FILE": "custom.ini", "VIRTUAL_ENV": "other environment",
        "PATH": "normal path", "HTTPS_PROXY": "https://proxy.invalid",
        "SSL_CERT_FILE": "corporate.pem", "ESP_IMAGE_MODEL_CACHE": "my models",
    }
    original = environment.copy()
    actual = builder["isolated_build_environment"](environment)
    assert environment == original
    assert actual == {
        "PATH": "normal path", "HTTPS_PROXY": "https://proxy.invalid",
        "SSL_CERT_FILE": "corporate.pem", "ESP_IMAGE_MODEL_CACHE": "my models",
        "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }


def prepare_build_fixture(tmp_path, monkeypatch, target, *, missing_interpreter=False):
    """Use an in-memory archive and fake pip; never download or execute Python."""
    windows = target == "win32-x64"
    site = "Lib/site-packages" if windows else "lib/python3.12/site-packages"
    members = {
        f"python/{site}/pip/__init__.py": b"# pip fixture\n",
        "python/LICENSE.txt": b"Python license fixture\n",
        "python/licenses/OpenSSL.txt": b"Dependency notice fixture\n",
    }
    if not missing_interpreter:
        members.update({"python/python.exe": b"Not executable"} if windows else {
            "python/bin/python3": b"Not executable", "python/bin/python": b"Not executable",
        })
    contents = io.BytesIO()
    with tarfile.open(fileobj=contents, mode="w:gz") as package:
        for name, data in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            package.addfile(entry, io.BytesIO(data))
    archive = contents.getvalue()
    project = tmp_path / "source project"
    installer = project / "installer"
    installer.mkdir(parents=True)
    source = {"url": "https://fixture.invalid/python.tar.gz", "sha256": hashlib.sha256(archive).hexdigest()}
    (installer / "native-python.json").write_text(json.dumps({
        "version": "3.12.14", "release": "20260901", "targets": {target: source},
    }))
    for name in ("requirements-management.txt", "linux-generation-setup.py", "constraints-linux-cuda.txt", "constraints-cuda.txt"):
        (installer / name).write_text("# fixture\n")
    (project / "frontend/dist").mkdir(parents=True)
    (project / "frontend/dist/index.html").write_text("fixture web")
    (project / "src/esp_image_server").mkdir(parents=True)
    (project / "src/esp_image_server/__init__.py").write_text("# fixture server\n")
    (project / "LICENSE").write_text("Application license fixture\n")
    (project / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\ndependencies = ["fastapi"]\n')
    build_globals = builder["build"].__globals__
    monkeypatch.setitem(build_globals, "PROJECT", project)
    monkeypatch.setitem(build_globals, "host_target", lambda: target)
    calls = []

    def download(url, *, timeout):
        assert url == source["url"]
        assert timeout == 120
        return io.BytesIO(archive)

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))

    def check_output(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return "fastapi==0.141.1\n"

    monkeypatch.setattr(build_globals["urllib"].request, "urlopen", download)
    monkeypatch.setattr(build_globals["subprocess"], "run", run)
    monkeypatch.setattr(build_globals["subprocess"], "check_output", check_output)
    return project, source, site, calls


@pytest.mark.parametrize("target", ["win32-x64", "linux-x64", "darwin-arm64"])
def test_native_bundle_uses_private_interpreter_and_relocatable_source_path(tmp_path, monkeypatch, target):
    project, source, site, calls = prepare_build_fixture(tmp_path, monkeypatch, target)
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "conflicting Python"))
    monkeypatch.setenv("PIP_TARGET", str(tmp_path / "external packages"))
    output = tmp_path / "Output with spaces é 日本語"
    builder["build"](output)

    interpreter = ".venv/python.exe" if target == "win32-x64" else ".venv/bin/python3"
    assert (output / interpreter).is_file()
    assert (output / ".venv/LICENSE.txt").read_text() == "Python license fixture\n"
    assert (output / ".venv/licenses/OpenSSL.txt").is_file()
    assert (output / "LICENSE").is_file()
    source_link = output / ".venv" / site / "esp-image-server.pth"
    assert (source_link.parent / source_link.read_text().strip()).resolve() == (output / "src").resolve()
    assert (output / "src/esp_image_server/__init__.py").is_file()
    manifest = json.loads((output / "runtime-manifest.json").read_text())
    assert manifest == {
        "target": target, "mode": "management", "python": "3.12.14",
        "python_source": source, "app_version": "1.2.3",
    }
    assert len(calls) == 3
    for arguments, options in calls:
        assert Path(arguments[0]).parts[-len(Path(interpreter).parts):] == Path(interpreter).parts
        assert arguments[1:4] == ["-I", "-m", "pip"]
        assert "PYTHONHOME" not in options["env"]
        assert "PIP_TARGET" not in options["env"]
        assert options["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert calls[0][0][4:7] == ["install", "--only-binary=:all:", "--no-cache-dir"]
    assert calls[1][0][4:] == ["check"]
    assert calls[2][0][4:] == ["freeze", "--all"]
    assert (output / "setup").exists() == (target == "linux-x64")
    assert not (tmp_path / "external packages").exists()


def test_failed_dependency_install_does_not_publish_partial_windows_runtime(tmp_path, monkeypatch):
    prepare_build_fixture(tmp_path, monkeypatch, "win32-x64")

    def fail(arguments, **kwargs):
        raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(builder["build"].__globals__["subprocess"], "run", fail)
    output = tmp_path / "unpublished runtime"
    with pytest.raises(subprocess.CalledProcessError):
        builder["build"](output)
    assert not output.exists()
    assert not list(tmp_path.glob("esp-native-build-*"))


def test_builder_never_replaces_an_existing_runtime(tmp_path, monkeypatch):
    prepare_build_fixture(tmp_path, monkeypatch, "win32-x64")
    output = tmp_path / "existing runtime"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("installed runtime")
    with pytest.raises(ValueError, match="Output already exists"):
        builder["build"](output)
    assert marker.read_text() == "installed runtime"


def test_archive_with_no_expected_interpreter_fails_before_pip(tmp_path, monkeypatch):
    _, _, _, calls = prepare_build_fixture(tmp_path, monkeypatch, "win32-x64", missing_interpreter=True)
    output = tmp_path / "missing interpreter"
    with pytest.raises(ValueError, match="lacks its interpreter"):
        builder["build"](output)
    assert not calls
    assert not output.exists()
