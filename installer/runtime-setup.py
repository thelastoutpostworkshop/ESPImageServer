"""Validate the private Windows runtime and prepare generation dependencies."""

import argparse
import importlib
import json
from pathlib import Path
import platform
import sys
import sysconfig
import tomllib


def validate_runtime(prefix: Path) -> dict:
    prefix = prefix.resolve()
    manifest = json.loads((prefix / "runtime-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("target") != "win32-x64" or manifest.get("mode") != "management":
        raise ValueError("The bundled runtime manifest must describe Windows x64 management Python")
    expected = manifest.get("python")
    if (platform.python_implementation() != "CPython"
            or sys.version_info[:2] != (3, 12)
            or platform.python_version() != expected
            or sysconfig.get_platform() != "win-amd64"
            or Path(sys.prefix).resolve() != prefix
            or Path(sys.executable).resolve() != prefix / "python.exe"):
        raise ValueError(f"Setup requires the bundled CPython {expected} x64 interpreter at {prefix}")
    # A full standalone prefix must include pip; never fall back to system tools.
    importlib.import_module("pip")
    print(f"Validated private CPython {expected} x64 at {prefix}")
    return manifest


def write_requirements(project: Path, destination: Path) -> None:
    configuration = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = configuration["project"]["dependencies"]
    if not dependencies or any(not isinstance(value, str) or "\n" in value or "\r" in value
                               or value.startswith("-") for value in dependencies):
        raise ValueError("The application's generation dependencies are invalid")
    destination.write_text("\n".join(["setuptools", *dependencies]) + "\n", encoding="utf-8")


def verify_dependencies(prefix: Path) -> None:
    validate_runtime(prefix)
    for name in ("fastapi", "numpy", "PIL", "uvicorn", "zeroconf", "torch",
                 "torchvision", "diffusers", "transformers", "imageio",
                 "imageio_ffmpeg", "sentencepiece", "esp_image_server.version"):
        importlib.import_module(name)
    server_version = importlib.import_module("esp_image_server.version")
    expected_source = prefix.resolve().parent / "src/esp_image_server/version.py"
    if Path(server_version.__file__).resolve() != expected_source:
        raise ValueError("The private runtime did not load the installed ESPImageServer source")
    # Ignore the environment override so verification checks the dependency's
    # own bundled executable rather than a system ffmpeg installation.
    import os
    os.environ.pop("IMAGEIO_FFMPEG_EXE", None)
    ffmpeg = importlib.import_module("imageio_ffmpeg")
    executable = Path(ffmpeg.get_ffmpeg_exe()).resolve()
    if not executable.is_file() or not executable.is_relative_to(prefix.resolve()):
        raise ValueError("The video dependency did not provide its bundled FFmpeg executable")
    print(f"Runtime imports and bundled FFmpeg verified: {executable}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "requirements", "verify"))
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    if args.operation == "requirements":
        if args.project is None:
            parser.error("requirements needs --project")
        validate_runtime(args.runtime)
        write_requirements(args.project, args.runtime / "generation-requirements.txt")
    elif args.operation == "verify":
        verify_dependencies(args.runtime)
    else:
        validate_runtime(args.runtime)


if __name__ == "__main__":
    main()
