#Requires -Version 5.1
# Uses synthetic files only. Does not compile or communicate with hardware.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$packager = Join-Path $PSScriptRoot 'package-firmware.ps1'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('esp-firmware-test-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $fixture
$utf8 = [Text.UTF8Encoding]::new($false)
$flashArgs = @'
--flash-mode dio --flash-freq 80m --flash-size 4MB
0x0 Test.ino.bootloader.bin
0x8000 Test.ino.partitions.bin
0xe000 boot_app0.bin
0x10000 Test.ino.bin
'@
foreach ($name in @('Test.ino.bootloader.bin', 'Test.ino.partitions.bin', 'boot_app0.bin', 'Test.ino.bin')) {
    [IO.File]::WriteAllBytes((Join-Path $fixture $name), [byte[]](1, 2, 3, 4))
}
[IO.File]::WriteAllText((Join-Path $fixture 'build.options.json'),
    '{"fqbn":"esp32:esp32:esp32s3:FlashMode=dio,FlashSize=4M"}', $utf8)
[IO.File]::WriteAllText((Join-Path $fixture 'flash_args'), $flashArgs, $utf8)
$null = & $packager -PackageDirectory $fixture -BoardTarget JC4827W543 -FirmwareVersion 1.2.3
$manifestPath = Join-Path $fixture 'manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.segments.Count -ne 4 -or $manifest.chip -ne 'esp32s3' -or
    $manifest.flash.size_bytes -ne 4194304 -or $manifest.firmware_version -ne '1.2.3') {
    throw 'Valid package metadata was not preserved.'
}
foreach ($segment in $manifest.segments) {
    if ($segment.sha256 -ne (Get-FileHash -LiteralPath (Join-Path $fixture $segment.file)).Hash.ToLowerInvariant()) {
        throw 'Incorrect binary hash.'
    }
}
$manifestHash = (Get-FileHash -LiteralPath $manifestPath).Hash

function Assert-Rejected([string]$Label, [string]$Arguments, [string]$Board = 'JC4827W543') {
    [IO.File]::WriteAllText((Join-Path $fixture 'flash_args'), $Arguments, $utf8)
    $rejected = $false
    try { $null = & $packager -PackageDirectory $fixture -BoardTarget $Board -FirmwareVersion 1.2.3 }
    catch { $rejected = $true }
    if (-not $rejected) { throw "Invalid package accepted: $Label" }
    if ((Get-FileHash -LiteralPath $manifestPath).Hash -ne $manifestHash) {
        throw "Failed validation changed the existing manifest: $Label"
    }
    Write-Output "PASS: $Label"
}

Write-Output 'PASS: valid package metadata and SHA-256 hashes'
Assert-Rejected 'wrong chip' $flashArgs 'ESP32_C6_LCD_147'
Assert-Rejected 'missing binary' ($flashArgs.Replace('Test.ino.bin', 'Missing.ino.bin'))
Assert-Rejected 'overlapping regions' ($flashArgs.Replace('0x10000', '0xe000'))
Assert-Rejected 'outside flash capacity' ($flashArgs.Replace('0x10000', '0x400000'))
Assert-Rejected 'path traversal' ($flashArgs.Replace('Test.ino.bin', '../Test.ino.bin'))
Assert-Rejected 'missing first-install component' ($flashArgs.Replace('0xe000 boot_app0.bin', ''))
Assert-Rejected 'conflicting flash size' ($flashArgs.Replace('4MB', '8MB'))
Assert-Rejected 'unrecognized flash command' ($flashArgs.Replace('--flash-mode dio', '--erase-all yes'))
Assert-Rejected 'conflicting direct flash mode' ($flashArgs.Replace('--flash-mode dio', '--flash-mode qio'))
[IO.File]::WriteAllText((Join-Path $fixture 'build.options.json'),
    '{"fqbn":"esp32:esp32:esp32c6:FlashMode=qio,FlashSize=4M"}', $utf8)
[IO.File]::WriteAllText((Join-Path $fixture 'flash_args'), $flashArgs, $utf8)
$null = & $packager -PackageDirectory $fixture -BoardTarget ESP32_C6_LCD_147 -FirmwareVersion 1.1.4
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.chip -ne 'esp32c6' -or $manifest.flash.mode -ne 'dio') {
    throw 'C6 QIO preset did not preserve the exported DIO flash mode.'
}
Write-Output 'PASS: C6 QIO preset exports DIO flash mode'
$manifestHash = (Get-FileHash -LiteralPath $manifestPath).Hash
Assert-Rejected 'C6 QIO preset rejects conflicting flash mode' ($flashArgs.Replace('--flash-mode dio', '--flash-mode qout')) 'ESP32_C6_LCD_147'
[IO.File]::WriteAllText((Join-Path $fixture 'build.options.json'),
    '{"fqbn":"esp32:esp32:esp32s3:FlashMode=qio,FlashSize=16M"}', $utf8)
$s3FlashArgs = $flashArgs.Replace('4MB', '16MB')
[IO.File]::WriteAllText((Join-Path $fixture 'flash_args'), $s3FlashArgs, $utf8)
$null = & $packager -PackageDirectory $fixture -BoardTarget ST7701_320X820 -FirmwareVersion 1.1.4
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.chip -ne 'esp32s3' -or $manifest.board_target -ne 'ST7701_320X820' -or
    $manifest.flash.mode -ne 'dio' -or $manifest.flash.size_bytes -ne 16MB) {
    throw 'S3 QIO preset did not preserve the exported DIO flash settings.'
}
Write-Output 'PASS: S3 QIO preset exports DIO flash mode with 16 MB flash'
$manifestHash = (Get-FileHash -LiteralPath $manifestPath).Hash
Assert-Rejected 'S3 QIO preset rejects conflicting flash mode' ($s3FlashArgs.Replace('--flash-mode dio', '--flash-mode qout')) 'ST7701_320X820'
# Remove only this explicitly created, verified temporary directory.
$resolvedFixture = [IO.Path]::GetFullPath($fixture)
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $resolvedFixture.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($resolvedFixture) -notlike 'esp-firmware-test-*') {
    throw 'Unexpected fixture cleanup path.'
}
Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
