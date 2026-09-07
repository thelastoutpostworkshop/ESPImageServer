#Requires -Version 5.1
<#
.SYNOPSIS
Validates an Arduino ESP32 export and writes manifest.json beside its binaries.
.DESCRIPTION
Board and firmware version are explicit publisher declarations. The Arduino
export does not prove the application board target or version. This script
checks chip/flash configuration, files, ranges, and hashes, but does not certify
that binaries are credential-free. It never compiles, flashes, or erases a board.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [Parameter(Mandatory)]
    [ValidateSet('JC4827W543', 'ST7701_320X820', 'ESP32_C6_LCD_147', 'CHEAP_YELLOW_DISPLAY')]
    [string]$BoardTarget,
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$')]
    [string]$FirmwareVersion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$packageRoot = (Get-Item -LiteralPath $PackageDirectory).FullName
if (-not (Test-Path -LiteralPath $packageRoot -PathType Container)) {
    throw 'PackageDirectory must be a folder.'
}

function Get-PackageFile([string]$Name) {
    # Flat packages only: reject traversal, drive paths, ADS, and symlinks.
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') {
        throw "Invalid package filename: $Name"
    }
    $item = Get-Item -LiteralPath (Join-Path $packageRoot $Name)
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Expected a regular package file: $Name"
    }
    return $item
}

$boardChips = @{
    JC4827W543 = 'esp32s3'
    ST7701_320X820 = 'esp32s3'
    ESP32_C6_LCD_147 = 'esp32c6'
    CHEAP_YELLOW_DISPLAY = 'esp32'
}
$metadataFile = Get-PackageFile 'build.options.json'
$metadata = [IO.File]::ReadAllText($metadataFile.FullName) | ConvertFrom-Json
$fqbn = [string]$metadata.fqbn
if ($fqbn -notmatch '^esp32:esp32:(esp32s3|esp32c6|esp32):(.+)$') {
    throw 'Unsupported or missing ESP32 FQBN in build.options.json.'
}
$chip = $Matches[1]
$boardOptions = @{}
foreach ($option in ($Matches[2] -split ',')) {
    $pair = $option -split '=', 2
    if ($pair.Count -ne 2 -or $boardOptions.ContainsKey($pair[0])) {
        throw 'Invalid or repeated FQBN option.'
    }
    $boardOptions[$pair[0]] = $pair[1]
}
if ($chip -ne $boardChips[$BoardTarget]) {
    throw "Board $BoardTarget requires $($boardChips[$BoardTarget]); export uses $chip."
}

$argsFile = Get-PackageFile 'flash_args'
$lines = @([IO.File]::ReadAllLines($argsFile.FullName) |
    ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($lines.Count -lt 2) { throw 'flash_args contains no flash segments.' }
$tokens = $lines[0] -split '\s+'
$flash = @{}
if ($tokens.Count % 2 -ne 0) { throw 'Malformed flash options.' }
for ($i = 0; $i -lt $tokens.Count; $i += 2) {
    $key = $tokens[$i] -replace '_', '-'
    if ($key -notin @('--flash-mode', '--flash-freq', '--flash-size') -or $flash.ContainsKey($key)) {
        throw "Unsupported or repeated flash option: $key"
    }
    $flash[$key] = $tokens[$i + 1]
}
if ($flash.Count -ne 3 -or $flash['--flash-mode'] -notmatch '^(dio|dout|qio|qout)$' -or
    $flash['--flash-freq'] -notmatch '^[0-9]+m$' -or
    $flash['--flash-size'] -notmatch '^(1|2|4|8|16|32|64|128)MB$') {
    throw 'Expected explicit flash mode, frequency, and size in flash_args.'
}
$flashBytes = [long]($flash['--flash-size'] -replace 'MB$', '') * 1MB
if ($boardOptions['FlashSize'] -ne ($flash['--flash-size'] -replace 'MB$', 'M')) {
    throw 'Flash size differs between FQBN and flash_args.'
}
# FQBN FlashMode can name a build preset; only compare direct flash mode values.
if ($boardOptions['FlashMode'] -in @('dio', 'dout', 'qio', 'qout') -and
    $boardOptions['FlashMode'] -ne $flash['--flash-mode']) {
    throw 'Flash mode differs between FQBN and flash_args.'
}

$segments = @()
$seenNames = @{}
foreach ($line in $lines[1..($lines.Count - 1)]) {
    if ($line -notmatch '^(0x[0-9a-fA-F]+)\s+"?([A-Za-z0-9][A-Za-z0-9_.-]*\.bin)"?$') {
        throw 'Malformed flash segment; expected a hex offset and a local .bin filename.'
    }
    $offset = [Convert]::ToInt64($Matches[1].Substring(2), 16)
    $name = $Matches[2]
    if ($seenNames.ContainsKey($name)) { throw "Repeated binary: $name" }
    $seenNames[$name] = $true
    $binary = Get-PackageFile $name
    if ($binary.Length -eq 0 -or $offset % 4096 -ne 0 -or
        $offset -gt $flashBytes -or $binary.Length -gt ($flashBytes - $offset)) {
        throw "Empty, unaligned, or out-of-flash segment: $name"
    }
    $role = if ($name -match '\.bootloader\.bin$') { 'bootloader' }
        elseif ($name -match '\.partitions\.bin$') { 'partition_table' }
        elseif ($name -eq 'boot_app0.bin') { 'ota_data' }
        elseif ($name -match '\.ino\.bin$') { 'application' }
        else { throw "Unsupported binary role: $name" }
    $segments += [ordered]@{
        role = $role
        file = $name
        offset = ('0x{0:x}' -f $offset)
        size_bytes = $binary.Length
        sha256 = (Get-FileHash -LiteralPath $binary.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
foreach ($role in @('bootloader', 'partition_table', 'ota_data', 'application')) {
    if (@($segments | Where-Object { $_.role -eq $role }).Count -ne 1) {
        throw "Expected exactly one $role segment for first installation."
    }
}
$segments = @($segments | Sort-Object { [Convert]::ToInt64($_.offset.Substring(2), 16) })
$previousEnd = 0L
foreach ($segment in $segments) {
    $start = [Convert]::ToInt64($segment.offset.Substring(2), 16)
    if ($start -lt $previousEnd) { throw 'Flash segments overlap, including erased sectors.' }
    $previousEnd = $start + [long]([Math]::Ceiling($segment.size_bytes / 4096.0) * 4096)
}

$manifest = [ordered]@{
    schema_version = 1
    package_type = 'esp-image-display-firmware'
    installation_type = 'first_install'
    board_target = $BoardTarget
    firmware_version = $FirmwareVersion
    identity_source = 'publisher_declared'
    chip = $chip
    fqbn = $fqbn
    flash = [ordered]@{
        mode = $flash['--flash-mode']
        frequency = $flash['--flash-freq']
        size_bytes = $flashBytes
    }
    segments = $segments
}
# Validate everything before replacing an existing manifest. No absolute paths
# or arbitrary compiler flags from build.options.json are published.
$manifestPath = Join-Path $packageRoot 'manifest.json'
if (Test-Path -LiteralPath $manifestPath) { $null = Get-PackageFile 'manifest.json' }
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8) + "`n",
    [Text.UTF8Encoding]::new($false))
Write-Output "Generated $manifestPath ($BoardTarget, firmware $FirmwareVersion; $($segments.Count) binaries)."
