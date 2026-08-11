[CmdletBinding()]
param(
    [switch]$UseCuda,
    [Parameter(Mandatory = $true)]
    [string]$ModelId,
    [Parameter(Mandatory = $true)]
    [int]$InferenceSteps,
    [Parameter(Mandatory = $true)]
    [double]$GuidanceScale,
    [Parameter(Mandatory = $true)]
    [int]$GenerationWidth,
    [Parameter(Mandatory = $true)]
    [int]$GenerationHeight
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

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c 'import sys' 2>$null
        if ($LASTEXITCODE -eq 0) { return @('py', '-3.12') }
        return @('py')
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @('python') }
    return $null
}

function Invoke-PythonCommand([string[]]$Command, [string[]]$Arguments) {
    $allArguments = @($Command | Select-Object -Skip 1) + $Arguments
    if ((Invoke-LoggedExternal $Command[0] $allArguments) -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

try {
    $pythonCommand = Get-PythonCommand
    if (-not $pythonCommand) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Python is missing and Windows Package Manager (winget) is unavailable.'
        }
        Write-InstallLog 'Installing Python 3.12...'
        if ((Invoke-LoggedExternal 'winget' @('install', '--id', 'Python.Python.3.12', '--exact', '--scope', 'user', '--accept-package-agreements', '--accept-source-agreements')) -ne 0) {
            throw 'Python installation failed.'
        }
        $pythonCommand = Get-PythonCommand
        if (-not $pythonCommand) { throw 'Python was installed. Run the installer again to continue.' }
    }

    $venvPath = Join-Path $projectRoot '.venv'
    $venvPython = Join-Path $venvPath 'Scripts\python.exe'
    Set-InstallStatus 1 'Creating the local Python environment...'
    if (-not (Test-Path $venvPython)) {
        Invoke-PythonCommand $pythonCommand @('-m', 'venv', $venvPath)
    }

    Set-InstallStatus 2 'Installing the selected PyTorch build...'
    if ((Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip')) -ne 0) {
        throw 'Unable to update pip.'
    }

    # A new environment correctly returns a non-zero status here because torch is
    # not installed yet. Do not let PowerShell turn that expected probe into a
    # terminating error before the install branch below can run.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $torchOutput = & $venvPython -c "import torch; print(torch.version.cuda or '')" 2>$null
        $torchAvailable = $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $installedCuda = ($torchOutput | Out-String).Trim()
    $hasCuda = [bool]$installedCuda
    $torchIndexUrl = if ($UseCuda) { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
    $needsTorchInstall = ($UseCuda -and -not $hasCuda) -or (-not $UseCuda -and ($hasCuda -or -not $torchAvailable))
    if ($needsTorchInstall) {
        if ($torchAvailable) {
            Invoke-LoggedExternal $venvPython @('-m', 'pip', 'uninstall', '-y', 'torch', 'torchvision') | Out-Null
        }
        $torchExitCode = Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', 'torch', 'torchvision', '--index-url', $torchIndexUrl)
        if ($torchExitCode -ne 0) {
            throw 'Unable to install PyTorch and torchvision.'
        }
    } else {
        # Diffusers uses torchvision for image preprocessing. Install it separately
        # for environments created by earlier installer versions.
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $venvPython -c 'import torchvision' 2>$null
            $torchVisionAvailable = $LASTEXITCODE -eq 0
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if (-not $torchVisionAvailable) {
            if ((Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', 'torchvision', '--index-url', $torchIndexUrl)) -ne 0) {
                throw 'Unable to install torchvision.'
            }
        }
    }

    Set-InstallStatus 3 'Installing ESPImageServer packages...'
    if ((Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', '--editable', $projectRoot)) -ne 0) {
        throw 'Unable to install ESPImageServer dependencies.'
    }

    Set-InstallStatus 4 'Saving your server settings...'
    $modelCachePath = Join-Path $env:LOCALAPPDATA 'ESPImageServer\models'
    New-Item -ItemType Directory -Force $modelCachePath | Out-Null
    $env:ESP_IMAGE_MODEL_CACHE = $modelCachePath
    $settingsFile = Join-Path $projectRoot 'server_settings.bat'
@"
@echo off
set "ESP_IMAGE_MODEL=$ModelId"
set "ESP_IMAGE_MODEL_CACHE=%LOCALAPPDATA%\ESPImageServer\models"
set "ESP_IMAGE_INFERENCE_STEPS=$InferenceSteps"
set "ESP_IMAGE_GUIDANCE_SCALE=$GuidanceScale"
set "ESP_IMAGE_GENERATION_WIDTH=$GenerationWidth"
set "ESP_IMAGE_GENERATION_HEIGHT=$GenerationHeight"
"@ | Set-Content -Path $settingsFile -Encoding ascii

    Set-InstallStatus 5 "Downloading and preparing $ModelId..."
    if ((Invoke-LoggedExternal $venvPython @('-c', "from esp_image_server.config import Settings; from esp_image_server.generator import DiffusersGenerator; g = DiffusersGenerator(Settings.from_env()); g.load()")) -ne 0) {
        throw 'Unable to download the selected image model.'
    }
    Set-InstallStatus 6 'Model is ready. Finishing installation...'
    Set-Content -Path $resultPath -Value 'success' -Encoding ascii
} catch {
    Write-InstallLog "ERROR: $($_.Exception.Message)"
    Set-InstallStatus 0 'Installation failed. See bootstrap.log for details.'
    Set-Content -Path $resultPath -Value 'failed' -Encoding ascii
    exit 1
}
