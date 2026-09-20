"""Build a relocatable management or Linux CUDA backend on its native runner."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]


def host_target():
    architecture = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    return f"{sys.platform}-{architecture}"


def extract_python(archive, destination, expected_sha256):
    with archive.open("rb") as source:
        actual_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("Standalone Python checksum mismatch")
    with tarfile.open(archive) as package:
        # Python's data filter rejects traversal, escaping links, and device files.
        members = package.getmembers()
        if not members or any(not Path(member.name).parts or Path(member.name).parts[0] != "python" for member in members):
            raise ValueError("Unexpected standalone Python archive layout")
        package.extractall(destination, members=members, filter="data")


def dependency_arguments(target, mode):
    if mode == "management":
        return ["-r", str(PROJECT / "installer/requirements-management.txt")]
    if mode != "cuda" or target != "linux-x64":
        raise ValueError("CUDA bundles are supported only on Linux x64")
    dependencies = tomllib.loads((PROJECT / "pyproject.toml").read_text())["project"]["dependencies"]
    return ["--constraint", str(PROJECT / "installer/constraints-linux-cuda.txt"),
            "--extra-index-url", "https://download.pytorch.org/whl/cu128",
            "torch", "setuptools", *dependencies]


def build(destination, mode="management"):
    manifest = json.loads((PROJECT / "installer/native-python.json").read_text())
    target = host_target()
    if target not in manifest["targets"]:
        raise ValueError(f"Build on Linux x64 or macOS ARM64, not {target}")
    dependencies = dependency_arguments(target, mode)
    if destination.exists():
        raise ValueError(f"Output already exists; choose a new directory: {destination}")
    web = PROJECT / "frontend/dist"
    if not (web / "index.html").is_file():
        raise ValueError("Build the frontend first: npm --prefix frontend run build")
    source = manifest["targets"][target]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="esp-native-build-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "python.tar.gz"
        with urllib.request.urlopen(source["url"], timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        extract_python(archive, staging, source["sha256"])
        bundle = staging / "backend"
        bundle.mkdir()
        (staging / "python").rename(bundle / ".venv")
        python = bundle / ".venv/bin/python3"
        # Use the full standalone prefix at the existing runtime path, not a venv.
        launcher = bundle / ".venv/bin/python"
        if not launcher.exists():
            launcher.symlink_to("python3")
        subprocess.run([str(python), "-I", "-m", "pip", "install", "--only-binary=:all:",
                        "--no-cache-dir", *dependencies], check=True)
        subprocess.run([str(python), "-I", "-m", "pip", "check"], check=True)
        shutil.copytree(PROJECT / "src/esp_image_server", bundle / "src/esp_image_server",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(web, bundle / "web")
        shutil.copy2(PROJECT / "LICENSE", bundle / "LICENSE")
        shutil.copy2(PROJECT / "pyproject.toml", bundle / "pyproject.toml")
        site = bundle / ".venv/lib/python3.12/site-packages"
        (site / "esp-image-server.pth").write_text("../../../../src\n", encoding="utf-8")
        resolved = subprocess.check_output([str(python), "-I", "-m", "pip", "freeze", "--all"], text=True)
        (bundle / "requirements-resolved.txt").write_text(resolved, encoding="utf-8")
        (bundle / "runtime-manifest.json").write_text(json.dumps({
            "target": target, "mode": mode, "python": manifest["version"],
            "python_source": source, "app_version": tomllib.loads(
                (PROJECT / "pyproject.toml").read_text())["project"]["version"],
        }, indent=2) + "\n", encoding="utf-8")
        bundle.rename(destination)
    print(f"{mode} backend prepared: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("management", "cuda"), default="management")
    args = parser.parse_args()
    build(args.output.resolve(), args.mode)
