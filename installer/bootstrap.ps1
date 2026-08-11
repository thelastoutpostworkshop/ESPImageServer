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
Set-Content -Path $logPath -Value 'ESPImageServer setup log' -Encoding utf8

function Write-InstallLog([string]$Message) {
    Add-Content -Path $logPath -Value $Message -Encoding utf8
    Write-Host $Message
}

function Invoke-LoggedExternal([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments 2>&1 | ForEach-Object {
        Write-InstallLog $_.ToString()
    }
    return $LASTEXITCODE
}

function Set-InstallStatus([int]$Step, [string]$Message) {
    Set-Content -Path $statusPath -Value "$Step|$Message" -Encoding ascii
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
    if ($UseCuda -and -not $hasCuda) {
        if ($torchAvailable) { Invoke-LoggedExternal $venvPython @('-m', 'pip', 'uninstall', '-y', 'torch') | Out-Null }
        $torchExitCode = Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', 'torch', '--index-url', 'https://download.pytorch.org/whl/cu128')
    } elseif (-not $UseCuda -and ($hasCuda -or -not $torchAvailable)) {
        if ($torchAvailable) { Invoke-LoggedExternal $venvPython @('-m', 'pip', 'uninstall', '-y', 'torch') | Out-Null }
        $torchExitCode = Invoke-LoggedExternal $venvPython @('-m', 'pip', 'install', 'torch', '--index-url', 'https://download.pytorch.org/whl/cpu')
    }
    if ((($UseCuda -and -not $hasCuda) -or (-not $UseCuda -and ($hasCuda -or -not $torchAvailable))) -and $torchExitCode -ne 0) {
        throw 'Unable to install PyTorch.'
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
