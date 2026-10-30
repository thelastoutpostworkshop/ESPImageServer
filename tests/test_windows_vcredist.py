"""Exercise prerequisite decisions with WinPS5; never download or install a runtime."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HELPER = PROJECT_ROOT / "installer/ensure-vc-runtime.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows runtime prerequisite")

HARNESS = r'''
param([string]$Helper, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Helper, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Evaluate only function declarations, never the helper's top-level installer.
foreach ($definition in $ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst]
}) {
    . ([scriptblock]::Create($definition.Extent.Text))
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
    Assert-True ([bool]$failure) 'Expected runtime prerequisite to fail'
    Assert-True ($failure -match $Pattern) "Unexpected error: $failure"
}
'''

MOCKS = r'''
$script:requiredVersion = [version]'14.50.35719.0'
$script:installedVersion = $null
$script:filesValid = $false
$script:installerExitCode = 0
$script:installCompletes = $true
$script:downloadFailure = $false
$script:signatureFailure = $false
$script:downloads = 0
$script:signatureChecks = 0
$script:registrationReads = 0
$script:fileChecks = 0
$script:installCalls = [Collections.Generic.List[object]]::new()
$script:messages = [Collections.Generic.List[string]]::new()
function Write-VcRuntimeLog([string]$Message) { $script:messages.Add($Message) }
function Receive-VcRedistributable([string]$Destination) {
    $script:downloads += 1
    if ($script:downloadFailure) { throw 'Synthetic network failure' }
    Assert-True ($Destination.StartsWith($FixtureRoot + [IO.Path]::DirectorySeparatorChar)) 'Download stays inside fixture'
    $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination))
    [IO.File]::WriteAllBytes($Destination, [byte[]](0))
}
function Get-VcRedistributableVersion([string]$Path) {
    $script:signatureChecks += 1
    Assert-True ([IO.File]::Exists($Path)) 'Validate downloaded file before use'
    if ($script:signatureFailure) { throw 'Synthetic invalid Microsoft signature' }
    return $script:requiredVersion
}
function Get-InstalledVcRuntimeVersion {
    $script:registrationReads += 1
    return $script:installedVersion
}
function Test-VcRuntimeFiles([version]$RequiredVersion) {
    $script:fileChecks += 1
    Assert-True ($RequiredVersion -ge $script:requiredVersion) 'Do not accept older runtime files'
    return $script:filesValid
}
function Invoke-VcRedistributable([string]$Path, [string]$Operation, [string]$LogPath) {
    Assert-True ([IO.File]::Exists($Path)) 'Only invoke the downloaded fixture'
    Assert-Equal $script:signatureChecks 1 'Verify package before invoking it'
    Assert-True ($LogPath.StartsWith($FixtureRoot + [IO.Path]::DirectorySeparatorChar)) 'Logs stay inside fixture'
    $script:installCalls.Add([pscustomobject]@{ Path = $Path; Operation = $Operation; LogPath = $LogPath })
    if ($script:installCompletes) {
        $script:installedVersion = $script:requiredVersion
        $script:filesValid = $true
    }
    return $script:installerExitCode
}
function Run-Prerequisite {
    return Invoke-VcRuntimePrerequisite -WorkDirectory (Join-Path $FixtureRoot 'download folder') -LogDirectory (Join-Path $FixtureRoot 'log folder')
}
'''


def run_powershell(tmp_path: Path, scenario: str, *, mocks: bool = True) -> None:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    assert powershell.is_file(), "Windows PowerShell 5.1 is required for prerequisite tests"
    root = tmp_path / "User é 日本語"
    root.mkdir()
    harness = root / "runtime harness.ps1"
    harness.write_text(HARNESS + (MOCKS if mocks else "") + scenario + '\nWrite-Output "PASS"\nexit 0\n', encoding="utf-8-sig")
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(harness), "-Helper", str(HELPER), "-FixtureRoot", str(root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


@pytest.mark.parametrize("installed", ["14.50.35719.0", "14.51.40000.0"])
def test_current_or_newer_healthy_runtime_is_not_installed_again(tmp_path, installed):
    run_powershell(tmp_path, f"\n$script:installedVersion = [version]'{installed}'\n" + r'''
$script:filesValid = $true
Assert-Equal (Run-Prerequisite) 0 'Healthy runtime satisfies prerequisite'
Assert-Equal $script:installCalls.Count 0 'Do not reinstall or downgrade a working runtime'
Assert-Equal $script:signatureChecks 1 'The required version comes from a validated package'
''')


@pytest.mark.parametrize("installed", [None, "14.42.34433.0"])
def test_missing_or_old_runtime_is_installed_and_rechecked(tmp_path, installed):
    initial = "$null" if installed is None else f"[version]'{installed}'"
    run_powershell(tmp_path, f"\n$script:installedVersion = {initial}\n" + r'''
Assert-Equal (Run-Prerequisite) 0 'Install a missing or older runtime'
Assert-Equal $script:installCalls.Count 1 'Only one prerequisite install'
Assert-Equal $script:installCalls[0].Operation '/install' 'Install instead of repair'
Assert-True ($script:registrationReads -ge 2) 'Re-read registration after installation'
Assert-True ($script:fileChecks -ge 1) 'Check runtime DLLs after installation'
''')


def test_registered_but_damaged_runtime_is_repaired(tmp_path):
    run_powershell(tmp_path, r'''
$script:installedVersion = $script:requiredVersion
Assert-Equal (Run-Prerequisite) 0 'Repair runtime with missing or invalid files'
Assert-Equal $script:installCalls.Count 1 'One repair attempt'
Assert-Equal $script:installCalls[0].Operation '/repair' 'Repair damaged current runtime'
Assert-True ($script:fileChecks -ge 2) 'Check runtime DLLs again after repair'
''')


def test_reboot_required_stops_before_claiming_runtime_ready(tmp_path):
    run_powershell(tmp_path, r'''
$script:installerExitCode = 3010
$script:installCompletes = $false
Assert-Equal (Run-Prerequisite) 3010 'Propagate restart requirement to Inno'
Assert-Equal $script:installCalls.Count 1 'Run the prerequisite once'
Assert-Equal $script:registrationReads 1 'Do not use registry changes as proof before restart'
Assert-True (-not $script:filesValid) 'Fixture still requires restart'
''')


@pytest.mark.parametrize("exit_code", [0, 1638, -2147023258])
def test_success_or_already_installed_still_requires_actual_postconditions(tmp_path, exit_code):
    run_powershell(tmp_path, f"\n$script:installerExitCode = {exit_code}\n" + r'''
$script:installCompletes = $false
Assert-Fails { Run-Prerequisite } 'runtime|installed|verif|version'
Assert-Equal $script:installCalls.Count 1 'Never loop installation on a failed postcondition'
Assert-True ($script:registrationReads -ge 2) 'Validate registration even when the process claims success'
''')


@pytest.mark.parametrize("exit_code", [1638, -2147023258])
def test_already_installed_status_is_accepted_only_with_verified_runtime(tmp_path, exit_code):
    run_powershell(tmp_path, f"\n$script:installerExitCode = {exit_code}\n" + r'''
Assert-Equal (Run-Prerequisite) 0 'Accept runtime installed concurrently'
Assert-True ($script:registrationReads -ge 2) 'Check the actual installed version'
Assert-True ($script:fileChecks -ge 1) 'Check the actual installed files'
''')


def test_registered_version_alone_does_not_satisfy_postcondition(tmp_path):
    run_powershell(tmp_path, r'''
$script:installedVersion = $script:requiredVersion
$script:installCompletes = $false
Assert-Fails { Run-Prerequisite } 'runtime|installed|verif|files'
Assert-True ($script:fileChecks -ge 2) 'Missing DLLs still fail after claimed successful repair'
''')


@pytest.mark.parametrize("exit_code", [1223, -2147023673, 1602, -2147023294])
def test_cancelled_admin_approval_has_actionable_error(tmp_path, exit_code):
    run_powershell(tmp_path, f"\n$script:installerExitCode = {exit_code}\n" + r'''
$script:installCompletes = $false
Assert-Fails { Run-Prerequisite } 'cancel|approval|administrator'
Assert-Equal $script:installCalls.Count 1 'Never retry declined elevation automatically'
''')


@pytest.mark.parametrize("exit_code", [1603, 1618, -2147023293])
def test_runtime_installer_failure_is_not_treated_as_gpu_failure(tmp_path, exit_code):
    run_powershell(tmp_path, f"\n$script:installerExitCode = {exit_code}\n" + r'''
$script:installCompletes = $false
Assert-Fails { Run-Prerequisite } 'Visual C\+\+|runtime|redistributable'
Assert-Equal $script:installCalls.Count 1 'Only one attempted install'
Assert-True (($script:messages -join "`n") -notmatch 'NVIDIA.*driver') 'Runtime errors must not blame GPU drivers'
''')


@pytest.mark.parametrize("failure", ["downloadFailure", "signatureFailure"])
def test_failed_download_or_signature_never_runs_a_package(tmp_path, failure):
    run_powershell(tmp_path, f"\n$script:{failure} = $true\n" + r'''
Assert-Fails { Run-Prerequisite } 'network|signature|download'
Assert-Equal $script:installCalls.Count 0 'Never execute a failed download or untrusted package'
''')


SIGNATURE_MOCKS = r'''
$script:signatureStatus = 'Valid'
$script:certificateSubject = 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US'
$script:certificateName = 'Microsoft Corporation'
$script:missingCertificate = $false
$script:productName = 'Microsoft Visual C++ v14 Redistributable (x64) - 14.50.35719'
$script:majorVersion = 14
function Get-AuthenticodeSignature([string]$LiteralPath) {
    $certificate = [pscustomobject]@{ Subject = $script:certificateSubject }
    $certificate | Add-Member -MemberType ScriptMethod -Name GetNameInfo -Value {
        param($Type, $ForIssuer)
        return $script:certificateName
    }
    if ($script:missingCertificate) { $certificate = $null }
    return [pscustomobject]@{ Status = $script:signatureStatus; SignerCertificate = $certificate }
}
function Get-Item([string]$LiteralPath) {
    return [pscustomobject]@{ VersionInfo = [pscustomobject]@{
        ProductName = $script:productName
        FileMajorPart = $script:majorVersion
        FileMinorPart = 50
        FileBuildPart = 35719
        FilePrivatePart = 0
    } }
}
'''


def test_valid_microsoft_x64_package_supplies_required_version(tmp_path):
    run_powershell(tmp_path, SIGNATURE_MOCKS + r'''
Assert-Equal (Get-VcRedistributableVersion 'mocked package.exe').ToString() '14.50.35719.0' 'Use signed package version resources'
''', mocks=False)


@pytest.mark.parametrize("invalid_signature", [
    "$script:signatureStatus = 'NotSigned'",
    "$script:signatureStatus = 'HashMismatch'",
    "$script:missingCertificate = $true",
    "$script:certificateName = 'Another Publisher'",
    "$script:certificateSubject = 'CN=Microsoft Corporation, O=Another Publisher'",
    "$script:certificateSubject = 'CN=Microsoft Corporation, O=Microsoft Corporation Evil'",
])
def test_package_validation_rejects_untrusted_or_different_signer(tmp_path, invalid_signature):
    run_powershell(tmp_path, SIGNATURE_MOCKS + "\n" + invalid_signature + r'''
Assert-Fails { Get-VcRedistributableVersion 'mocked package.exe' } 'signature|Microsoft'
''', mocks=False)


@pytest.mark.parametrize("invalid_product", [
    "$script:productName = 'Microsoft Visual C++ v14 Redistributable (x86)'",
    "$script:productName = 'Microsoft Visual C++ v14 Redistributable (ARM64)'",
    "$script:productName = 'Another Microsoft Product (x64)'",
    "$script:majorVersion = 12",
])
def test_valid_microsoft_signature_does_not_authorize_wrong_package(tmp_path, invalid_product):
    run_powershell(tmp_path, SIGNATURE_MOCKS + "\n" + invalid_product + r'''
Assert-Fails { Get-VcRedistributableVersion 'mocked package.exe' } 'x64|v14|Redistributable'
''', mocks=False)


DLL_MOCKS = r'''
$script:badFile = ''
$script:missing = $false
$script:checkedFiles = [Collections.Generic.List[string]]::new()
function Test-Path([string]$LiteralPath, [string]$PathType) {
    $name = [IO.Path]::GetFileName($LiteralPath)
    $script:checkedFiles.Add($name)
    Assert-Equal $PathType 'Leaf' 'Check runtime files, not directories'
    return -not ($script:missing -and $name -eq $script:badFile)
}
function Get-Item([string]$LiteralPath) {
    $minor = if ([IO.Path]::GetFileName($LiteralPath) -eq $script:badFile) { 42 } else { 50 }
    return [pscustomobject]@{ VersionInfo = [pscustomobject]@{
        FileMajorPart = 14; FileMinorPart = $minor; FileBuildPart = 35719; FilePrivatePart = 0
    } }
}
'''


def test_runtime_files_check_requires_all_three_x64_libraries(tmp_path):
    run_powershell(tmp_path, DLL_MOCKS + r'''
Assert-True (Test-VcRuntimeFiles ([version]'14.50.35719.0')) 'All runtime libraries meet the minimum'
Assert-Equal @($script:checkedFiles) @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') 'Check both C++ and C runtime libraries'
''', mocks=False)


@pytest.mark.parametrize("library", ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_old_runtime_library_rejects_registration_only_success(tmp_path, library, missing):
    value = "$true" if missing else "$false"
    run_powershell(tmp_path, DLL_MOCKS + f"\n$script:badFile = '{library}'\n$script:missing = {value}\n" + r'''
Assert-True (-not (Test-VcRuntimeFiles ([version]'14.50.35719.0'))) 'Any missing or old DLL requires installation/repair'
''', mocks=False)


def test_process_adapter_preserves_switches_unicode_paths_and_exit_code(tmp_path):
    # This executable only records arguments in the fixture and returns 1638.
    # No Microsoft package, package manager, network, or host mutation is used.
    run_powershell(tmp_path, r'''
$executable = Join-Path $FixtureRoot 'harmless argument probe.exe'
$source = @'
using System;
using System.IO;
public static class RuntimeArgumentProbe {
    public static int Main(string[] arguments) {
        if (arguments.Length != 5) return 9;
        File.WriteAllLines(arguments[4], arguments);
        return 1638;
    }
}
'@
Add-Type -TypeDefinition $source -OutputAssembly $executable -OutputType ConsoleApplication
$logPath = Join-Path $FixtureRoot 'log with spaces é 日本語.txt'
foreach ($operation in @('/install', '/repair')) {
    Assert-Equal (Invoke-VcRedistributable $executable $operation $logPath) 1638 'Preserve the process exit code'
    Assert-Equal @([IO.File]::ReadAllLines($logPath)) @($operation, '/quiet', '/norestart', '/log', $logPath) 'Keep arguments and Unicode log paths intact'
}
''', mocks=False)


PROCESS_MOCKS = r'''
$script:finished = $true
$script:waitFailure = $false
$script:waitArguments = [Collections.Generic.List[int]]::new()
$script:disposals = 0
$script:kills = 0
$script:exitCodeReads = 0
function Start-VcRedistributableProcess([string]$Path, [string]$Operation, [string]$LogPath) {
    Assert-Equal $Path 'fixture.exe' 'Start the selected package'
    Assert-Equal $Operation '/install' 'Preserve the selected operation'
    Assert-Equal $LogPath 'fixture log.txt' 'Preserve the selected log path'
    $process = [pscustomobject]@{}
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
        param([int]$Milliseconds)
        $script:waitArguments.Add($Milliseconds)
        if ($script:waitFailure) { throw 'Synthetic process-wait failure' }
        return $script:finished
    }
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value {
        $script:disposals += 1
    }
    $process | Add-Member -MemberType ScriptMethod -Name Kill -Value {
        $script:kills += 1
        throw 'The runtime installer must never be killed'
    }
    $process | Add-Member -MemberType ScriptProperty -Name ExitCode -Value {
        $script:exitCodeReads += 1
        return 3010
    }
    return $process
}
function Assert-ProcessReleased {
    Assert-Equal @($script:waitArguments) @(600000) 'Bound the prerequisite wait to ten minutes'
    Assert-Equal $script:disposals 1 'Release the retained process handle'
    Assert-Equal $script:kills 0 'Never interrupt a system-wide runtime transaction'
}
'''


def test_process_wait_is_bounded_and_preserves_finished_exit_code(tmp_path):
    run_powershell(tmp_path, PROCESS_MOCKS + r'''
Assert-Equal (Invoke-VcRedistributable 'fixture.exe' '/install' 'fixture log.txt') 3010 'Preserve the completed installer exit code'
Assert-Equal $script:exitCodeReads 1 'Read completion status after the wait succeeds'
Assert-ProcessReleased
''', mocks=False)


def test_process_timeout_reports_pending_transaction_without_killing_it(tmp_path):
    run_powershell(tmp_path, PROCESS_MOCKS + r'''
$script:finished = $false
Assert-Fails { Invoke-VcRedistributable 'fixture.exe' '/install' 'fixture log.txt' } 'may still be running.*finish.*restart Windows.*retrying'
Assert-Equal $script:exitCodeReads 0 'A timeout is not a completed installation'
Assert-ProcessReleased
''', mocks=False)


def test_process_wait_failure_still_releases_handle_without_killing(tmp_path):
    run_powershell(tmp_path, PROCESS_MOCKS + r'''
$script:waitFailure = $true
Assert-Fails { Invoke-VcRedistributable 'fixture.exe' '/install' 'fixture log.txt' } 'process-wait failure'
Assert-Equal $script:exitCodeReads 0 'Do not claim an exit code after a failed wait'
Assert-ProcessReleased
''', mocks=False)
