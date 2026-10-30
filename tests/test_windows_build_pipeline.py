"""Exercise build helpers with harmless probes, never Inno, npm, or a real build."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows build helpers")

HARNESS = r'''
param([string]$BuildScript, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Get-BuildPythonCommand', 'Invoke-InstallerCompile')) {
    $definition = @($ast.EndBlock.Statements | Where-Object {
        $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -eq $name
    })
    if ($definition.Count -ne 1) { throw "Missing build helper: $name" }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
# No top-level version changes, runtime downloads, npm, or real compilers run.
function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
function Assert-Equal($Actual, $Expected, [string]$Message) {
    if ((ConvertTo-Json -InputObject $Actual -Compress -Depth 8) -cne
        (ConvertTo-Json -InputObject $Expected -Compress -Depth 8)) { throw $Message }
}
function Assert-Fails([scriptblock]$Action, [string]$Pattern) {
    $failure = $null
    try { & $Action | Out-Null } catch { $failure = $_.Exception.Message }
    Assert-True ([bool]$failure) 'The helper must fail'
    Assert-True ($failure -match $Pattern) "Unexpected error: $failure"
}
function Start-Sleep { param([int]$Seconds) } # Retry behavior is tested without delays.
$projectRoot = Join-Path $FixtureRoot 'project'
$trace = Join-Path $FixtureRoot 'native-arguments.txt'
$env:ESP_TEST_BUILD_TRACE = $trace
$env:ESP_TEST_BUILD_ROOT = $FixtureRoot
$env:ESP_TEST_COMPILER_MODE = 'success'
$env:ESP_TEST_REJECT_BUILD_PYTHON = ''
$probe = Join-Path $FixtureRoot 'harmless build probe.exe'
$source = @'
using System;
using System.IO;
public static class BuildProbe {
    public static int Main(string[] arguments) {
        string trace = Environment.GetEnvironmentVariable("ESP_TEST_BUILD_TRACE");
        string executable = Environment.GetCommandLineArgs()[0];
        File.AppendAllLines(trace, new [] { executable + "\t" + String.Join("\t", arguments) });
        if (arguments.Length > 0 && arguments[0].StartsWith("/O")) {
            string directory = Path.GetFullPath(arguments[0].Substring(2));
            string root = Environment.GetEnvironmentVariable("ESP_TEST_BUILD_ROOT") + Path.DirectorySeparatorChar;
            if (!directory.StartsWith(root, StringComparison.OrdinalIgnoreCase)) return 99;
            string mode = Environment.GetEnvironmentVariable("ESP_TEST_COMPILER_MODE");
            bool fail = mode == "fail" || (mode == "retry" && File.ReadAllLines(trace).Length < 3);
            if (mode != "missing") File.WriteAllText(Path.Combine(directory, "ESPImageServer-Setup-1.2.3.exe"), fail ? "partial" : "fixture artifact");
            return fail ? 17 : 0;
        }
        return String.Equals(executable, Environment.GetEnvironmentVariable("ESP_TEST_REJECT_BUILD_PYTHON"), StringComparison.OrdinalIgnoreCase) ? 1 : 0;
    }
}
'@
Add-Type -TypeDefinition $source -OutputAssembly $probe -OutputType ConsoleApplication
function New-Probe([string]$RelativePath) {
    $destination = Join-Path $FixtureRoot $RelativePath
    $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force
    Copy-Item -LiteralPath $probe -Destination $destination
    return $destination
}
$applications = @{}
function Get-Command {
    [CmdletBinding()]
    param([string]$Name, [string]$CommandType)
    Assert-Equal $CommandType 'Application' 'Only build application lookup is allowed'
    Assert-True ($Name -in @('python', 'py')) 'Unexpected build command lookup'
    if ($applications.ContainsKey($Name)) { return [pscustomobject]@{ Source = $applications[$Name] } }
}
function Invoke-FixtureCompile {
    return Invoke-InstallerCompile $probe (Join-Path $FixtureRoot 'source with spaces é\ESPImageServer.iss') `
        (Join-Path $FixtureRoot 'desktop output 日本語') (Join-Path $FixtureRoot 'runtime output é') `
        (Join-Path $FixtureRoot 'dist') '1.2.3'
}
'''


def run_powershell(tmp_path: Path, scenario: str) -> None:
    root = tmp_path / "Build account é 日本語"
    root.mkdir()
    harness = root / "build harness.ps1"
    harness.write_text(HARNESS + scenario + '\nWrite-Output "PASS"\n', encoding="utf-8-sig")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(harness), "-BuildScript", str(PROJECT / "build-installer.ps1"), "-FixtureRoot", str(root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_project_python_is_preferred_and_checked_in_isolated_mode(tmp_path):
    run_powershell(tmp_path, r'''
$local = New-Probe 'project\.venv\Scripts\python.exe'
$applications['python'] = New-Probe 'unrelated installation\python.exe'
$selected = @(Get-BuildPythonCommand)
Assert-Equal $selected @($local) 'Prefer the project build environment'
$calls = [IO.File]::ReadAllLines($trace)
Assert-Equal $calls.Count 1 'Never run unrelated Python when the project interpreter works'
$arguments = $calls[0] -split "`t"
Assert-Equal $arguments[0] $local 'Probe the project interpreter'
Assert-Equal $arguments[1] '-I' 'Build discovery ignores Python environment overrides'
Assert-Equal $arguments[2] '-c' 'Validate the build interpreter version'
Assert-True ($arguments[3] -match 'sys.version_info.*3, 12') 'Require supported build Python'
''')


def test_explicit_build_interpreter_overrides_project_and_path(tmp_path):
    run_powershell(tmp_path, r'''
$null = New-Probe 'project\.venv\Scripts\python.exe'
$explicit = New-Probe 'chosen Python é\python.exe'
$applications['python'] = New-Probe 'unrelated installation\python.exe'
Assert-Equal @(Get-BuildPythonCommand $explicit) @($explicit) 'Honor the explicit build interpreter'
Assert-Equal ([IO.File]::ReadAllLines($trace)).Count 1 'Probe only the requested interpreter'
''')


def test_unsupported_project_python_falls_back_to_resolved_build_python(tmp_path):
    run_powershell(tmp_path, r'''
$local = New-Probe 'project\.venv\Scripts\python.exe'
$env:ESP_TEST_REJECT_BUILD_PYTHON = $local
$resolved = New-Probe 'build Python\python.exe'
$applications['python'] = $resolved
Assert-Equal @(Get-BuildPythonCommand) @($resolved) 'Reject old project Python and use a supported build interpreter'
Assert-Equal ([IO.File]::ReadAllLines($trace)).Count 2 'Probe both candidates in order'
''')


def test_launcher_fallback_requests_python_312(tmp_path):
    run_powershell(tmp_path, r'''
$launcher = New-Probe 'build launcher\py.exe'
$applications['py'] = $launcher
Assert-Equal @(Get-BuildPythonCommand) @($launcher, '-3.12') 'Pin launcher fallback to supported Python'
$arguments = ([IO.File]::ReadAllLines($trace)[0]) -split "`t"
Assert-Equal @($arguments[1..3]) @('-3.12', '-I', '-c') 'Pass launcher version and isolation intact'
''')


def test_store_aliases_do_not_launch_or_download_python(tmp_path):
    run_powershell(tmp_path, r'''
$applications['python'] = New-Probe 'Microsoft\WindowsApps\python.exe'
$applications['py'] = New-Probe 'Microsoft\WindowsApps\py.exe'
Assert-Fails { Get-BuildPythonCommand } 'People installing the app do not need system Python'
Assert-True (-not (Test-Path -LiteralPath $trace)) 'Store aliases must never execute'
''')


def test_missing_explicit_build_interpreter_does_not_fall_back(tmp_path):
    run_powershell(tmp_path, r'''
$applications['python'] = New-Probe 'unrelated installation\python.exe'
Assert-Fails { Get-BuildPythonCommand (Join-Path $FixtureRoot 'missing Python\python.exe') } 'does not exist|Cannot find path'
Assert-True (-not (Test-Path -LiteralPath $trace)) 'A requested missing path must not silently select another interpreter'
''')


def test_compiler_receives_exact_private_runtime_and_desktop_inputs(tmp_path):
    run_powershell(tmp_path, r'''
$artifact = Invoke-FixtureCompile
Assert-Equal ([IO.File]::ReadAllText($artifact)) 'fixture artifact' 'Only return a finished staged artifact'
$arguments = ([IO.File]::ReadAllLines($trace)[0]) -split "`t"
Assert-Equal $arguments.Count 5 'Preserve four compiler arguments through native quoting'
Assert-Equal $arguments[1] ('/O' + [IO.Path]::GetDirectoryName($artifact)) 'Compile into the returned staging directory'
Assert-Equal $arguments[2] ('/DDesktopBuildOutput=' + (Join-Path $FixtureRoot 'desktop output 日本語')) 'Use the selected desktop bundle'
Assert-Equal $arguments[3] ('/DRuntimeBuildOutput=' + (Join-Path $FixtureRoot 'runtime output é')) 'Use the selected private Python bundle'
Assert-Equal $arguments[4] (Join-Path $FixtureRoot 'source with spaces é\ESPImageServer.iss') 'Use the expected installer definition'
''')


def test_failed_compiles_do_not_replace_previously_published_installer(tmp_path):
    run_powershell(tmp_path, r'''
$env:ESP_TEST_COMPILER_MODE = 'fail'
$output = Join-Path $FixtureRoot 'dist'
$null = New-Item -ItemType Directory -Path $output
$existing = Join-Path $output 'ESPImageServer-Setup-1.2.3.exe'
[IO.File]::WriteAllText($existing, 'previous completed installer')
Assert-Fails { Invoke-FixtureCompile } 'failed after 3 attempts'
Assert-Equal ([IO.File]::ReadAllText($existing)) 'previous completed installer' 'Preserve the published installer'
$calls = @([IO.File]::ReadAllLines($trace))
Assert-Equal $calls.Count 3 'Retry only the bounded number of attempts'
$outputs = @($calls | ForEach-Object { ($_ -split "`t")[1] })
Assert-Equal @($outputs | Select-Object -Unique).Count 3 'Each attempt uses a fresh staging directory'
''')


def test_reported_compile_success_without_artifact_is_rejected(tmp_path):
    run_powershell(tmp_path, r'''
$env:ESP_TEST_COMPILER_MODE = 'missing'
Assert-Fails { Invoke-FixtureCompile } 'reported success but did not create'
Assert-Equal ([IO.File]::ReadAllLines($trace)).Count 1 'Reject missing output immediately'
''')


def test_retry_returns_only_the_successful_attempt(tmp_path):
    run_powershell(tmp_path, r'''
$env:ESP_TEST_COMPILER_MODE = 'retry'
$artifact = Invoke-FixtureCompile
Assert-Equal ([IO.File]::ReadAllText($artifact)) 'fixture artifact' 'Never select a partial failed output'
$calls = @([IO.File]::ReadAllLines($trace))
Assert-Equal $calls.Count 3 'The third fixture attempt succeeds'
Assert-Equal (($calls[2] -split "`t")[1]) ('/O' + [IO.Path]::GetDirectoryName($artifact)) 'Return exactly the successful staging path'
''')
