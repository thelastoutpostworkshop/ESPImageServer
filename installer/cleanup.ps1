[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = 'Continue'
$localData = Join-Path $env:LOCALAPPDATA 'ESPImageServer'
$roamingData = Join-Path $env:APPDATA 'ESPImageServer'
$settingsPath = Join-Path $localData 'app_settings.json'
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

# A custom library is created only from an empty folder selected in Settings,
# so it is owned by ESPImageServer and safe to remove during a full uninstall.
Remove-ESPImageServerFolder $customLibrary
Remove-ESPImageServerFolder $localData
Remove-ESPImageServerFolder $roamingData
Remove-ESPImageServerFolder (Join-Path $InstallRoot '.venv')
