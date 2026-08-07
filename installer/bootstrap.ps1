[CmdletBinding()]
param(
    [switch]$UseCuda,
    [switch]$DownloadModel
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$logPath = Join-Path $projectRoot 'bootstrap.log'
Start-Transcript -Path $logPath -Append | Out-Null

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
    if (-not (Test-Path $venvPython)) {
        Write-Host 'Creating the local Python environment...'
        Invoke-PythonCommand $pythonCommand @('-m', 'venv', $venvPath)
    }

    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'Unable to update pip.' }

    $torchOutput = & $venvPython -c "import torch; print(torch.version.cuda or '')" 2>$null
    $torchAvailable = $LASTEXITCODE -eq 0
    $installedCuda = ($torchOutput | Out-String).Trim()
    $hasCuda = [bool]$installedCuda
    if ($UseCuda -and -not $hasCuda) {
        if ($torchAvailable) { & $venvPython -m pip uninstall -y torch | Out-Null }
        Write-Host 'Installing CUDA-enabled PyTorch...'
        & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    } elseif (-not $UseCuda -and ($hasCuda -or -not $torchAvailable)) {
        if ($torchAvailable) { & $venvPython -m pip uninstall -y torch | Out-Null }
        Write-Host 'Installing CPU PyTorch...'
        & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install PyTorch.' }

    Write-Host 'Installing ESPImageServer...'
    & $venvPython -m pip install --editable $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install ESPImageServer dependencies.' }

    if ($DownloadModel) {
        Write-Host 'Downloading the image model...'
        & $venvPython -c "from esp_image_server.config import Settings; from esp_image_server.generator import DiffusersGenerator; g = DiffusersGenerator(Settings.from_env()); g.load()"
        if ($LASTEXITCODE -ne 0) { throw 'Unable to download the image model.' }
    }
} finally {
    Stop-Transcript | Out-Null
}
