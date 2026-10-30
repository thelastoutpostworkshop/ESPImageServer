[CmdletBinding()]
param(
    [switch]$UseCuda,
    [string]$ProgressDirectory
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$logPath = Join-Path $projectRoot 'bootstrap.log'
$statusPath = Join-Path $projectRoot 'installer_status.txt'
$resultPath = Join-Path $projectRoot 'installer_result.txt'

Remove-Item $statusPath, $resultPath, $logPath -Force -ErrorAction SilentlyContinue
function Write-SharedText([string]$Path, [string]$Text, [bool]$Append = $false) {
    $mode = if ($Append) { [System.IO.FileMode]::Append } else { [System.IO.FileMode]::Create }
    $stream = [System.IO.File]::Open($Path, $mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    try {
        $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
        try {
            $writer.Write($Text)
            $writer.Flush()
        } finally {
            $writer.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

Write-SharedText $logPath "ESPImageServer setup log`r`n"

function Write-InstallLog([string]$Message) {
    Write-SharedText $logPath "$Message`r`n" $true
    Write-Host $Message
}

function Invoke-LoggedExternal([string]$Command, [string[]]$Arguments) {
    # Some Python libraries write warnings to stderr even when their command
    # succeeds. Treat those as log output and use the process exit code to
    # determine whether the installer should fail.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $exitCode = 1
    $savedEnvironment = @{}
    foreach ($entry in @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(PYTHON|PIP_)' })) {
        $savedEnvironment[$entry.Name] = $entry.Value
        [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
    }
    $env:PIP_CONFIG_FILE = 'NUL'
    try {
        # A failed process launch must not reuse a previous command's success.
        $global:LASTEXITCODE = 1
        & $Command @Arguments 2>&1 | ForEach-Object {
            Write-InstallLog $_.ToString()
        }
        $exitCode = $LASTEXITCODE
    } finally {
        foreach ($entry in @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(PYTHON|PIP_)' })) {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
        foreach ($name in $savedEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
        }
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $exitCode
}

function Write-InstallProgress([string]$Path, [string]$Text) {
    # Publish a whole status record. A brief wizard read lock or unavailable
    # feedback file must not abort package installation or runtime activation.
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        try {
            if (-not [IO.Path]::IsPathRooted($Path)) { return }
            [IO.File]::WriteAllText(($Path + '.pending'), $Text, [Text.UTF8Encoding]::new($false))
            Move-Item -LiteralPath ($Path + '.pending') -Destination $Path -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -lt 2) { Start-Sleep -Milliseconds 25 }
        }
    }
    Remove-Item -LiteralPath ($Path + '.pending') -Force -ErrorAction SilentlyContinue
    Write-Host 'Setup progress feedback is temporarily unavailable.'
}

function Set-InstallStatus([int]$Step, [string]$Message) {
    if ($ProgressDirectory) {
        Write-InstallProgress (Join-Path $ProgressDirectory 'progress.txt') "$Step|$Message"
    }
    Write-InstallProgress $statusPath "$Step|$Message"
    Write-InstallLog "[$Step/6] $Message"
}

function Get-OwnedRuntimePath([string]$Root, [string]$Name) {
    if (-not [IO.Path]::IsPathRooted($Root) -or $Name -notmatch '^(runtime|runtime-base|runtime-staging-[0-9a-f]{32}|runtime-backup-[0-9a-f]{32})$') {
        throw 'Invalid app-owned runtime path.'
    }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $candidate = [IO.Path]::GetFullPath((Join-Path $rootFull $Name))
    if ([IO.Path]::GetDirectoryName($candidate) -ne $rootFull) {
        throw 'The runtime path is outside the application directory.'
    }
    return $candidate
}

function Assert-PlainRuntimeDirectory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "Runtime directory is missing: $Path" }
    $directory = Get-Item -LiteralPath $Path -Force
    if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing a runtime directory that is a link: $Path"
    }
    foreach ($entry in Get-ChildItem -LiteralPath $Path -Recurse -Force) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing a linked file or directory inside the app runtime: $($entry.FullName)"
        }
    }
}

function Remove-StagedRuntime([string]$Root, [string]$Name) {
    if ($Name -notmatch '^runtime-(staging|backup)-[0-9a-f]{32}$') {
        throw 'Only an owned staging or backup runtime can be removed.'
    }
    $path = Get-OwnedRuntimePath $Root $Name
    if (Test-Path -LiteralPath $path) {
        Assert-PlainRuntimeDirectory $path
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

function Recover-RuntimePromotion([string]$Root) {
    $active = Get-OwnedRuntimePath $Root 'runtime'
    # A forced exit while writing the record cannot leave a partial journal:
    # only the closed pending file is renamed to the durable record.
    [IO.File]::Delete((Join-Path $Root 'runtime-promotion.pending.json'))
    $journalPath = Join-Path $Root 'runtime-promotion.json'
    if (-not (Test-Path -LiteralPath $journalPath)) { return }
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    if ($journal.stage -notmatch '^runtime-staging-[0-9a-f]{32}$' -or
        $journal.backup -notmatch '^runtime-backup-[0-9a-f]{32}$') {
        throw 'The runtime recovery record is invalid. Repair the app installation.'
    }
    $stage = Get-OwnedRuntimePath $Root $journal.stage
    $backup = Get-OwnedRuntimePath $Root $journal.backup
    if (Test-Path -LiteralPath $backup) {
        Assert-PlainRuntimeDirectory $backup
        if (Test-Path -LiteralPath $active) {
            Assert-PlainRuntimeDirectory $active
            if (Test-Path -LiteralPath $stage) { throw 'Runtime recovery found conflicting staged files. Close the app and retry setup.' }
            [IO.Directory]::Move($active, $stage)
        }
        [IO.Directory]::Move($backup, $active)
        Write-InstallLog 'Recovered the previous runtime after an interrupted setup.'
    }
    # No backup means the first install or a transaction that did not move the
    # old runtime yet. Never delete the active runtime in either case.
    Remove-StagedRuntime $Root $journal.stage
    Remove-Item -LiteralPath $journalPath -Force
}

function New-StagedRuntime([string]$Root) {
    $base = Get-OwnedRuntimePath $Root 'runtime-base'
    Assert-PlainRuntimeDirectory $base
    if (-not (Test-Path -LiteralPath (Join-Path $base 'python.exe') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $base 'runtime-manifest.json') -PathType Leaf)) {
        throw 'The bundled Python runtime is incomplete. Run the ESPImageServer installer again.'
    }
    $name = 'runtime-staging-' + [guid]::NewGuid().ToString('N')
    $stage = Get-OwnedRuntimePath $Root $name
    try { Copy-Item -LiteralPath $base -Destination $stage -Recurse -Force }
    catch {
        if (Test-Path -LiteralPath $stage) { Remove-StagedRuntime $Root $name }
        throw
    }
    return $stage
}

function Remove-AbandonedRuntimeStages([string]$Root) {
    # Inno's SetupMutex prevents a second setup from owning one of these paths.
    # Recovery must finish first; its journal can still reference a staged copy.
    if (Test-Path -LiteralPath (Join-Path $Root 'runtime-promotion.json')) {
        throw 'Runtime recovery must finish before cleaning abandoned staging directories.'
    }
    foreach ($directory in Get-ChildItem -LiteralPath $Root -Directory -Force) {
        if ($directory.Name -match '^runtime-staging-[0-9a-f]{32}$') {
            Remove-StagedRuntime $Root $directory.Name
        }
    }
}

function Complete-RuntimePromotion([string]$Root, [string]$Stage, [scriptblock]$Verify) {
    $stageName = [IO.Path]::GetFileName($Stage)
    if ((Get-OwnedRuntimePath $Root $stageName) -ne [IO.Path]::GetFullPath($Stage) -or
        $stageName -notmatch '^runtime-staging-[0-9a-f]{32}$') { throw 'Invalid staged runtime for promotion.' }
    Assert-PlainRuntimeDirectory $Stage
    if (-not (Test-Path -LiteralPath (Join-Path $Stage 'runtime-ready.txt') -PathType Leaf) -or
        [IO.File]::ReadAllText((Join-Path $Stage 'runtime-ready.txt')).Trim() -cne 'ready') {
        throw 'The staged runtime has not passed validation.'
    }
    $active = Get-OwnedRuntimePath $Root 'runtime'
    $backupName = 'runtime-backup-' + [guid]::NewGuid().ToString('N')
    $backup = Get-OwnedRuntimePath $Root $backupName
    $journalPath = Join-Path $Root 'runtime-promotion.json'
    if (Test-Path -LiteralPath $journalPath) { throw 'Recover the previous runtime transaction before installing another.' }
    if (Test-Path -LiteralPath $active) { Assert-PlainRuntimeDirectory $active }
    $pendingPath = Join-Path $Root 'runtime-promotion.pending.json'
    [IO.File]::Delete($pendingPath)
    $record = @{ stage = $stageName; backup = $backupName } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($pendingPath, $record, [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($pendingPath, $journalPath)
    $promoted = $false
    try {
        if (Test-Path -LiteralPath $active) { [IO.Directory]::Move($active, $backup) }
        [IO.Directory]::Move($Stage, $active)
        $promoted = $true
        & $Verify $active
    } catch {
        $failure = $_.Exception.Message
        try {
            if ($promoted) { [IO.Directory]::Move($active, $Stage) }
            if (Test-Path -LiteralPath $backup) { [IO.Directory]::Move($backup, $active) }
            Remove-Item -LiteralPath $journalPath -Force
        } catch {
            throw "Runtime activation failed: $failure Recovery is pending; close ESPImageServer and rerun setup. $($_.Exception.Message)"
        }
        throw "Runtime activation failed; the previous runtime was preserved. Close ESPImageServer and retry setup. $failure"
    }
    # Commit by removing the recovery record before discarding the backup. A
    # forced exit can leave an unused backup, but cannot roll back a later run.
    Remove-Item -LiteralPath $journalPath -Force
    try { Remove-StagedRuntime $Root $backupName }
    catch { Write-InstallLog "The previous runtime backup could not be removed: $($_.Exception.Message)" }
}

function Invoke-RuntimeSetup([string]$Python, [string]$Operation, [string]$Runtime) {
    $arguments = @('-I', (Join-Path $projectRoot 'runtime-setup.py'), $Operation, $Runtime)
    if ($Operation -eq 'requirements') { $arguments += @('--project', $projectRoot) }
    if ((Invoke-LoggedExternal $Python $arguments) -ne 0) {
        throw "The private Python runtime failed its $Operation check. See bootstrap.log and run the installer again."
    }
}

function Write-ResolvedDependencyVersions([string]$Python) {
    Write-InstallLog 'Resolved Python package versions (pip freeze --all):'
    if ((Invoke-LoggedExternal $Python @('-I', '-m', 'pip', 'freeze', '--all')) -ne 0) {
        throw 'Unable to record the installed Python package versions.'
    }
}

$stagedRuntime = $null
try {
    Recover-RuntimePromotion $projectRoot
    Remove-AbandonedRuntimeStages $projectRoot
    Set-InstallStatus 1 'Preparing the bundled private Python runtime...'
    $stagedRuntime = New-StagedRuntime $projectRoot
    $runtimePython = Join-Path $stagedRuntime 'python.exe'
    Invoke-RuntimeSetup $runtimePython 'requirements' $stagedRuntime

    $constraintsFileName = if ($UseCuda) { 'constraints-cuda.txt' } else { 'constraints-cpu.txt' }
    $constraintsFile = Join-Path $projectRoot $constraintsFileName
    if (-not (Test-Path -LiteralPath $constraintsFile -PathType Leaf)) {
        throw "The required dependency constraints file is missing: $constraintsFileName"
    }
    $torchIndexUrl = if ($UseCuda) { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
    Write-InstallLog "Using the bundled private Python runtime, $constraintsFileName, and the selected PyTorch wheel index."
    Set-InstallStatus 2 'Updating the Python package installer...'
    if ((Invoke-LoggedExternal $runtimePython @('-I', '-m', 'pip', 'install', '--upgrade', '--constraint', $constraintsFile, 'pip')) -ne 0) {
        throw 'Unable to install the pinned pip version.'
    }
    Set-InstallStatus 2 'Downloading and installing PyTorch...'
    if ((Invoke-LoggedExternal $runtimePython @('-I', '-m', 'pip', 'install', '--upgrade', '--constraint', $constraintsFile, '--index-url', $torchIndexUrl, '--extra-index-url', 'https://pypi.org/simple', 'torch', 'torchvision')) -ne 0) {
        throw 'Unable to install the pinned PyTorch and torchvision packages.'
    }
    if ($UseCuda) {
        # A script file avoids Windows PowerShell 5.1 stripping embedded quotes
        # from Python source. Explicit Python checks also work with optimization
        # enabled, which would otherwise remove assert-based validation.
        $gpuCheckPath = Join-Path $projectRoot 'verify-gpu.py'
        if (-not (Test-Path -LiteralPath $gpuCheckPath -PathType Leaf)) {
            throw 'The GPU validation script is missing. Run the installer again.'
        }
        Set-InstallStatus 2 'Checking NVIDIA GPU support...'
        $gpuCheckExitCode = Invoke-LoggedExternal $runtimePython @('-I', $gpuCheckPath)
        switch ($gpuCheckExitCode) {
            0 { }
            10 { throw 'PyTorch could not be loaded. See the preceding package or DLL error in bootstrap.log. Repair the Microsoft Visual C++ x64 runtime and Python/PyTorch installation, then retry setup.' }
            11 { throw 'CPU-only PyTorch was installed. Setup requires the pinned CUDA-enabled PyTorch packages; see bootstrap.log and retry setup.' }
            12 { throw 'PyTorch cannot access a compatible NVIDIA GPU. Confirm this computer has a supported NVIDIA GPU and install or update its driver, then retry setup.' }
            13 { throw 'The NVIDIA CUDA computation check failed. See the preceding error in bootstrap.log. Check GPU support and the NVIDIA driver, then retry setup.' }
            default { throw "The GPU validation process failed unexpectedly (exit code $gpuCheckExitCode). See bootstrap.log for details." }
        }
    }

    Set-InstallStatus 3 'Downloading and installing ESPImageServer packages...'
    $applicationInstallArguments = @('-I', '-m', 'pip', 'install', '--upgrade', '--constraint', $constraintsFile)
    if ($UseCuda) { $applicationInstallArguments += @('--extra-index-url', $torchIndexUrl) }
    $applicationInstallArguments += @('-r', (Join-Path $stagedRuntime 'generation-requirements.txt'))
    if ((Invoke-LoggedExternal $runtimePython $applicationInstallArguments) -ne 0) {
        throw 'Unable to install the pinned ESPImageServer dependencies.'
    }
    Set-InstallStatus 3 'Checking installed package dependencies...'
    if ((Invoke-LoggedExternal $runtimePython @('-I', '-m', 'pip', 'check')) -ne 0) {
        throw 'The installed Python dependencies are inconsistent. See bootstrap.log and retry setup.'
    }
    Set-InstallStatus 3 'Checking Python imports and video tools...'
    Invoke-RuntimeSetup $runtimePython 'verify' $stagedRuntime

    Set-InstallStatus 4 'Recording installed package versions...'
    Write-ResolvedDependencyVersions $runtimePython
    Set-Content -LiteralPath (Join-Path $stagedRuntime 'runtime-ready.txt') -Value 'ready' -Encoding ascii

    Set-InstallStatus 5 'Saving your server settings...'
    $modelCachePath = Join-Path $env:LOCALAPPDATA 'ESPImageServer\models'
    New-Item -ItemType Directory -Force $modelCachePath | Out-Null
    $settingsFile = Join-Path $projectRoot 'server_settings.bat'
@"
@echo off
set "ESP_IMAGE_MODEL_CACHE=%LOCALAPPDATA%\ESPImageServer\models"
"@ | Set-Content -LiteralPath $settingsFile -Encoding ascii

    Set-InstallStatus 5 'Activating and checking the Python runtime...'
    Complete-RuntimePromotion $projectRoot $stagedRuntime {
        param($activeRuntime)
        Invoke-RuntimeSetup (Join-Path $activeRuntime 'python.exe') 'verify' $activeRuntime
    }
    $stagedRuntime = $null
    Write-InstallLog 'Models will download when you select one in ESPImageServer.'
    Set-InstallStatus 6 'Finishing installation...'
    Set-Content -LiteralPath $resultPath -Value 'success' -Encoding ascii
} catch {
    Write-InstallLog "ERROR: $($_.Exception.Message)"
    Set-InstallStatus 0 'Installation failed. See bootstrap.log for details.'
    Set-Content -LiteralPath $resultPath -Value 'failed' -Encoding ascii
    exit 1
} finally {
    if ($stagedRuntime -and -not (Test-Path -LiteralPath (Join-Path $projectRoot 'runtime-promotion.json'))) {
        try { Remove-StagedRuntime $projectRoot ([IO.Path]::GetFileName($stagedRuntime)) }
        catch { Write-InstallLog "Could not remove the incomplete runtime: $($_.Exception.Message)" }
    }
}
