[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "ESPImageServer-cleanup-test-$([guid]::NewGuid().ToString('N'))"
$previousLocalAppData = $env:LOCALAPPDATA
$previousAppData = $env:APPDATA

try {
    $env:LOCALAPPDATA = Join-Path $testRoot 'local-app-data'
    $env:APPDATA = Join-Path $testRoot 'roaming-app-data'
    $localData = Join-Path $env:LOCALAPPDATA 'ESPImageServer'
    $customLibrary = Join-Path $testRoot 'my-custom-library'
    $installRoot = Join-Path $testRoot 'install'
    $marker = Join-Path $customLibrary 'do-not-delete.txt'
    $modelCache = Join-Path $localData 'models'

    New-Item -ItemType Directory -Force $customLibrary, (Join-Path $installRoot '.venv'), $modelCache | Out-Null
    Set-Content -LiteralPath $marker -Value 'This marker represents a user file.' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $modelCache 'model-cache-marker.txt') -Value 'This marker represents app-owned cache.' -Encoding utf8
    @{ image_library_location = $customLibrary } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $localData 'app_settings.json') -Encoding utf8

    & (Join-Path $PSScriptRoot 'cleanup.ps1') -InstallRoot $installRoot

    if (-not (Test-Path -LiteralPath $marker)) {
        throw 'Cleanup deleted the marker in the user-selected image library.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $localData 'app_settings.json'))) {
        throw 'Cleanup removed local metadata needed to reconnect the preserved library.'
    }
    if (Test-Path -LiteralPath (Join-Path $installRoot '.venv')) {
        throw 'Cleanup did not remove the app-owned virtual environment.'
    }
    if (Test-Path -LiteralPath $modelCache) {
        throw 'Cleanup did not remove the app-owned model cache.'
    }

    Write-Host 'PASS: custom image library marker and metadata were preserved; app-owned cache and virtual environment were removed.'
} finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    $env:APPDATA = $previousAppData
    if (Test-Path -LiteralPath $testRoot) {
        $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
        $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($resolvedTestRoot.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
        }
    }
}
