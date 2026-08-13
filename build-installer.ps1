<#!
.SYNOPSIS
Builds the ESPImageServer Windows installer from the repository root.

.EXAMPLE
./build-installer.ps1
#>

[CmdletBinding()]
param(
    [switch]$SynchronizeOnly
)

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

function Set-DerivedVersion([string]$Path, [string]$Pattern, [scriptblock]$Replacement, [string]$Description) {
    $content = [System.IO.File]::ReadAllText($Path)
    $matches = [regex]::Matches($content, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if ($matches.Count -eq 0) {
        throw "Could not synchronize $Description in $Path."
    }
    $updated = [regex]::Replace($content, $Pattern, $Replacement, [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if ($updated -ne $content) {
        [System.IO.File]::WriteAllText($Path, $updated, [System.Text.UTF8Encoding]::new($false))
    }
}

Push-Location $projectRoot
try {
    $versionMatch = Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"'
    if (-not $versionMatch.Matches.Count) {
        throw 'Could not read the application version from pyproject.toml.'
    }
    $version = $versionMatch.Matches[0].Groups[1].Value
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        throw "The version in pyproject.toml must use major.minor.patch format; found '$version'."
    }

    Set-DerivedVersion (Join-Path $projectRoot 'desktop\package.json') '(?m)("version"\s*:\s*")[^"]+("\s*,)' {
        param($match) $match.Groups[1].Value + $version + $match.Groups[2].Value
    } 'Electron package version'
    Set-DerivedVersion (Join-Path $projectRoot 'desktop\package-lock.json') '(?s)\A(\{\s*"name"\s*:\s*"esp-image-server-desktop",\s*"version"\s*:\s*")[^"]+("\s*,)' {
        param($match) $match.Groups[1].Value + $version + $match.Groups[2].Value
    } 'Electron lockfile root version'
    Set-DerivedVersion (Join-Path $projectRoot 'desktop\package-lock.json') '(?s)("packages"\s*:\s*\{\s*""\s*:\s*\{\s*"name"\s*:\s*"esp-image-server-desktop",\s*"version"\s*:\s*")[^"]+("\s*,)' {
        param($match) $match.Groups[1].Value + $version + $match.Groups[2].Value
    } 'Electron lockfile package version'
    Set-DerivedVersion (Join-Path $projectRoot 'installer\ESPImageServer.iss') '(?m)(#define AppVersion ")[^"]+("$)' {
        param($match) $match.Groups[1].Value + $version + $match.Groups[2].Value
    } 'Inno Setup app version'
    Set-DerivedVersion (Join-Path $projectRoot 'installer\ESPImageServer.iss') '(?m)(OutputBaseFilename=ESPImageServer-Setup-)[^\r\n]+' {
        param($match) $match.Groups[1].Value + $version
    } 'Inno Setup output filename'

    if ($SynchronizeOnly) {
        Write-Host "Version $version synchronized from pyproject.toml." -ForegroundColor Green
        return
    }

    Invoke-BuildStep 'Building the web app' { npm --prefix frontend run build }
    Invoke-BuildStep 'Building the Electron application' { npm --prefix desktop run build }
    Invoke-BuildStep 'Compiling the installer' { & $innoSetup installer\ESPImageServer.iss }

    $installerPath = Join-Path $projectRoot "dist\ESPImageServer-Setup-$version.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Installer compilation completed but the expected file was not found: $installerPath"
    }
    Write-Host "`nInstaller created: $installerPath" -ForegroundColor Green
} finally {
    Pop-Location
}
