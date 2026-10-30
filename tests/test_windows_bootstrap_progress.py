"""Exercise progress transport and the real Inno reader with harmless fixtures.

The Inno fixture exits in InitializeSetup: it has no payload, registration,
uninstaller, install hooks, or application launch. No production installer runs.
"""

from pathlib import Path
import subprocess
import sys

import pytest

from test_windows_private_runtime import run_powershell
from test_windows_source_packaging import inno_compiler


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows setup progress")


def test_status_is_published_to_current_run_and_local_diagnostics(tmp_path):
    run_powershell(tmp_path, r'''
$ProgressDirectory = Join-Path $FixtureRoot 'current setup é 日本語'
$null = New-Item -ItemType Directory -Path $ProgressDirectory
$statusPath = Join-Path $FixtureRoot 'installer_status.txt'
[IO.File]::WriteAllText($statusPath, '6|Old installation finished')
Assert-True (-not (Test-Path (Join-Path $ProgressDirectory 'progress.txt'))) 'A new run starts without stale feedback'
Set-InstallStatus 1 'Preparing Python é 日本語...'
$expected = '1|Preparing Python é 日本語...'
Assert-True ([IO.File]::ReadAllText($statusPath) -ceq $expected) 'Keep local diagnostics current'
Assert-True ([IO.File]::ReadAllText((Join-Path $ProgressDirectory 'progress.txt')) -ceq $expected) 'Publish UTF-8 status for this run'
Assert-True (-not (Test-Path ($statusPath + '.pending'))) 'Atomic publication finished'
Assert-True (-not (Test-Path (Join-Path $FixtureRoot 'installer_result.txt'))) 'Feedback does not publish success'
''')


def test_locked_feedback_is_nonfatal_preserves_last_record_and_recovers(tmp_path):
    run_powershell(tmp_path, r'''
$ProgressDirectory = Join-Path $FixtureRoot 'current setup'
$null = New-Item -ItemType Directory -Path $ProgressDirectory
$statusPath = Join-Path $FixtureRoot 'installer_status.txt'
$progress = Join-Path $ProgressDirectory 'progress.txt'
Set-InstallStatus 1 'Preparing Python...'
$lock = [IO.File]::Open($progress, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
try { Set-InstallStatus 2 'Downloading PyTorch...' } finally { $lock.Dispose() }
Assert-True ([IO.File]::ReadAllText($progress) -ceq '1|Preparing Python...') 'A locked record stays whole'
Assert-True ([IO.File]::ReadAllText($statusPath) -ceq '2|Downloading PyTorch...') 'Other diagnostics still update'
Assert-True (-not (Test-Path ($progress + '.pending'))) 'Abandoned pending feedback is removed'
Set-InstallStatus 3 'Checking installed packages...'
Assert-True ([IO.File]::ReadAllText($progress) -ceq '3|Checking installed packages...') 'Feedback recovers after unlocking'
$ProgressDirectory = Join-Path $FixtureRoot 'missing directory'
Set-InstallStatus 4 'Recording installed packages...'
Assert-True ([IO.File]::ReadAllText($statusPath) -ceq '4|Recording installed packages...') 'Unavailable feedback never prevents continuing'
''')


def test_status_retries_a_short_read_collision(tmp_path):
    run_powershell(tmp_path, r'''
$path = Join-Path $FixtureRoot 'progress.txt'
$script:attempts = 0
function Move-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$Destination, [switch]$Force)
    $script:attempts += 1
    if ($script:attempts -lt 3) { throw [IO.IOException]::new('Synthetic short read lock') }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
}
Write-InstallProgress $path '2|Downloading PyTorch...'
Assert-True ($script:attempts -eq 3) 'Retry brief sharing collisions'
Assert-True ([IO.File]::ReadAllText($path) -ceq '2|Downloading PyTorch...') 'Current status reaches the reader'
''')


