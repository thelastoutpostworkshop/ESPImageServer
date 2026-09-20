import hashlib
import io
from pathlib import Path
import runpy
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
