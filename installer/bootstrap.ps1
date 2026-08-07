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
Start-Transcript -Path $logPath -Append | Out-Null

Remove-Item $statusPath, $resultPath -Force -ErrorAction SilentlyContinue

function Set-InstallStatus([int]$Step, [string]$Message) {
    Set-Content -Path $statusPath -Value "$Step|$Message" -Encoding ascii
    Write-Host $Message
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
    & $Command[0] @($Command | Select-Object -Skip 1) @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Arguments -join ' ')" }
}

try {
    $pythonCommand = Get-PythonCommand
    if (-not $pythonCommand) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Python is missing and Windows Package Manager (winget) is unavailable.'
        }
        Write-Host 'Installing Python 3.12...'
        & winget install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
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
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'Unable to update pip.' }

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
        if ($torchAvailable) { & $venvPython -m pip uninstall -y torch | Out-Null }
        & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    } elseif (-not $UseCuda -and ($hasCuda -or -not $torchAvailable)) {
        if ($torchAvailable) { & $venvPython -m pip uninstall -y torch | Out-Null }
        & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install PyTorch.' }

    Set-InstallStatus 3 'Installing ESPImageServer packages...'
    & $venvPython -m pip install --editable $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install ESPImageServer dependencies.' }

    Set-InstallStatus 4 'Saving your server settings...'
    $settingsFile = Join-Path $projectRoot 'server_settings.bat'
    @"
@echo off
set "ESP_IMAGE_MODEL=$ModelId"
set "ESP_IMAGE_INFERENCE_STEPS=$InferenceSteps"
set "ESP_IMAGE_GUIDANCE_SCALE=$GuidanceScale"
set "ESP_IMAGE_GENERATION_WIDTH=$GenerationWidth"
set "ESP_IMAGE_GENERATION_HEIGHT=$GenerationHeight"
"@ | Set-Content -Path $settingsFile -Encoding ascii

    Set-InstallStatus 5 "Downloading and preparing $ModelId..."
    & $venvPython -c "from esp_image_server.config import Settings; from esp_image_server.generator import DiffusersGenerator; g = DiffusersGenerator(Settings.from_env()); g.load()"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to download the selected image model.' }
    Set-InstallStatus 6 'Model is ready. Finishing installation...'
    Set-Content -Path $resultPath -Value 'success' -Encoding ascii
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Set-InstallStatus 0 'Installation failed. See bootstrap.log for details.'
    Set-Content -Path $resultPath -Value 'failed' -Encoding ascii
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
