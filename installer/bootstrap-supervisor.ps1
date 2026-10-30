[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BootstrapPath,
    [Parameter(Mandatory = $true)][string]$ControlDirectory,
    [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$ParentProcessId,
    [switch]$UseCuda
)

$ErrorActionPreference = 'Stop'
$outcome = 'failed'
$failure = ''
$exitCode = 1
$worker = $null
$parentProcess = $null
$cancelPath = Join-Path $ControlDirectory 'cancel.request'

function Test-CancellationRequested {
    return (Test-Path -LiteralPath $cancelPath) -or $parentProcess.HasExited
}

try {
    if (-not [System.IO.Path]::IsPathRooted($BootstrapPath) -or
        -not [System.IO.Path]::IsPathRooted($ControlDirectory)) {
        throw 'Bootstrap and control paths must be absolute.'
    }
    if (-not (Test-Path -LiteralPath $ControlDirectory -PathType Container)) {
        throw 'The installer control directory is missing.'
    }
    if (-not (Test-Path -LiteralPath $BootstrapPath -PathType Leaf)) {
        throw "The bootstrap script is missing: $BootstrapPath"
    }
    try {
        $parentProcess = [System.Diagnostics.Process]::GetProcessById($ParentProcessId)
        # Force a retained native handle now, so PID reuse cannot change which
        # installer process we monitor later.
        $null = $parentProcess.Handle
    } catch {
        $outcome = 'cancelled'
        $exitCode = 2
        throw 'The installer process is no longer available. Bootstrap was not started.'
    }

    if (Test-CancellationRequested) {
        $outcome = 'cancelled'
        $exitCode = 2
        $failure = 'Installation was cancelled before bootstrap started.'
    } else {
        $bootstrapDirectory = [System.IO.Path]::GetDirectoryName($BootstrapPath)
        $resultPath = Join-Path $bootstrapDirectory 'installer_result.txt'
        # Never accept a previous run's completion marker. Failure to remove it
        # is an installation error, not permission to continue with stale state.
        if (Test-Path -LiteralPath $resultPath) {
            if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
                throw "The bootstrap result path is not a file: $resultPath"
            }
            Remove-Item -LiteralPath $resultPath -Force
        }
        if (Test-Path -LiteralPath $resultPath) {
            throw "Could not remove the previous bootstrap result: $resultPath"
        }
        Add-Type -Path (Join-Path $PSScriptRoot 'BootstrapProcess.cs')
        if (Test-CancellationRequested) {
            $outcome = 'cancelled'
            $exitCode = 2
            $failure = 'Installation was cancelled before bootstrap started.'
        } else {
            $arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $BootstrapPath,
                '-ProgressDirectory', $ControlDirectory)
            if ($UseCuda) { $arguments += '-UseCuda' }
            $worker = [EspImageServer.Setup.BootstrapProcess]::Start(
                (Join-Path $PSHOME 'powershell.exe'), [string[]]$arguments,
                $bootstrapDirectory)

            while (-not $worker.HasExited) {
                if (Test-CancellationRequested) {
                    $outcome = 'cancelled'
                    $exitCode = 2
                    $failure = 'Installation was cancelled. The bootstrap process tree was stopped.'
                    break
                }
                Start-Sleep -Milliseconds 100
            }
            if ($outcome -ne 'cancelled') {
                if (Test-CancellationRequested) {
                    $outcome = 'cancelled'
                    $exitCode = 2
                    $failure = 'Installation was cancelled as bootstrap finished.'
                } elseif ($worker.ExitCode -ne 0) {
                    throw "Bootstrap PowerShell exited with code $($worker.ExitCode). See bootstrap.log in the installation folder if it was created."
                } elseif (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
                    throw 'Bootstrap PowerShell exited without a completion result. See bootstrap.log in the installation folder if it was created.'
                } elseif ([System.IO.File]::ReadAllText($resultPath).Trim() -cne 'success') {
                    throw 'Bootstrap did not report successful completion. See bootstrap.log in the installation folder for details.'
                } else {
                    $outcome = 'success'
                    $exitCode = 0
                }
            }
        }
    }
} catch {
    $failure = $_.Exception.Message
} finally {
    if ($null -ne $worker) {
        try {
            # Even a completed worker can leave descendants alive. Drain the
            # entire owned tree before making any completion result visible.
            $worker.TerminateAndWait(10000)
        } catch {
            $outcome = 'failed'
            $exitCode = 1
            $failure = "$failure Bootstrap cleanup failed: $($_.Exception.Message)"
        } finally {
            $worker.Dispose()
        }
    }
    if ($null -ne $parentProcess) { $parentProcess.Dispose() }
}

try {
    if ($failure) {
        [System.IO.File]::WriteAllText((Join-Path $ControlDirectory 'error.txt'), $failure,
            (New-Object System.Text.UTF8Encoding($false)))
    }
    # The caller also waits for this supervisor process to exit. A marker alone
    # is never evidence that setup, logging, and child cleanup are complete.
    [System.IO.File]::WriteAllText((Join-Path $ControlDirectory 'outcome.txt'), $outcome,
        [System.Text.Encoding]::ASCII)
} catch {
    Write-Error "Could not report bootstrap completion: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
exit $exitCode
