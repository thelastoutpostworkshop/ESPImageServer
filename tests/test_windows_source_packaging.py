"""Compile/extract harmless source files with the production Inno source entry.

The fixture has no application code, registry, shortcuts, uninstaller, or [Run]
section. Its only destination is pytest's temporary directory.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Inno file enumeration")


def inno_compiler():
    # tests/conftest.py redirects LOCALAPPDATA before collection. An explicit
    # compiler path also supports per-user installations outside that fixture.
    if os.environ.get("ESP_INNO_COMPILER"):
        compiler = Path(os.environ["ESP_INNO_COMPILER"])
        assert compiler.is_file(), "The explicitly selected Inno compiler is missing"
        return str(compiler)
    compiler = shutil.which("ISCC.exe")
    if compiler:
        return compiler
    for variable, prefix in (("LOCALAPPDATA", "Programs"), ("ProgramFiles(x86)", "")):
        if os.environ.get(variable):
            directory = Path(os.environ[variable]) / prefix
            standard = directory / "Inno Setup 6/ISCC.exe"
            if standard.is_file():
                return str(standard)
            candidates = sorted(directory.glob("Inno Setup*/ISCC.exe"))
            if candidates:
                return str(candidates[-1])
    if os.environ.get("ESP_REQUIRE_INNO_TEST") == "1":
        pytest.fail("Inno Setup compiler is required for the source-only fixture")
    pytest.skip("Inno Setup compiler is unavailable for the source-only fixture")


def production_source_entry():
    script = (PROJECT / "installer/ESPImageServer.iss").read_text(encoding="utf-8")
    files = script.split("[Files]", 1)[1].split("\n[", 1)[0]
    entries = [line.strip() for line in files.splitlines()
               if re.match(r'Source:\s*"\.\.\\src\\', line)]
    assert len(entries) == 1, "Select the production backend-source entry without copying its rules"
    entry = entries[0]
    # A future source-entry change must not give this harmless fixture install
    # hooks, system destinations, or executable registration flags.
    assert set(re.findall(r"(?:^|;)\s*(\w+):", entry)) <= {"Source", "DestDir", "Excludes", "Flags"}
    destination = re.search(r'DestDir:\s*"([^"]+)"', entry).group(1)
    assert destination.startswith("{app}\\src") and ".." not in destination and ":" not in destination
    flags = re.search(r"Flags:\s*([^;]+)", entry).group(1).split()
    assert set(flags) <= {"recursesubdirs", "createallsubdirs", "ignoreversion"}
    return entry


def extract_source_fixture(tmp_path, entry):
    compiler = inno_compiler()
    project = tmp_path / "source project"
    package = project / "src/esp_image_server"
    assets = {"__init__.py": b"# Harmless package fixture\n",
              "nested/module.py": b"# Harmless nested module\n",
              "static/test-page-logo.png": b"Harmless image fixture"}
    for relative, contents in assets.items():
        file = package / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(contents)
    metadata = project / "src/esp_image_server.egg-info"
    metadata.mkdir()
    (metadata / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: esp-image-server\nVersion: 1.2.3\n")
    (project / "src/empty_developer.egg-info").mkdir()
    for relative in ("__pycache__", "nested/__pycache__"):
        (package / relative).mkdir()
    (package / "__pycache__/module.cpython-312.pyc").write_bytes(b"Stale developer bytecode")
    (package / "nested/loose.pyc").write_bytes(b"Stale developer bytecode")

    installer = project / "installer"
    installer.mkdir()
    output = tmp_path / "fixture compiler output"
    installed = (tmp_path / "extracted source").resolve()
    assert installed.is_relative_to(tmp_path.resolve())
    script = installer / "source-fixture.iss"
    script.write_text("\n".join([
        "[Setup]", "AppName=ESP source packaging fixture", "AppVersion=0.0.0",
        "AppId=ESPImageServerSourcePackagingFixture", "PrivilegesRequired=lowest",
        f"DefaultDirName={installed}", "UsePreviousAppDir=no", "DisableDirPage=yes",
        "DisableProgramGroupPage=yes", "DisableReadyPage=yes", "DisableFinishedPage=yes",
        "Uninstallable=no", "CreateUninstallRegKey=no", "DirExistsWarning=no",
        f"OutputDir={output}", "OutputBaseFilename=source-fixture", "Compression=none",
        "[Files]", entry, "",
    ]), encoding="utf-8-sig")
    compiled = subprocess.run([compiler, "/Q", str(script)], capture_output=True, text=True,
                              errors="replace", timeout=90)
    (tmp_path / "compiler.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    # Only this newly compiled, source-only fixture executes; never the app's
    # installer, bootstrap, runtime, or development Python packaging commands.
    result = subprocess.run([str(output / "source-fixture.exe"), "/VERYSILENT", "/SP-", "/NORESTART",
                             f"/DIR={installed}", f"/LOG={tmp_path / 'extraction.log'}"],
                            capture_output=True, timeout=90)
    assert result.returncode == 0, (tmp_path / "extraction.log").read_text(errors="replace")
    return installed, assets


def test_inno_source_payload_excludes_developer_metadata_and_bytecode(tmp_path):
    installed, assets = extract_source_fixture(tmp_path, production_source_entry())
    actual = {path.relative_to(installed).as_posix(): path.read_bytes()
              for path in installed.rglob("*") if path.is_file()}
    expected = {"src/esp_image_server/" + name: contents for name, contents in assets.items()}
    assert actual == expected
    # Checking files alone misses the regression: an EMPTY .egg-info directory
    # is still discovered by pip and makes the final `pip check` fail.
    forbidden = [path.relative_to(installed).as_posix() for path in installed.rglob("*")
                 if path.name.endswith(".egg-info") or path.name == "__pycache__"]
    assert forbidden == []
