<#!
.SYNOPSIS
Builds the ESPImageServer Windows installer from the repository root.

.EXAMPLE
./build-installer.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$innoSetup = 'C:\Users\charles\AppData\Local\Programs\Inno Setup 6\ISCC.exe'

if (-not (Test-Path -LiteralPath $innoSetup)) {
    throw "Inno Setup compiler was not found at: $innoSetup"
}

function Invoke-BuildStep([string]$Name, [scriptblock]$Command) {
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    Invoke-BuildStep 'Building the web app' { npm --prefix frontend run build }
    Invoke-BuildStep 'Building the Electron application' { npm --prefix desktop run build }
    Invoke-BuildStep 'Compiling the installer' { & $innoSetup installer\ESPImageServer.iss }

    $version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    $installerPath = Join-Path $projectRoot "dist\ESPImageServer-Setup-$version.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Installer compilation completed but the expected file was not found: $installerPath"
    }
    Write-Host "`nInstaller created: $installerPath" -ForegroundColor Green
} finally {
    Pop-Location
}
