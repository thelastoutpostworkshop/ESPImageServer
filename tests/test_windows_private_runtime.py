"""Run isolated setup helpers against temporary files, never real installation."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows private runtime")

HARNESS = r'''
param([string]$Bootstrap, [string]$Interpreter, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Bootstrap, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($definition in $ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst]
}) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Write-InstallLog([string]$Message) { Write-Host $Message }
function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
function Assert-Fails([scriptblock]$Action, [string]$Pattern) {
    $failure = $null
    try { & $Action | Out-Null } catch { $failure = $_.Exception.Message }
    Assert-True ([bool]$failure) 'Expected failure'
    Assert-True ($failure -match $Pattern) "Unexpected failure: $failure"
}
function New-RuntimeFixture([string]$Name, [string]$Identity, [bool]$Ready = $false) {
    $runtime = Join-Path $FixtureRoot $Name
    $null = New-Item -ItemType Directory -Path $runtime -Force
    [IO.File]::WriteAllText((Join-Path $runtime 'identity.txt'), $Identity)
    [IO.File]::WriteAllText((Join-Path $runtime 'python.exe'), 'Never execute this fixture')
    [IO.File]::WriteAllText((Join-Path $runtime 'runtime-manifest.json'), '{}')
    if ($Ready) { [IO.File]::WriteAllText((Join-Path $runtime 'runtime-ready.txt'), 'ready') }
    return $runtime
}
$stageName = 'runtime-staging-' + ('a' * 32)
$backupName = 'runtime-backup-' + ('b' * 32)
'''


def run_powershell(tmp_path: Path, scenario: str, *, expected_exit: int = 0) -> Path:
    fixture = tmp_path / "Installed app é 日本語"
    fixture.mkdir()
    harness = tmp_path / "runtime-harness.ps1"
    harness.write_text(HARNESS + scenario + '\nWrite-Output "PASS"\n', encoding="utf-8-sig")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness), "-Bootstrap", str(PROJECT / "installer/bootstrap.ps1"),
         "-Interpreter", sys.executable, "-FixtureRoot", str(fixture)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    if expected_exit == 0:
        assert "PASS" in result.stdout
    return fixture


def test_staging_uses_only_bundled_python_and_leaves_active_runtime_unchanged(tmp_path):
    run_powershell(tmp_path, r'''
$base = New-RuntimeFixture 'runtime-base' 'bundled'
$active = New-RuntimeFixture 'runtime' 'previous'
$stage = New-StagedRuntime $FixtureRoot
Assert-True ([IO.Path]::GetDirectoryName($stage) -eq $FixtureRoot) 'Stage stays in the install directory'
Assert-True ([IO.Path]::GetFileName($stage) -match '^runtime-staging-[0-9a-f]{32}$') 'Use a unique owned stage'
Assert-True ([IO.File]::ReadAllText((Join-Path $stage 'identity.txt')) -eq 'bundled') 'Copy the supplied runtime'
Assert-True ([IO.File]::ReadAllText((Join-Path $active 'identity.txt')) -eq 'previous') 'Do not mutate the working runtime'
Assert-True ([IO.File]::ReadAllText((Join-Path $base 'identity.txt')) -eq 'bundled') 'Keep base runtime immutable'
''')


def test_retry_removes_only_abandoned_staging_after_recovery(tmp_path):
    run_powershell(tmp_path, r'''
$stage = New-RuntimeFixture $stageName 'interrupted-download'
$active = New-RuntimeFixture 'runtime' 'previous'
$manual = New-RuntimeFixture 'runtime-staging-manual' 'keep'
Remove-AbandonedRuntimeStages $FixtureRoot
Assert-True (-not (Test-Path -LiteralPath $stage)) 'Remove interrupted dependency download'
Assert-True (Test-Path -LiteralPath $active) 'Never remove active runtime'
Assert-True (Test-Path -LiteralPath $manual) 'Do not guess ownership from a prefix alone'
[IO.File]::WriteAllText((Join-Path $FixtureRoot 'runtime-promotion.json'), '{}')
Assert-Fails { Remove-AbandonedRuntimeStages $FixtureRoot } 'recovery must finish'
''')


@pytest.mark.parametrize("missing", ["python.exe", "runtime-manifest.json"])
def test_incomplete_bundle_cannot_fall_back_to_system_python(tmp_path, missing):
    run_powershell(tmp_path, f"\n$missing = '{missing}'\n" + r'''
$base = New-RuntimeFixture 'runtime-base' 'bundled'
Remove-Item -LiteralPath (Join-Path $base $missing)
Assert-Fails { New-StagedRuntime $FixtureRoot } 'bundled Python runtime is incomplete'
Assert-True (@(Get-ChildItem -LiteralPath $FixtureRoot -Filter 'runtime-staging-*').Count -eq 0) 'Reject before staging'
''')


def test_successful_promotion_verifies_relocated_runtime_and_preserves_data(tmp_path):
    run_powershell(tmp_path, r'''
$active = New-RuntimeFixture 'runtime' 'previous'
$stage = New-RuntimeFixture $stageName 'next' $true
$userData = Join-Path $FixtureRoot 'settings-and-images.txt'
[IO.File]::WriteAllText($userData, 'preserve user content')
$script:verified = $false
Complete-RuntimePromotion $FixtureRoot $stage {
    param($relocated)
    Assert-True ($relocated -eq $active) 'Verify at the final path'
    Assert-True ([IO.File]::ReadAllText((Join-Path $relocated 'identity.txt')) -eq 'next') 'Check the new runtime'
    $script:verified = $true
}
Assert-True $script:verified 'Do not commit without final validation'
Assert-True (-not (Test-Path -LiteralPath $stage)) 'Stage was moved'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $FixtureRoot 'runtime-promotion.json'))) 'Committed journal removed'
Assert-True (@(Get-ChildItem -LiteralPath $FixtureRoot -Filter 'runtime-backup-*').Count -eq 0) 'Old runtime removed only after validation'
Assert-True ([IO.File]::ReadAllText($userData) -eq 'preserve user content') 'User data preserved'
''')


def test_relative_source_mapping_survives_runtime_promotion(tmp_path):
    run_powershell(tmp_path, r'''
$stage = New-RuntimeFixture $stageName 'next' $true
$site = Join-Path $stage 'Lib\site-packages'
$source = Join-Path $FixtureRoot 'src'
$null = New-Item -ItemType Directory -Path $site -Force
$null = New-Item -ItemType Directory -Path $source
[IO.File]::WriteAllText((Join-Path $site 'esp-image-server.pth'), "../../../src`n")
[IO.File]::WriteAllText((Join-Path $source 'esp_relocation_probe.py'), 'VALUE = 42')
$probe = Join-Path $FixtureRoot 'relocation probe.py'
@'
import site, sys
from pathlib import Path
site.addsitedir(str(Path(sys.argv[1]) / 'Lib/site-packages'))
import esp_relocation_probe
assert esp_relocation_probe.VALUE == 42
assert Path(esp_relocation_probe.__file__).parent == Path(sys.argv[2])
'@ | Set-Content -LiteralPath $probe -Encoding UTF8
Assert-True ((Invoke-LoggedExternal $Interpreter @('-I', $probe, $stage, $source)) -eq 0) 'Source imports from staging'
Complete-RuntimePromotion $FixtureRoot $stage {
    param($relocated)
    Assert-True ((Invoke-LoggedExternal $Interpreter @('-I', $probe, $relocated, $source)) -eq 0) 'Source imports after promotion'
}
''')


@pytest.mark.parametrize("existing", [False, True])
def test_failed_final_validation_rolls_back_promotion(tmp_path, existing):
    run_powershell(tmp_path, f"\n$existing = {'$true' if existing else '$false'}\n" + r'''
$active = Join-Path $FixtureRoot 'runtime'
if ($existing) { $null = New-RuntimeFixture 'runtime' 'previous' }
$stage = New-RuntimeFixture $stageName 'bad-new-runtime' $true
Assert-Fails { Complete-RuntimePromotion $FixtureRoot $stage { throw 'Synthetic relocated import failure' } } 'previous runtime was preserved'
if ($existing) {
    Assert-True ([IO.File]::ReadAllText((Join-Path $active 'identity.txt')) -eq 'previous') 'Restore working runtime'
} else {
    Assert-True (-not (Test-Path -LiteralPath $active)) 'Failed first install must not leave active runtime'
}
Assert-True (Test-Path -LiteralPath $stage) 'Failed stage remains owned for caller cleanup'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $FixtureRoot 'runtime-promotion.json'))) 'Rollback finished'
''')


def test_unverified_stage_never_replaces_active_runtime(tmp_path):
    run_powershell(tmp_path, r'''
$active = New-RuntimeFixture 'runtime' 'previous'
$stage = New-RuntimeFixture $stageName 'unverified'
Assert-Fails { Complete-RuntimePromotion $FixtureRoot $stage { throw 'Must not validate' } } 'has not passed validation'
Assert-True ([IO.File]::ReadAllText((Join-Path $active 'identity.txt')) -eq 'previous') 'Old runtime untouched'
''')


@pytest.mark.parametrize("new_active", [False, True])
def test_retry_recovers_interruption_during_runtime_promotion(tmp_path, new_active):
    run_powershell(tmp_path, f"\n$newActive = {'$true' if new_active else '$false'}\n" + r'''
$null = New-RuntimeFixture $backupName 'previous'
if ($newActive) { $null = New-RuntimeFixture 'runtime' 'interrupted-next' $true }
else { $null = New-RuntimeFixture $stageName 'interrupted-next' $true }
@{ stage = $stageName; backup = $backupName } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $FixtureRoot 'runtime-promotion.json') -Encoding UTF8
Recover-RuntimePromotion $FixtureRoot
Assert-True ([IO.File]::ReadAllText((Join-Path $FixtureRoot 'runtime\identity.txt')) -eq 'previous') 'Restore previous runtime after interruption'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $FixtureRoot $stageName))) 'Remove only interrupted stage'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $FixtureRoot 'runtime-promotion.json'))) 'Recovery complete'
''')


@pytest.mark.parametrize("name", ["runtime", "..", "../outside", "runtime-staging-other", "C:\\outside"])
def test_cleanup_rejects_unowned_names(tmp_path, name):
    escaped = name.replace("'", "''")
    run_powershell(tmp_path, f"\nAssert-Fails {{ Remove-StagedRuntime $FixtureRoot '{escaped}' }} 'owned staging or backup'\n")


def test_recovery_rejects_paths_outside_the_owned_runtime_directories(tmp_path):
    run_powershell(tmp_path, r'''
@{ stage = '..\outside'; backup = $backupName } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $FixtureRoot 'runtime-promotion.json') -Encoding UTF8
Assert-Fails { Recover-RuntimePromotion $FixtureRoot } 'recovery record is invalid'
''')


def test_interrupted_journal_write_does_not_block_retry_or_move_active_runtime(tmp_path):
    run_powershell(tmp_path, r'''
$active = New-RuntimeFixture 'runtime' 'previous'
$pending = Join-Path $FixtureRoot 'runtime-promotion.pending.json'
[IO.File]::WriteAllText($pending, '{"stage":')
Recover-RuntimePromotion $FixtureRoot
Assert-True (-not (Test-Path -LiteralPath $pending)) 'Discard only an uncommitted record'
Assert-True ([IO.File]::ReadAllText((Join-Path $active 'identity.txt')) -eq 'previous') 'Keep original active runtime'
''')


def test_runtime_directory_links_are_rejected_before_copy_or_removal(tmp_path):
    run_powershell(tmp_path, r'''
$outside = Join-Path $FixtureRoot 'user-images'
$null = New-Item -ItemType Directory -Path $outside
[IO.File]::WriteAllText((Join-Path $outside 'saved.jpg'), 'preserve')
$linked = Join-Path $FixtureRoot $stageName
$null = New-Item -ItemType Junction -Path $linked -Target $outside
try { Assert-Fails { Remove-StagedRuntime $FixtureRoot $stageName } 'directory that is a link' }
finally { [IO.Directory]::Delete($linked) }
Assert-True ([IO.File]::ReadAllText((Join-Path $outside 'saved.jpg')) -eq 'preserve') 'Never traverse user links'
''')


def test_native_commands_isolate_python_and_pip_environment_and_restore_parent(tmp_path):
    run_powershell(tmp_path, r'''
$probe = Join-Path $FixtureRoot 'environment probe.py'
@'
import json, os, sys
from pathlib import Path
Path(__file__).with_suffix('.json').write_text(json.dumps({
    'pythonhome': os.environ.get('PYTHONHOME'), 'pythonpath': os.environ.get('PYTHONPATH'),
    'target': os.environ.get('PIP_TARGET'), 'config': os.environ.get('PIP_CONFIG_FILE'),
    'app': os.environ.get('ESP_IMAGE_TEST'), 'isolated': sys.flags.isolated,
    'user_site': sys.flags.no_user_site,
}))
'@ | Set-Content -LiteralPath $probe -Encoding UTF8
$env:PYTHONHOME = 'invalid inherited prefix'
$env:PYTHONPATH = 'invalid inherited imports'
$env:PIP_TARGET = 'outside-runtime'
$env:PIP_CONFIG_FILE = 'inherited-pip.ini'
$env:ESP_IMAGE_TEST = 'preserve deliberate configuration'
Assert-True ((Invoke-LoggedExternal $Interpreter @('-I', $probe)) -eq 0) 'Conflicting parent environment cannot break private commands'
$result = Get-Content -LiteralPath ([IO.Path]::ChangeExtension($probe, '.json')) -Raw | ConvertFrom-Json
Assert-True ($null -eq $result.pythonhome -and $null -eq $result.pythonpath -and $null -eq $result.target) 'Remove conflicting child overrides'
Assert-True ($result.config -eq 'NUL') 'Disable pip configuration files'
Assert-True ($result.isolated -eq 1 -and $result.user_site -eq 1) 'Use isolated Python startup'
Assert-True ($result.app -eq $env:ESP_IMAGE_TEST) 'Keep deliberate app configuration'
Assert-True ($env:PYTHONHOME -eq 'invalid inherited prefix' -and $env:PYTHONPATH -eq 'invalid inherited imports') 'Restore parent Python environment'
Assert-True ($env:PIP_TARGET -eq 'outside-runtime' -and $env:PIP_CONFIG_FILE -eq 'inherited-pip.ini') 'Restore parent pip environment'
''')


def test_uninstall_removes_owned_runtime_directories_and_preserves_unrelated_files(tmp_path):
    installed = tmp_path / "Installed app"
    installed.mkdir()
    owned = ["runtime", "runtime-base", "runtime-staging-" + "a" * 32, "runtime-backup-" + "b" * 32]
    for name in [*owned, "user-library", "runtime-staging-manual"]:
        (installed / name).mkdir()
        (installed / name / "keep.txt").write_text("fixture")
    (installed / "runtime-promotion.json").write_text("{}")
    environment = os.environ.copy()
    environment.update(LOCALAPPDATA=str(tmp_path / "local"), APPDATA=str(tmp_path / "roaming"))
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(PROJECT / "installer/cleanup.ps1"), "-InstallRoot", str(installed)],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(not (installed / name).exists() for name in owned)
    assert not (installed / "runtime-promotion.json").exists()
    assert (installed / "user-library/keep.txt").read_text() == "fixture"
    assert (installed / "runtime-staging-manual/keep.txt").read_text() == "fixture"


@pytest.mark.parametrize("failure", ["none", "gpu", "relocated_import"])
def test_complete_bootstrap_uses_staging_and_commits_only_after_success(tmp_path, failure):
    fixture = run_powershell(tmp_path, f"\n$failureScenario = '{failure}'\n" + r'''
$projectRoot = $FixtureRoot
$logPath = Join-Path $FixtureRoot 'bootstrap.log'
$statusPath = Join-Path $FixtureRoot 'installer_status.txt'
$resultPath = Join-Path $FixtureRoot 'installer_result.txt'
$env:LOCALAPPDATA = Join-Path $FixtureRoot 'fixture-account'
$UseCuda = $true
$stagedRuntime = $null
$null = New-RuntimeFixture 'runtime-base' 'bundled-next'
$null = New-RuntimeFixture 'runtime' 'previous'
[IO.File]::WriteAllText((Join-Path $FixtureRoot 'constraints-cuda.txt'), 'fixture')
[IO.File]::WriteAllText((Join-Path $FixtureRoot 'verify-gpu.py'), 'Never execute this fixture')
[IO.File]::WriteAllText((Join-Path $FixtureRoot 'saved-image.jpg'), 'preserve image')
function Invoke-RuntimeSetup([string]$Python, [string]$Operation, [string]$Runtime) {
    Assert-True ($Python -eq (Join-Path $Runtime 'python.exe')) 'Use private standalone interpreter'
    if ($Operation -eq 'requirements') {
        [IO.File]::WriteAllText((Join-Path $Runtime 'generation-requirements.txt'), 'fixture')
    }
    if ($failureScenario -eq 'relocated_import' -and $Operation -eq 'verify' -and [IO.Path]::GetFileName($Runtime) -eq 'runtime') {
        throw 'Synthetic import failure after promotion'
    }
}
function Invoke-LoggedExternal([string]$Command, [string[]]$Arguments) {
    Assert-True ($Command.StartsWith($FixtureRoot + '\runtime-staging-')) 'Never install into the active or system runtime'
    Assert-True ($Arguments[0] -eq '-I') 'Every command uses isolated Python'
    if ($failureScenario -eq 'gpu' -and $Arguments -contains (Join-Path $FixtureRoot 'verify-gpu.py')) { return 12 }
    return 0
}
$body = @($ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.TryStatementAst] -and $_.Extent.Text.Contains('Recover-RuntimePromotion $projectRoot')
})
Assert-True ($body.Count -eq 1) 'Exactly one production bootstrap body'
. ([scriptblock]::Create($body[0].Extent.Text))
''', expected_exit=0 if failure == "none" else 1)
    expected = "bundled-next" if failure == "none" else "previous"
    assert (fixture / "runtime/identity.txt").read_text() == expected
    assert (fixture / "installer_result.txt").read_text().strip() == ("success" if failure == "none" else "failed")
    assert (fixture / "saved-image.jpg").read_text() == "preserve image"
    assert not list(fixture.glob("runtime-staging-*"))
    assert not list(fixture.glob("runtime-backup-*"))
    assert not (fixture / "runtime-promotion.json").exists()
