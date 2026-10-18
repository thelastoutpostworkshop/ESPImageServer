"""Run bootstrap discovery with synthetic installs; never execute its installer body."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell discovery")

# Only these production functions and constants are evaluated. In particular,
# bootstrap's top-level file deletion, winget, pip, and venv work never runs.
HARNESS = r'''
param([string]$Bootstrap, [string]$Interpreter, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Bootstrap, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('SupportedPythonVersion', 'supportedPythonCheck')) {
    $assignment = @($ast.EndBlock.Statements | Where-Object {
        $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left.Extent.Text -eq ('$' + $name)
    })
    if ($assignment.Count -ne 1) { throw "Missing production constant: $name" }
    . ([scriptblock]::Create($assignment[0].Extent.Text))
}
foreach ($name in @('Get-RegisteredPythonPaths', 'Get-DefaultPythonPaths',
                   'Test-SupportedPythonCommand', 'Get-PythonCommand', 'Get-OrInstallPythonCommand')) {
    $definition = @($ast.EndBlock.Statements | Where-Object {
        $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -eq $name
    })
    if ($definition.Count -ne 1) { throw "Missing production function: $name" }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
function Assert-Equal($Actual, $Expected, [string]$Message) {
    $actualJson = ConvertTo-Json -InputObject $Actual -Compress -Depth 5
    $expectedJson = ConvertTo-Json -InputObject $Expected -Compress -Depth 5
    if ($actualJson -cne $expectedJson) { throw "$Message. Expected $expectedJson; got $actualJson" }
}
function Assert-Fails([scriptblock]$Action, [string]$Pattern) {
    $failure = $null
    try { & $Action | Out-Null } catch { $failure = $_.Exception.Message }
    Assert-True ([bool]$failure) 'Expected discovery to fail'
    Assert-True ($failure -match $Pattern) "Unexpected error: $failure"
}
function New-FixtureFile([string]$RelativePath) {
    $path = Join-Path $FixtureRoot $RelativePath
    $null = New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($path))
    [IO.File]::WriteAllBytes($path, [byte[]](0))
    return $path
}
$script:installLogs = [Collections.Generic.List[string]]::new()
function Write-InstallLog([string]$Message) { $script:installLogs.Add($Message) }
$script:unexpectedExternalCalls = 0
function Invoke-LoggedExternal([string]$Command, [string[]]$Arguments) {
    $script:unexpectedExternalCalls += 1
    throw "Unexpected external command; no installer may run: $Command"
}
'''

DISCOVERY_MOCKS = r'''
$script:registered = @()
$script:defaults = @()
$script:accepted = @{}
$script:applications = @{}
$script:probes = [Collections.Generic.List[object]]::new()
$script:lookups = [Collections.Generic.List[string]]::new()
function Get-RegisteredPythonPaths { return $script:registered }
function Get-DefaultPythonPaths { return $script:defaults }
function Test-SupportedPythonCommand([string[]]$Command) {
    $script:probes.Add(@($Command))
    return $script:accepted.ContainsKey($Command[0]) -and $script:accepted[$Command[0]]
}
function Get-Command {
    [CmdletBinding()]
    param([Parameter(Position=0)][string]$Name, [string]$CommandType)
    Assert-Equal $CommandType 'Application' 'Only application lookup is allowed'
    Assert-True ($Name -in @('py', 'python', 'winget')) "Unexpected command lookup: $Name"
    $script:lookups.Add($Name)
    if ($script:applications.ContainsKey($Name)) {
        return [pscustomobject]@{ Source = $script:applications[$Name] }
    }
}
'''

WINGET_MOCK = r'''
$script:wingetSource = Join-Path $FixtureRoot 'App Installer\winget.exe'
$script:applications['winget'] = $script:wingetSource
$script:wingetCalls = 0
$script:wingetExitCode = 0
$script:onInstall = {}
function Invoke-LoggedExternal([string]$Command, [string[]]$Arguments) {
    Assert-Equal $Command $script:wingetSource 'Use the resolved winget executable'
    Assert-Equal @($Arguments) @('install', '--id', 'Python.Python.3.12', '--exact',
        '--source', 'winget', '--scope', 'user', '--architecture', 'x64',
        '--accept-package-agreements', '--accept-source-agreements') 'Install the supported user-scoped x64 package'
    $script:wingetCalls += 1
    & $script:onInstall
    return $script:wingetExitCode
}
'''


def run_powershell(tmp_path: Path, scenario: str) -> None:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    assert powershell.is_file(), "Windows PowerShell 5.1 is required for installer regression tests"
    script = tmp_path / "discovery-harness.ps1"
    # Windows PowerShell requires the BOM to read Unicode fixture paths reliably.
    script.write_text(HARNESS + scenario + '\nWrite-Output "PASS"\nexit 0\n', encoding="utf-8-sig")
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(script), "-Bootstrap", str(PROJECT_ROOT / "installer/bootstrap.ps1"),
         "-Interpreter", sys.executable, "-FixtureRoot", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_registered_supported_python_precedes_defaults_and_path(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + r'''
$wrong = New-FixtureFile 'Old Python\python.exe'
$supported = New-FixtureFile 'User é 日本語\Python312\python.exe'
$fallback = New-FixtureFile 'Default Python\python.exe'
$script:registered = @($wrong, $supported)
$script:defaults = @($fallback)
$script:accepted[$supported] = $true
$script:accepted[$fallback] = $true
$selected = @(Get-OrInstallPythonCommand)
Assert-Equal $selected @($supported) 'Choose the verified registered executable intact'
Assert-Equal $script:probes.Count 2 'Skip unsupported candidates before choosing a supported one'
Assert-Equal $script:lookups.Count 0 'An existing supported install needs no PATH lookup or winget'
''')


def test_missing_and_relative_candidates_do_not_hide_supported_default(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + r'''
$supported = New-FixtureFile 'Default install\python.exe'
$script:registered = @('python.exe', (Join-Path $FixtureRoot 'missing\python.exe'))
$script:defaults = @($supported)
$script:accepted[$supported] = $true
Assert-Equal @(Get-PythonCommand) @($supported) 'Find the default install after invalid registry paths'
Assert-Equal $script:probes.Count 1 'Do not execute relative or missing candidate paths'
Assert-True (($script:installLogs -join "`n").Contains((Join-Path $FixtureRoot 'missing\python.exe'))) 'Record searched installation paths that were missing'
''')


@pytest.mark.parametrize("launcher_supported", [False, True])
def test_path_fallback_uses_resolved_application_and_pinned_launcher_version(tmp_path, launcher_supported):
    supported = "$true" if launcher_supported else "$false"
    run_powershell(tmp_path, DISCOVERY_MOCKS + f"\n$launcherSupported = {supported}\n" + r'''
$launcher = New-FixtureFile 'Launcher folder\py.exe'
$python = New-FixtureFile 'Python folder\python.exe'
$script:applications['py'] = $launcher
$script:applications['python'] = $python
$script:accepted[$launcher] = $launcherSupported
$script:accepted[$python] = $true
$selected = @(Get-PythonCommand)
Assert-Equal $script:probes[0][0] $launcher 'Probe the resolved launcher path'
Assert-True ($script:probes[0][1] -match '3\.12') 'Launcher must request the supported version'
if ($launcherSupported) {
    Assert-Equal $selected @($script:probes[0]) 'Return the verified launcher and its version arguments'
} else {
    Assert-Equal $selected @($python) 'Reject an unsupported launcher and try the resolved Python path'
}
''')


def test_windows_store_aliases_are_not_executed(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + r'''
$script:applications['py'] = New-FixtureFile 'Microsoft\WindowsApps\py.exe'
$script:applications['python'] = New-FixtureFile 'Microsoft\WindowsApps\python.exe'
Assert-True ($null -eq (Get-PythonCommand)) 'Store aliases must not count as installed Python'
Assert-Equal $script:probes.Count 0 'Do not open the Microsoft Store by probing its aliases'
''')


def test_fresh_install_is_found_from_registry_without_path_refresh(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + WINGET_MOCK + r'''
$originalPath = $env:Path
$script:onInstall = {
    $python = New-FixtureFile 'New account é\Python312\python.exe'
    $script:registered = @($python)
    $script:accepted[$python] = $true
}
$selected = @(Get-OrInstallPythonCommand)
Assert-Equal $selected @($script:registered[0]) 'Rediscover the fresh registered install in the same setup run'
Assert-Equal $script:wingetCalls 1 'Install only once'
Assert-Equal $env:Path $originalPath 'Discovery must not modify PATH'
Assert-True (-not $script:applications.ContainsKey('py')) 'Fresh account has no launcher on PATH'
Assert-True (-not $script:applications.ContainsKey('python')) 'Fresh account has no Python on PATH'
''')


def test_fresh_install_is_found_at_default_localappdata_path(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + WINGET_MOCK + r'''
# Restore the real default candidate reader; only this child process's environment changes.
$defaultReader = $ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -eq 'Get-DefaultPythonPaths'
}
. ([scriptblock]::Create($defaultReader.Extent.Text))
$env:LOCALAPPDATA = Join-Path $FixtureRoot 'Fresh account é\AppData\Local'
$env:ProgramW6432 = Join-Path $FixtureRoot 'Machine Programs'
$env:ProgramFiles = Join-Path $FixtureRoot 'Other Programs'
$script:expected = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$expectedMachine = Join-Path $env:ProgramW6432 'Python312\python.exe'
$expectedPrograms = Join-Path $env:ProgramFiles 'Python312\python.exe'
$candidates = @(Get-DefaultPythonPaths)
foreach ($candidate in @($script:expected, $expectedMachine, $expectedPrograms)) {
    Assert-True ($candidates -contains $candidate) "Missing standard install candidate: $candidate"
}
$script:onInstall = {
    $null = New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($script:expected))
    [IO.File]::WriteAllBytes($script:expected, [byte[]](0))
    $script:accepted[$script:expected] = $true
}
Assert-Equal @(Get-OrInstallPythonCommand) @($script:expected) 'Find the fresh user install without registry or PATH'
Assert-Equal $script:wingetCalls 1 'Install only once'
Assert-Equal $script:registered.Count 0 'No registry registration is required for the default location'
''')


def test_missing_winget_fails_without_running_any_external_command(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + r'''
Assert-Fails { Get-OrInstallPythonCommand } 'winget'
Assert-Equal $script:probes.Count 0 'No candidate executable exists'
Assert-Equal $script:unexpectedExternalCalls 0 'Missing winget must fail before invoking an installer'
''')


def test_successful_install_without_working_python_cannot_succeed(tmp_path):
    run_powershell(tmp_path, DISCOVERY_MOCKS + WINGET_MOCK + r'''
Assert-Fails { Get-OrInstallPythonCommand } 'Python'
Assert-Equal $script:wingetCalls 1 'A failed install is not repeated'
Assert-Equal $script:probes.Count 0 'No working executable was installed'
''')


@pytest.mark.parametrize("exit_code", [-1978335189, 2316632107])
@pytest.mark.parametrize("usable", [False, True])
def test_no_upgrade_result_requires_a_working_python(tmp_path, exit_code, usable):
    usable_value = "$true" if usable else "$false"
    run_powershell(tmp_path, DISCOVERY_MOCKS + WINGET_MOCK +
                   f"\n$script:wingetExitCode = {exit_code}\n$script:usable = {usable_value}\n" + r'''
$script:onInstall = {
    $python = New-FixtureFile 'Registered Python\python.exe'
    $script:registered = @($python)
    $script:accepted[$python] = $script:usable
}
if ($script:usable) {
    Assert-Equal @(Get-OrInstallPythonCommand) @($script:registered[0]) 'Reuse the verified runtime after winget reports no upgrade'
} else {
    Assert-Fails { Get-OrInstallPythonCommand } '(?i)installed.*(could not|unusable|not working)'
    Assert-True (($script:installLogs -join "`n") -match '(?i)Python') 'Keep Python diagnostic context in the install log'
}
Assert-Equal $script:wingetCalls 1 'An installed but unusable Python must not trigger repeated installs or automatic repair'
Assert-Equal $script:probes.Count 1 'Recheck executable compatibility after the no-upgrade result'
''')


@pytest.mark.parametrize("exit_code", [42, -1978335212])
def test_other_winget_errors_fail_with_the_actual_exit_code(tmp_path, exit_code):
    run_powershell(tmp_path, DISCOVERY_MOCKS + WINGET_MOCK +
                   f"\n$script:wingetExitCode = {exit_code}\n" + r'''
# A partially created executable does not turn an installation failure into success.
$script:onInstall = {
    $python = New-FixtureFile 'Partial Python\python.exe'
    $script:registered = @($python)
    $script:accepted[$python] = $true
}
Assert-Fails { Get-OrInstallPythonCommand } ([regex]::Escape([string]$script:wingetExitCode))
Assert-Equal $script:wingetCalls 1 'Do not retry an unexpected installer failure'
Assert-Equal $script:probes.Count 0 'Unexpected installer errors must remain failures'
''')


@pytest.mark.parametrize(("implementation", "version", "platform_name", "accepted"), [
    ("CPython", (3, 12), "win-amd64", True),
    ("CPython", (3, 11), "win-amd64", False),
    ("CPython", (3, 13), "win-amd64", False),
    ("PyPy", (3, 12), "win-amd64", False),
    ("CPython", (3, 12), "win32", False),
    ("CPython", (3, 12), "win-arm64", False),
])
def test_actual_probe_rejects_unsupported_runtime_without_installing_one(
    tmp_path, implementation, version, platform_name, accepted,
):
    wrapper = tmp_path / "runtime-probe.py"
    wrapper.write_text(
        "import platform, sys, sysconfig\n"
        f"platform.python_implementation = lambda: {implementation!r}\n"
        f"sys.version_info = {version!r}\n"
        f"sys.version = '{version[0]}.{version[1]}.0 (synthetic runtime)'\n"
        f"sysconfig.get_platform = lambda: {platform_name!r}\n"
        "assert sys.argv[1] == '-c'\n"
        "exec(sys.argv[2])\n",
        encoding="utf-8",
    )
    expected = "$true" if accepted else "$false"
    run_powershell(tmp_path,
                   f"\n$expected = {expected}\n$implementation = '{implementation}'\n"
                   f"$platformName = '{platform_name}'\n$runtimeVersion = '{version[0]}.{version[1]}.0'\n" + r'''
$wrapper = Join-Path $FixtureRoot 'runtime-probe.py'
$result = Test-SupportedPythonCommand @($Interpreter, $wrapper)
Assert-Equal $result $expected 'Production compatibility probe must validate implementation, version, and architecture'
$log = $script:installLogs -join "`n"
Assert-True ($log.Contains($Interpreter)) 'Record the actual executable that was probed'
Assert-True ($log.Contains($implementation)) 'Record the detected Python implementation'
Assert-True ($log.Contains($runtimeVersion)) 'Record the detected Python version'
Assert-True ($log.Contains($platformName)) 'Record the detected Python architecture'
if (-not $expected) {
    Assert-True ($log -match '(?i)(exit|reject|unsupported)') 'Explain why the runtime was rejected'
}
''')


def test_missing_and_failing_process_do_not_inherit_previous_success(tmp_path):
    run_powershell(tmp_path, r'''
$global:LASTEXITCODE = 0
$missing = Join-Path $FixtureRoot 'not installed\python.exe'
Assert-Equal (Test-SupportedPythonCommand @($missing)) $false 'Missing executable must not reuse a successful exit code'
$global:LASTEXITCODE = 0
Assert-Equal (Test-SupportedPythonCommand @($Interpreter, '-c', 'raise SystemExit(7)')) $false 'Nonzero process exit must be rejected'
''')


def test_compatible_python_startup_warning_does_not_reject_successful_probe(tmp_path):
    wrapper = tmp_path / "runtime-warning.py"
    wrapper.write_text(
        "import platform, sys, sysconfig\n"
        "platform.python_implementation = lambda: 'CPython'\n"
        "sys.version_info = (3, 12)\n"
        "sysconfig.get_platform = lambda: 'win-amd64'\n"
        "sys.stderr.write('Synthetic Python startup warning\\n')\n"
        "assert sys.argv[1] == '-c'\n"
        "exec(sys.argv[2])\n",
        encoding="utf-8",
    )
    run_powershell(tmp_path, r'''
$global:LASTEXITCODE = 7
$wrapper = Join-Path $FixtureRoot 'runtime-warning.py'
$result = Test-SupportedPythonCommand @($Interpreter, $wrapper)
Assert-Equal $result $true 'A supported interpreter that warns on stderr and exits zero must be accepted'
Assert-True (($script:installLogs -join "`n").Contains('Synthetic Python startup warning')) 'Preserve startup warning details without rejecting a successful process'
''')


def test_python_startup_failure_is_recorded_without_becoming_a_return_value(tmp_path):
    wrapper = tmp_path / "runtime-failure.py"
    wrapper.write_text(
        "import sys\n"
        "sys.stderr.write('Synthetic startup failure\\n')\n"
        "raise SystemExit(17)\n",
        encoding="utf-8",
    )
    run_powershell(tmp_path, r'''
$wrapper = Join-Path $FixtureRoot 'runtime-failure.py'
$result = Test-SupportedPythonCommand @($Interpreter, $wrapper)
Assert-Equal $result $false 'Diagnostic output must not contaminate the Boolean probe result'
$log = $script:installLogs -join "`n"
Assert-True ($log.Contains($Interpreter)) 'Identify the executable that could not start'
Assert-True ($log.Contains('Synthetic startup failure')) 'Preserve the underlying interpreter startup error'
Assert-True ($log -match '\b17\b') 'Record the failing interpreter exit code'
''')
