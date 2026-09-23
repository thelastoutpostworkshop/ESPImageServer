<#!
.SYNOPSIS
Builds the ESPImageServer Windows installer from the repository root.

.EXAMPLE
./build-installer.ps1
#>

[CmdletBinding()]
param(
    [switch]$SynchronizeOnly,
    [string]$InnoSetupPath
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$innoSetup = $InnoSetupPath

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

function Invoke-InstallerCompile([string]$Compiler, [string]$ScriptPath, [string]$DesktopOutput, [string]$OutputRoot, [string]$Version) {
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        # Resource updates can collide with scanners or a previous setup process.
        # Compile to a new path on every attempt; publish only a finished EXE.
        $stagingDirectory = Join-Path $OutputRoot ('installer-staging-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stagingDirectory -Force | Out-Null
        Write-Host "`n==> Compiling the installer (attempt $($attempt + 1) of 3)" -ForegroundColor Cyan
        & $Compiler "/O$stagingDirectory" "/DDesktopBuildOutput=$DesktopOutput" $ScriptPath | Out-Host
        if ($LASTEXITCODE -eq 0) {
            $stagedInstaller = Join-Path $stagingDirectory "ESPImageServer-Setup-$Version.exe"
            if (-not (Test-Path -LiteralPath $stagedInstaller)) {
                throw "Compiler reported success but did not create $stagedInstaller"
            }
            return $stagedInstaller
        }
        if ($attempt -lt 2) {
            Write-Warning 'Installer compilation failed. Retrying with a fresh output path in 3 seconds. See the compiler error above.'
            Start-Sleep -Seconds 3
        }
    }
    throw 'Installer compilation failed after 3 attempts. For EndUpdateResource errors, another process or security scanner may be interfering with the output file. Check the compiler output and Windows Security protection history. The previous installer has not been replaced.'
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

    if (-not $innoSetup) {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
        )
        $innoSetup = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $innoSetup -or -not (Test-Path -LiteralPath $innoSetup)) {
        throw 'Inno Setup compiler was not found. Install Inno Setup 6 or pass -InnoSetupPath.'
    }

    Invoke-BuildStep 'Preparing the bundled flashing tool' { npm --prefix desktop run prepare:esptool }
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
    $stagedInstaller = Invoke-InstallerCompile $innoSetup (Join-Path $projectRoot 'installer\ESPImageServer.iss') $desktopAppOutput (Join-Path $projectRoot 'dist') $version
    $installerPath = Join-Path $projectRoot "dist\ESPImageServer-Setup-$version.exe"
    for ($copyAttempt = 0; $copyAttempt -lt 3; $copyAttempt++) {
        try {
            Copy-Item -LiteralPath $stagedInstaller -Destination $installerPath -Force
            break
        } catch {
            if ($copyAttempt -eq 2) {
                throw "Installer compiled successfully at $stagedInstaller but could not be copied to $installerPath. Close any running copy of that installer and retry copying it. $($_.Exception.Message)"
            }
            Start-Sleep -Seconds 3
        }
    }
    Write-Host "`nInstaller created: $installerPath" -ForegroundColor Green
} finally {
    Pop-Location
}
