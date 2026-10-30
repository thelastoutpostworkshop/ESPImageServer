[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = 'Continue'
$localData = Join-Path $env:LOCALAPPDATA 'ESPImageServer'
$roamingData = Join-Path $env:APPDATA 'ESPImageServer'
$settingsPath = Join-Path $localData 'app_settings.json'
$defaultLibrary = Join-Path $localData 'images'
$customLibrary = $null

if (Test-Path -LiteralPath $settingsPath) {
    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        if ($settings.image_library_location) {
            $customLibrary = [System.IO.Path]::GetFullPath([string]$settings.image_library_location)
        }
    } catch {
        Write-Warning "Could not read image library settings: $($_.Exception.Message)"
    }
}

function Remove-ESPImageServerFolder([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    try {
        $resolved = [System.IO.Path]::GetFullPath($Path)
        $root = [System.IO.Path]::GetPathRoot($resolved)
        if ($resolved -eq $root) {
            Write-Warning "Refusing to remove a drive root: $resolved"
            return
        }
        if (Test-Path -LiteralPath $resolved) {
            Write-Host "Removing $resolved"
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    } catch {
        Write-Warning "Could not remove $Path : $($_.Exception.Message)"
    }
}

function Test-ESPImageServerSamePath([string]$First, [string]$Second) {
    if ([string]::IsNullOrWhiteSpace($First) -or [string]::IsNullOrWhiteSpace($Second)) { return $false }
    try {
        $firstFull = [System.IO.Path]::GetFullPath($First).TrimEnd('\', '/')
        $secondFull = [System.IO.Path]::GetFullPath($Second).TrimEnd('\', '/')
        return [string]::Equals($firstFull, $secondFull, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

# The default library is inside ESPImageServer's own local-data folder and is
# removed with the app. Any other configured location is user-selected data:
# preserve both it and its local metadata/settings so a reinstall can find it.
if ($customLibrary -and -not (Test-ESPImageServerSamePath $customLibrary $defaultLibrary)) {
    Write-Host "Preserving user-selected image library: $customLibrary"
    Write-Host "Preserving $localData because it contains that library's settings and index."
    Remove-ESPImageServerFolder (Join-Path $localData 'models')
    Remove-ESPImageServerFolder (Join-Path $localData 'videos')
    Remove-ESPImageServerFolder (Join-Path $localData 'display_sd_thumbnails')
} else {
    Remove-ESPImageServerFolder $localData
}
Remove-ESPImageServerFolder $roamingData

# Runtime folders are created by setup after Inno has copied the base payload,
# so Inno's file list alone cannot remove them. Reject links and stay inside
# the explicit installation directory; never traverse a user-data location.
$installFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\', '/')
if ($installFull -and $installFull -ne [IO.Path]::GetPathRoot($installFull).TrimEnd('\', '/')) {
    foreach ($directory in Get-ChildItem -LiteralPath $installFull -Directory -Force -ErrorAction SilentlyContinue) {
        if ($directory.Name -notmatch '^(runtime|runtime-base|runtime-(staging|backup)-[0-9a-f]{32})$') { continue }
        $runtimeFull = [IO.Path]::GetFullPath($directory.FullName)
        if ([IO.Path]::GetDirectoryName($runtimeFull) -ne $installFull) { continue }
        if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Write-Warning "Preserving linked runtime directory: $runtimeFull"
            continue
        }
        $links = @(Get-ChildItem -LiteralPath $runtimeFull -Recurse -Force | Where-Object {
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        })
        if ($links.Count) {
            Write-Warning "Preserving runtime directory containing linked files: $runtimeFull"
            continue
        }
        Remove-ESPImageServerFolder $runtimeFull
    }
    Remove-Item -LiteralPath (Join-Path $installFull 'runtime-promotion.json') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $installFull 'runtime-promotion.pending.json') -Force -ErrorAction SilentlyContinue
}
