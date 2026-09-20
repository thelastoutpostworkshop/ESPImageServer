[CmdletBinding()]
param(
    [switch]$UseCuda
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$logPath = Join-Path $projectRoot 'bootstrap.log'
$statusPath = Join-Path $projectRoot 'installer_status.txt'
$resultPath = Join-Path $projectRoot 'installer_result.txt'
$SupportedPythonVersion = '3.12'
$supportedPythonCheck = "import platform, sys; raise SystemExit(0 if platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3, 12) else 1)"

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
    try {
        & $Command @Arguments 2>&1 | ForEach-Object {
            Write-InstallLog $_.ToString()
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $exitCode
}

function Set-InstallStatus([int]$Step, [string]$Message) {
    Write-SharedText $statusPath "$Step|$Message"
    Write-InstallLog "[$Step/6] $Message"
}

function Test-SupportedPythonCommand([string[]]$Command) {
    $allArguments = @($Command | Select-Object -Skip 1) + @('-c', $supportedPythonCheck)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command[0] @allArguments 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $launcherCommand = @('py', "-$SupportedPythonVersion")
        if (Test-SupportedPythonCommand $launcherCommand) { return $launcherCommand }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCommand = @('python')
        if (Test-SupportedPythonCommand $pythonCommand) { return $pythonCommand }
    }
    return $null
}

function Invoke-PythonCommand([string[]]$Command, [string[]]$Arguments) {
    $allArguments = @($Command | Select-Object -Skip 1) + $Arguments
    if ((Invoke-LoggedExternal $Command[0] $allArguments) -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Test-SupportedVirtualEnvironment([string]$Python) {
    if (-not (Test-Path $Python)) { return $false }
    return Test-SupportedPythonCommand @($Python)
}

function Write-ResolvedDependencyVersions([string]$Python) {
    Write-InstallLog 'Resolved Python package versions (pip freeze --all):'
    if ((Invoke-LoggedExternal $Python @('-m', 'pip', 'freeze', '--all')) -ne 0) {
        throw 'Unable to record the installed Python package versions.'
    }
}

try {
    $pythonCommand = Get-PythonCommand
    if (-not $pythonCommand) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Python is missing and Windows Package Manager (winget) is unavailable.'
        }
        Write-InstallLog "Installing supported CPython $SupportedPythonVersion..."
        if ((Invoke-LoggedExternal 'winget' @('install', '--id', 'Python.Python.3.12', '--exact', '--scope', 'user', '--accept-package-agreements', '--accept-source-agreements')) -ne 0) {
            throw 'Python installation failed.'
        }
        $pythonCommand = Get-PythonCommand
        if (-not $pythonCommand) { throw "CPython $SupportedPythonVersion was installed but is not yet available. Run the installer again to continue." }
    }
    Invoke-PythonCommand $pythonCommand @('-c', 'import platform, sys; print(platform.python_implementation(), sys.version)')

    $venvPath = Join-Path $projectRoot '.venv'
    $venvPython = Join-Path $venvPath 'Scripts\python.exe'
    Set-InstallStatus 1 'Creating the local Python environment...'
    if ((Test-Path $venvPath) -and -not (Test-SupportedVirtualEnvironment $venvPython)) {
        Write-InstallLog "Recreating the app-owned virtual environment because it is not CPython $SupportedPythonVersion."
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }
    if (-not (Test-Path $venvPython)) {
        Invoke-PythonCommand $pythonCommand @('-m', 'venv', $venvPath)
    }

    $constraintsFileName = if ($UseCuda) { 'constraints-cuda.txt' } else { 'constraints-cpu.txt' }
    $constraintsFile = Join-Path $projectRoot $constraintsFileName
    if (-not (Test-Path $constraintsFile)) {
        throw "The required dependency constraints file is missing: $constraintsFileName"
    }
    $torchIndexUrl = if ($UseCuda) { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
    Write-InstallLog "Using $constraintsFileName and the selected PyTorch wheel index."

    Set-InstallStatus 2 'Installing the pinned Python and PyTorch packages...'
    if ((Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', '--upgrade', '--constraint', $constraintsFile, 'pip')) -ne 0) {
        throw 'Unable to install the pinned pip version.'
    }
    # The selected PyTorch index supplies the CPU or CUDA wheels. PyPI remains
    # available for ordinary pinned Python dependencies that are not mirrored
    # in that wheel index, such as setuptools and filelock.
    if ((Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', '--upgrade', '--force-reinstall', '--constraint', $constraintsFile, '--index-url', $torchIndexUrl, '--extra-index-url', 'https://pypi.org/simple', 'torch', 'torchvision')) -ne 0) {
        throw 'Unable to install the pinned PyTorch and torchvision packages.'
    }
    if ($UseCuda) {
        # Do not finish a CUDA-selected install with a CPU-only fallback wheel.
        # This also gives a clear failure when the selected PC's NVIDIA driver
        # cannot make CUDA available to PyTorch.
        if ((Invoke-LoggedExternal $venvPython @('-c', 'import torch; assert torch.version.cuda, "CPU-only PyTorch was installed"; assert torch.cuda.is_available(), "PyTorch cannot access a compatible NVIDIA GPU"; print(f"CUDA PyTorch {torch.__version__} is ready on {torch.cuda.get_device_name(0)}")')) -ne 0) {
            throw 'CUDA was selected, but PyTorch could not use a compatible NVIDIA GPU. Update the NVIDIA driver or choose display management only (no AI generation).'
        }
    }

    Set-InstallStatus 3 'Installing pinned ESPImageServer packages...'
    $applicationInstallArguments = @('-m', 'pip', 'install', '--upgrade', '--constraint', $constraintsFile)
    if ($UseCuda) {
        # The editable install resolves torch again through the project's
        # dependencies, so make the CUDA wheel index available here as well.
        $applicationInstallArguments += @('--extra-index-url', $torchIndexUrl)
    }
    $applicationInstallArguments += @('--editable', $projectRoot)
    if ((Invoke-LoggedExternal $venvPython $applicationInstallArguments) -ne 0) {
        throw 'Unable to install the pinned ESPImageServer dependencies.'
    }
    # Video thumbnails use the FFmpeg binary bundled by imageio-ffmpeg. Verify
    # that the executable was installed now, rather than discovering a missing
    # dependency after the user saves their first generated video.
    if ((Invoke-LoggedExternal $venvPython @('-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')) -ne 0) {
        throw 'Unable to install the bundled FFmpeg tools needed for video thumbnails.'
    }

    Set-InstallStatus 4 'Recording installed package versions...'
    Write-ResolvedDependencyVersions $venvPython

    Set-InstallStatus 5 'Saving your server settings...'
    $modelCachePath = Join-Path $env:LOCALAPPDATA 'ESPImageServer\models'
    New-Item -ItemType Directory -Force $modelCachePath | Out-Null
    $env:ESP_IMAGE_MODEL_CACHE = $modelCachePath
    $settingsFile = Join-Path $projectRoot 'server_settings.bat'
@"
@echo off
set "ESP_IMAGE_MODEL_CACHE=%LOCALAPPDATA%\ESPImageServer\models"
"@ | Set-Content -Path $settingsFile -Encoding ascii

    Write-InstallLog 'Models will download when you select one in ESPImageServer.'
    Set-InstallStatus 6 'Environment is ready. Finishing installation...'
    Set-Content -Path $resultPath -Value 'success' -Encoding ascii
} catch {
    Write-InstallLog "ERROR: $($_.Exception.Message)"
    Set-InstallStatus 0 'Installation failed. See bootstrap.log for details.'
    Set-Content -Path $resultPath -Value 'failed' -Encoding ascii
    exit 1
}
