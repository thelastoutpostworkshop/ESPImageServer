from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_ROOT = PROJECT_ROOT / "installer"


def read_constraints(filename: str) -> dict[str, str]:
    constraints: dict[str, str] = {}
    for line in (INSTALLER_ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", maxsplit=1)
        constraints[name.lower()] = version
    return constraints


def test_cpu_and_cuda_installers_use_compatible_tested_package_versions() -> None:
    cpu_constraints = read_constraints("constraints-cpu.txt")
    cuda_constraints = read_constraints("constraints-cuda.txt")

    platform_specific_packages = {"torch", "torchvision", "setuptools"}
    assert {
        package: version
        for package, version in cpu_constraints.items()
        if package not in platform_specific_packages
    } == {
        package: version
        for package, version in cuda_constraints.items()
        if package not in platform_specific_packages
    }
    expected_cpu_versions = {
        "torch": "2.13.0",
        "torchvision": "0.28.0",
        "diffusers": "0.39.0",
        "transformers": "4.57.6",
        "huggingface-hub": "0.36.2",
        "fastapi": "0.141.1",
        "imageio": "2.37.4",
        "imageio-ffmpeg": "0.6.0",
        "numpy": "2.5.2",
        "pip": "26.2.1",
        "setuptools": "84.0.0",
    }
    for package, version in expected_cpu_versions.items():
        assert cpu_constraints[package] == version
    assert cuda_constraints["torch"] == "2.11.0+cu128"
    assert cuda_constraints["torchvision"] == "0.26.0+cu128"
    assert cuda_constraints["setuptools"] == "81.0.0"


def test_installer_requires_python_312_instead_of_using_the_default_launcher_version() -> None:
    bootstrap = (INSTALLER_ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    installer_definition = (INSTALLER_ROOT / "ESPImageServer.iss").read_text(
        encoding="utf-8"
    )

    assert "$SupportedPythonVersion = '3.12'" in bootstrap
    assert "Python.Python.3.12" in bootstrap
    assert "return @('py')" not in bootstrap
    assert "--constraint" in bootstrap
    assert "'verify-gpu.py'" in bootstrap
    assert "CPU-only PyTorch was installed" in bootstrap
    assert "--extra-index-url" in bootstrap
    assert "pip', 'freeze', '--all" in bootstrap
    assert "Recreating the app-owned virtual environment" in bootstrap
    assert 'print(platform.python_implementation(), sys.version)' in bootstrap
    assert 'print(f"Using' not in bootstrap
    assert 'requires-python = ">=3.12,<3.13"' in pyproject
    assert 'requires = ["setuptools==84.0.0"]' in pyproject
    assert 'Source: "constraints-cpu.txt"; DestDir: "{app}"' in installer_definition
    assert 'Source: "constraints-cuda.txt"; DestDir: "{app}"' in installer_definition
    assert 'Source: "verify-gpu.py"; DestDir: "{app}"' in installer_definition
