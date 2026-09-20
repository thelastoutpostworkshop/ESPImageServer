import hashlib
import io
from pathlib import Path
import runpy
import tarfile

import pytest

builder = runpy.run_path(str(Path(__file__).resolve().parents[1] / "installer/build-native-runtime.py"))


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
