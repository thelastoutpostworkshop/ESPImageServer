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

function Invoke-BuildStep([string]$Name, [scriptblock]$Command, [int]$RetryCount = 0) {
    for ($attempt = 0; $attempt -le $RetryCount; $attempt++) {
        Write-Host "`n==> $Name" -ForegroundColor Cyan
        & $Command
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -lt $RetryCount) {
            Write-Warning "$Name failed with exit code $LASTEXITCODE. Retrying in 3 seconds in case Windows is releasing a locked build file."
            Start-Sleep -Seconds 3
        }
    }
    throw "$Name failed with exit code $LASTEXITCODE. Close ESPImageServer if it is running, then try again."
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
    Set-DerivedVersion (Join-Path $projectRoot 'installer\ESPImageServer.iss') '(?m)(#define AppVersion ")[^"]+("(?=\r?$))' {
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
    # Build to a fresh staging directory every time. This avoids an antivirus
    # scanner or previous Electron run keeping the old app.asar locked.
    $desktopBuildOutput = Join-Path $projectRoot ("desktop\release\installer-staging-" + [guid]::NewGuid().ToString('N'))
    $desktopAppOutput = Join-Path $desktopBuildOutput 'win-unpacked'
    Invoke-BuildStep 'Building the Electron application' {
        Push-Location (Join-Path $projectRoot 'desktop')
        try {
            & .\node_modules\.bin\electron-builder.cmd --win --x64 --dir "--config.directories.output=$desktopBuildOutput"
        } finally {
            Pop-Location
        }
    }
    if (-not (Test-Path -LiteralPath $desktopAppOutput)) {
        throw "Electron packaging completed but the expected staging folder was not found: $desktopAppOutput"
    }
    Invoke-BuildStep 'Compiling the installer' { & $innoSetup "/DDesktopBuildOutput=$desktopAppOutput" installer\ESPImageServer.iss }

    $installerPath = Join-Path $projectRoot "dist\ESPImageServer-Setup-$version.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Installer compilation completed but the expected file was not found: $installerPath"
    }
    Write-Host "`nInstaller created: $installerPath" -ForegroundColor Green
} finally {
    Pop-Location
}
