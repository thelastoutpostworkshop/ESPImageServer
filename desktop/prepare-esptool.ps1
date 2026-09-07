#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$toolDirectory = Join-Path $PSScriptRoot 'tools\esptool'
$executable = Join-Path $toolDirectory 'esptool-windows-amd64\esptool.exe'
$expectedExecutableHash = 'a5aeedac428eee8b45e55dd5ad8a0f4f62adf8bee74f9d02c81e3e088219eee9'
if (Test-Path -LiteralPath $executable) {
    if ((Get-FileHash -LiteralPath $executable).Hash.ToLowerInvariant() -ne $expectedExecutableHash) { throw 'Cached esptool checksum mismatch.' }
    exit 0
}
$archive = Join-Path ([IO.Path]::GetTempPath()) ('esptool-' + [guid]::NewGuid() + '.zip')
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/espressif/esptool/releases/download/v5.1.0/esptool-v5.1.0-windows-amd64.zip' -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f68a8f7728adfc59cd60f9424928199e76eac66372c7bdc23898aa32753a437a') {
    throw 'esptool archive checksum mismatch.'
}
$null = New-Item -ItemType Directory -Path $toolDirectory -Force
Expand-Archive -LiteralPath $archive -DestinationPath $toolDirectory -Force
if ((Get-FileHash -LiteralPath $executable).Hash.ToLowerInvariant() -ne $expectedExecutableHash) { throw 'Extracted esptool checksum mismatch.' }
Remove-Item -LiteralPath $archive
Write-Output "Prepared esptool 5.1.0 in $toolDirectory"
