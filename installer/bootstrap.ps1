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
$supportedPythonCheck = "import platform, sys, sysconfig; raise SystemExit(0 if platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64' else 1)"

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
    if (-not $Command -or [string]::IsNullOrWhiteSpace($Command[0])) { return $false }
    $allArguments = @($Command | Select-Object -Skip 1) + @('-c', $supportedPythonCheck)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # A missing or broken executable must not inherit a previous successful
        # process exit code (for example, winget's).
        $global:LASTEXITCODE = 1
        & $Command[0] @allArguments *> $null
        return $global:LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-RegisteredPythonPaths {
    # PEP 514 registration is available immediately after installation, unlike
    # PATH inherited by this already-running setup process. Explicit views also
    # find x64 Python when setup was started from a 32-bit PowerShell process.
    foreach ($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryHive]::LocalMachine)) {
        foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
            $baseKey = $null
            try {
                $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
                foreach ($tag in @($SupportedPythonVersion, "$SupportedPythonVersion-64")) {
                    $installKey = $null
                    try {
                        $installKey = $baseKey.OpenSubKey("Software\Python\PythonCore\$tag\InstallPath")
                        if ($null -eq $installKey) { continue }
                        $executable = $installKey.GetValue('ExecutablePath')
                        if ($executable -is [string] -and -not [string]::IsNullOrWhiteSpace($executable)) {
                            $executable
                        }
                        $directory = $installKey.GetValue('')
                        if ($directory -is [string] -and -not [string]::IsNullOrWhiteSpace($directory)) {
                            Join-Path $directory 'python.exe'
                        }
                    } finally {
                        if ($null -ne $installKey) { $installKey.Dispose() }
                    }
                }
            } catch {
                # An unreadable registration must not hide other installations.
            } finally {
                if ($null -ne $baseKey) { $baseKey.Dispose() }
            }
        }
    }
}

function Get-DefaultPythonPaths {
    $versionDigits = $SupportedPythonVersion.Replace('.', '')
    if ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA "Programs\Python\Python$versionDigits\python.exe"
        Join-Path $env:LOCALAPPDATA "Programs\Python\Python$versionDigits-64\python.exe"
    }
    foreach ($programs in @($env:ProgramW6432, $env:ProgramFiles) | Select-Object -Unique) {
        if ($programs) {
            Join-Path $programs "Python$versionDigits\python.exe"
            Join-Path $programs "Python $SupportedPythonVersion\python.exe"
        }
    }
}

function Get-PythonCommand {
    $candidates = @(Get-RegisteredPythonPaths) + @(Get-DefaultPythonPaths)
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and
            [System.IO.Path]::IsPathRooted($candidate) -and
            (Test-Path -LiteralPath $candidate -PathType Leaf) -and
            (Test-SupportedPythonCommand @($candidate))) {
            return @($candidate)
        }
    }
    foreach ($name in @('py', 'python')) {
        $application = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        # Do not launch the Store's python.exe placeholder on a fresh account.
        if (-not $application -or $application.Source -like '*\Microsoft\WindowsApps\*') { continue }
        $command = @($application.Source)
        if ($name -eq 'py') { $command += "-$SupportedPythonVersion" }
        if (Test-SupportedPythonCommand $command) { return $command }
    }
    return $null
}

function Get-OrInstallPythonCommand {
    $command = Get-PythonCommand
    if ($command) { return $command }
    $winget = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        throw 'Python is missing and Windows Package Manager (winget) is unavailable.'
    }
    Write-InstallLog "Installing supported CPython $SupportedPythonVersion (x64)..."
    if ((Invoke-LoggedExternal $winget.Source @('install', '--id', 'Python.Python.3.12', '--exact', '--source', 'winget', '--scope', 'user', '--architecture', 'x64', '--accept-package-agreements', '--accept-source-agreements')) -ne 0) {
        throw 'Python installation failed.'
    }
    # Re-read registration and installation paths; no restart or PATH change is
    # required before this same setup process can create the virtual environment.
    $command = Get-PythonCommand
    if (-not $command) {
        throw "Python installation completed, but no working x64 CPython $SupportedPythonVersion was found in its registered location, standard installation folders, or PATH. Repair Python $SupportedPythonVersion and run setup again."
    }
    return $command
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
    $pythonCommand = Get-OrInstallPythonCommand
    Write-InstallLog "Using CPython $SupportedPythonVersion (x64): $($pythonCommand -join ' ')"
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
        Write-Host 'Checking NVIDIA CUDA with a small GPU computation...'
        if ((Invoke-LoggedExternal $venvPython @('-c', 'import torch; assert torch.version.cuda, "CPU-only PyTorch was installed"; assert torch.cuda.is_available(), "PyTorch cannot access a compatible NVIDIA GPU"; a = torch.ones((16, 16), device="cuda"); result = a @ a; torch.cuda.synchronize(); assert bool((result == 16).all().item()), "CUDA computation returned an incorrect result"; gpu = torch.cuda.get_device_properties(0); print(f"CUDA computation passed: {gpu.name}, {gpu.total_memory / (1024 ** 3):.1f} GiB total graphics memory, PyTorch {torch.__version__}")')) -ne 0) {
            throw 'The NVIDIA CUDA computation check failed. See the preceding error. Confirm this computer has a supported NVIDIA GPU, install or update its driver, and run setup again.'
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
    # Verify tokenizer and export imports as well as bundled FFmpeg before a
    # user spends time generating a video that cannot be encoded.
    if ((Invoke-LoggedExternal $venvPython @('-c', 'import imageio, imageio_ffmpeg, sentencepiece; print(imageio_ffmpeg.get_ffmpeg_exe())')) -ne 0) {
        throw 'Unable to verify the video tokenizer, MP4 exporter, and bundled FFmpeg dependencies.'
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
