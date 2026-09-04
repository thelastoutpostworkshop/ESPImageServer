<#
.SYNOPSIS
Builds the frontend and starts ESPImageServer from this repository.

.EXAMPLE
.\start-server.ps1

.EXAMPLE
.\start-server.ps1 -OpenBrowser
#>

[CmdletBinding()]
param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$serverPort = if ([string]::IsNullOrWhiteSpace($env:ESP_IMAGE_PORT)) { 8000 } else { $env:ESP_IMAGE_PORT }

if (-not (Test-Path -LiteralPath $python)) {
    throw "The project Python environment was not found at: $python"
}

function Invoke-ProjectCommand([string]$Name, [scriptblock]$Command) {
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    Invoke-ProjectCommand 'Building the web app' { npm --prefix frontend run build }

    if ($OpenBrowser) {
        $env:ESP_IMAGE_OPEN_BROWSER = '1'
    } else {
        Remove-Item Env:ESP_IMAGE_OPEN_BROWSER -ErrorAction SilentlyContinue
    }

    Write-Host "`n==> Starting ESPImageServer" -ForegroundColor Cyan
    Write-Host "Open http://127.0.0.1:$serverPort in a browser after the server is ready." -ForegroundColor Green
    & $python -m esp_image_server
    if ($LASTEXITCODE -ne 0) {
        throw "ESPImageServer stopped with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