def pascal_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def test_inno_reader_rejects_partial_records_and_formats_stages_and_elapsed_time(tmp_path):
    compiler = inno_compiler()
    cases = [
        (None, None), ("", None), ("2|", None), ("2|  ", None),
        ("7|Unknown", None), ("-1|Unknown", None), ("2|First\n3|Second", None),
        ("2|Partial\x00record", None), ("2|Multiple|fields", None),
        ("2|" + "x" * 256, None), ("2", None), ("2\nDownloading", None),
        ("2|Vérification 日本語...", (2, "Vérification 日本語...")),
        ("0|Installation failed.", (0, "Installation failed.")),
        *[(f"{step}|Stage {step}", (step, f"Stage {step}")) for step in range(1, 7)],
    ]
    checks = []
    for index, (contents, expected) in enumerate(cases):
        path = tmp_path / f"progress-{index}.txt"
        if contents is not None:
            path.write_bytes(contents.encode("utf-8"))
        checks.extend(["Step := 2;", "Message := 'previous';"])
        call = f"ReadBootstrapProgress({pascal_string(path)}, Step, Message)"
        if expected is None:
            checks.extend([
                f"Require(not {call}, 'Rejected record {index}');",
                f"Require((Step = 2) and (Message = 'previous'), 'Preserved status {index}');",
            ])
        else:
            step, message = expected
            checks.extend([
                f"Require({call}, 'Accepted record {index}');",
                f"Expected := {pascal_string(message)};",
                f"Require((Step = {step}) and (Message = Expected), 'Decoded status {index}');",
            ])
    for seconds, clock in [(0, "0:00"), (65, "1:05"), (3661, "61:01")]:
        checks.append(f"Require(BootstrapElapsedCaption({seconds}) = 'Elapsed: {clock}. Please keep setup open.', 'Elapsed {seconds}');")
    checks.extend([
        "Require(BootstrapProgressCaption(2, 'Downloading PyTorch...') = 'Step 2 of 6: Downloading PyTorch...', 'Stage caption');",
        "Require(BootstrapProgressCaption(3, 'Vérification 日本語...') = 'Step 3 of 6: Vérification 日本語...', 'Unicode stage caption');",
        "Require(BootstrapProgressCaption(0, 'Starting...') = 'Starting...', 'No false stage on startup');",
    ])
    result = tmp_path / "result.txt"
    script = tmp_path / "progress-reader.iss"
    script.write_text("\n".join([
        "[Setup]", "AppName=ESP progress reader fixture", "AppVersion=0.0.0",
        "PrivilegesRequired=lowest", f"DefaultDirName={tmp_path / 'unused'}",
        "Uninstallable=no", "CreateUninstallRegKey=no", "Compression=none",
        f"OutputDir={tmp_path / 'output'}", "OutputBaseFilename=progress-reader",
        "[Code]", f'#include "{PROJECT / "installer/bootstrap-progress.iss"}"',
        "procedure Require(Value: Boolean; const Message: String);",
        "begin if not Value then RaiseException(Message); end;",
        "function InitializeSetup: Boolean;",
        "var Step: Integer; Message, Expected: String;",
        "begin", "Result := False;", "try", *checks,
        f"SaveStringToFile({pascal_string(result)}, 'PASS', False);",
        "except", f"SaveStringToFile({pascal_string(result)}, Utf8Encode(GetExceptionMessage), False);",
        "end;", "end;",
    ]), encoding="utf-8-sig")
    compiled = subprocess.run([compiler, "/Q", str(script)], capture_output=True, text=True,
                              errors="replace", timeout=90)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    executed = subprocess.run([str(tmp_path / "output/progress-reader.exe"), "/VERYSILENT",
                               "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART",
                               f"/LOG={tmp_path / 'fixture.log'}"], timeout=30)
    assert result.is_file(), f"Reader fixture exited {executed.returncode} without a result"
    assert result.read_text(encoding="utf-8") == "PASS"
