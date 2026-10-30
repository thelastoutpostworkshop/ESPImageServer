"""Hosted-only Inno upgrade test; dependency download and desktop binary are fixtures."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import winreg

from upgrade_support import PROJECT, OLD_VERSION, set_backend_version, storage_probe, snapshot, assert_preserved

APP_ID = "B27A1E3C-992C-4822-B721-90A01836D7A1"
REGISTRY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{APP_ID}}}_is1"


def registered_version():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY) as key:
            return winreg.QueryValueEx(key, "DisplayVersion")[0]
    except FileNotFoundError:
        return None


def main():
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("This installer test may run only on disposable Windows GitHub runners")
    if registered_version() is not None:
        raise RuntimeError("An upgrade fixture is already installed")
    compiler = shutil.which("ISCC.exe")
    if not compiler:
        candidates = list(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).glob("Inno Setup*/ISCC.exe"))
        if not candidates:
            raise RuntimeError("Install Inno Setup on the CI runner before this test")
        compiler = str(sorted(candidates)[-1])
    current = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert current != OLD_VERSION
    with tempfile.TemporaryDirectory(prefix="esp-windows-upgrade-") as temporary:
        root = Path(temporary).resolve()
        stage = root / "fixture"
        installed = root / "Installed app"
        assert installed.resolve().is_relative_to(root)
        shutil.copytree(PROJECT / "installer", stage / "installer", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(PROJECT / "src", stage / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        for name in ("pyproject.toml", "README.md"):
            shutil.copy2(PROJECT / name, stage / name)
        (stage / "frontend/dist").mkdir(parents=True)
        (stage / "frontend/dist/index.html").write_text("CI upgrade fixture")
        desktop = stage / "desktop/release/win-unpacked"
        desktop.mkdir(parents=True)
        (desktop / "ESPImageServer.exe").write_bytes(b"CI fixture; never launched")
        # Keep the real Inno [Code] and all file destinations. Only heavyweight
        # bootstrap work is replaced with a deterministic completion fixture.
        (stage / "installer/bootstrap.ps1").write_text('''param([switch]$UseCuda)
$ErrorActionPreference = 'Stop'
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'fixture-bootstrap-runs.txt') -Value 'completed'
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installer_result.txt') -Value 'success'
''', encoding="utf-8")
        template = (stage / "installer/ESPImageServer.iss").read_text(encoding="utf-8")
        template = template.replace('#define AppName "ESPImageServer"', '#define AppName "ESPImageServerUpgradeCI"')
        template = re.sub(r"^AppId=.*$", "AppId={{" + APP_ID + "}", template, flags=re.M)
        def installer(version):
            set_backend_version(stage, version)
            script = re.sub(r'^#define AppVersion ".*"$', f'#define AppVersion "{version}"', template, flags=re.M)
            script = re.sub(r"^OutputBaseFilename=.*$", f"OutputBaseFilename=upgrade-{version}", script, flags=re.M)
            (stage / "installer/ESPImageServer.iss").write_text(script, encoding="utf-8")
            subprocess.run([compiler, "/Q", str(stage / "installer/ESPImageServer.iss")], check=True, timeout=180)
            return stage / "dist" / f"upgrade-{version}.exe"
        previous = installer(OLD_VERSION)
        latest = installer(current)
        try:
            saved = None
            for package, version, phase in ((previous, OLD_VERSION, "save"), (latest, current, "restart")):
                subprocess.run([str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER",
                                f"/DIR={installed}", f"/LOG={root / (version + '.log')}"], check=True, timeout=180)
                assert registered_version() == version
                if saved is not None:
                    assert_preserved(root / "user", saved)
                    assert (installed / ".venv/upgrade-marker").read_text() == "keep runtime"
                storage_probe(installed, root / "user", phase, version)
                if phase == "save":
                    saved = snapshot(root / "user")
                    (installed / ".venv").mkdir()
                    (installed / ".venv/upgrade-marker").write_text("keep runtime")
            assert (installed / "fixture-bootstrap-runs.txt").read_text().splitlines() == ["completed", "completed"]
            # Exercise the real Inno process monitor and finished/exit state,
            # using harmless workers instead of downloading dependencies.
            # In particular, ssPostInstall exceptions alone do not make Inno
            # return a failure exit code.
            for scenario, script_name, body in (
                ("early-exit", "bootstrap.ps1", "exit 17\n"),
                ("missing-result", "bootstrap.ps1", "exit 0\n"),
                ("success-then-error", "bootstrap.ps1", "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installer_result.txt') -Value 'success'\nexit 23\n"),
                ("supervisor-early-exit", "bootstrap-supervisor.ps1", "exit 31\n"),
            ):
                (stage / "installer" / script_name).write_text(
                    "param([switch]$UseCuda)\n" + body, encoding="utf-8"
                )
                failure_package = installer(current)
                result = subprocess.run(
                    [str(failure_package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER",
                     f"/DIR={installed}", f"/LOG={root / (scenario + '.log')}"],
                    check=False, timeout=60,
                )
                assert result.returncode == 1, f"{scenario}: expected failed setup, got {result.returncode}"
                assert_preserved(root / "user", saved)
        finally:
            uninstaller = installed / "unins000.exe"
            if uninstaller.exists():
                subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, timeout=120)
        assert registered_version() is None
    print("PASS: real Inno upgrade/data preservation and bootstrap failures return nonzero without hanging")


if __name__ == "__main__":
    main()
