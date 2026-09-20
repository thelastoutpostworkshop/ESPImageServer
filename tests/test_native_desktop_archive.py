import hashlib
import json
from pathlib import Path
import runpy
import tarfile

import pytest

archive = runpy.run_path(str(Path(__file__).resolve().parents[1] / "installer/archive-native-desktop.py"))


def bundle(tmp_path, target="linux-x64", mode="management"):
    root = tmp_path / "bundle é"
    resources = root / ("resources" if target == "linux-x64" else "ESPImageServer.app/Contents/Resources")
    backend = resources / "backend"
    backend.mkdir(parents=True)
    (backend / "runtime-manifest.json").write_text(json.dumps({
        "target": target, "mode": mode, "app_version": "1.2.3"}), encoding="utf-8")
    (resources / "sample").write_bytes(b"bundled payload")
    return root


@pytest.mark.parametrize("target,mode", [("linux-x64", "management"), ("linux-x64", "cuda"), ("darwin-arm64", "management")])
def test_distribution_roundtrip_and_checksum(tmp_path, target, mode):
    root = bundle(tmp_path, target, mode)
    result = archive["build"](root, tmp_path / "out", target, mode, "1.2.3")
    assert result.name == f"ESPImageServer-1.2.3-{target}-{mode}.tar.gz"
    assert result.with_name(result.name + ".sha256").read_text() == f"{hashlib.sha256(result.read_bytes()).hexdigest()}  {result.name}\n"
    extracted = tmp_path / "extracted"
    with tarfile.open(result) as packed:
        packed.extractall(extracted, filter="data")
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == sorted(p.relative_to(extracted) for p in extracted.rglob("*"))
    archive["verify"](result, root)
    with pytest.raises(ValueError, match="already exists"):
        archive["build"](root, tmp_path / "out", target, mode, "1.2.3")


def test_rejects_wrong_version_and_output_inside_bundle(tmp_path):
    root = bundle(tmp_path)
    with pytest.raises(ValueError, match="manifest"):
        archive["build"](root, tmp_path / "out", "linux-x64", "management", "2.0.0")
    with pytest.raises(ValueError, match="outside"):
        archive["build"](root, root / "out", "linux-x64", "management", "1.2.3")


def test_verification_detects_modified_contents(tmp_path):
    root = bundle(tmp_path)
    result = archive["build"](root, tmp_path / "out", "linux-x64", "management", "1.2.3")
    (root / "resources/sample").write_bytes(b"changed payload")
    with pytest.raises(ValueError, match="Content mismatch"):
        archive["verify"](result, root)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Native POSIX permissions and symlinks")
def test_preserves_executability_and_symlinks(tmp_path):
    root = bundle(tmp_path)
    executable = root / "resources/sample"
    executable.chmod(0o755)
    (root / "resources/link").symlink_to("sample")
    result = archive["build"](root, tmp_path / "out", "linux-x64", "management", "1.2.3")
    extracted = tmp_path / "extracted"
    with tarfile.open(result) as packed:
        packed.extractall(extracted, filter="data")
    assert (extracted / "resources/sample").stat().st_mode & 0o777 == 0o755
    assert (extracted / "resources/link").readlink() == Path("sample")
