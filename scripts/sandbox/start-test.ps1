[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$InstallerPath,
    [switch]$PrepareOnly
)

# Host launcher only: it copies test inputs and starts Windows Sandbox. It never
# executes the installer or the guest runner on the host.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows Sandbox tests require a Windows host.' }
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$installer = Get-Item -LiteralPath (Resolve-Path -LiteralPath $InstallerPath).ProviderPath
$filenameMatch = [regex]::Match($installer.Name, '^ESPImageServer-Setup-(\d+\.\d+\.\d+)\.exe$')
if ($installer.PSIsContainer -or -not $filenameMatch.Success -or $installer.Length -eq 0) {
    throw 'Choose an existing, nonempty ESPImageServer-Setup-X.Y.Z.exe installer.'
}
$version = $filenameMatch.Groups[1].Value
$header = [IO.File]::OpenRead($installer.FullName)
try {
    if ($header.ReadByte() -ne 0x4D -or $header.ReadByte() -ne 0x5A) {
        throw 'The selected installer does not have a Windows executable header.'
    }
} finally { $header.Dispose() }

$guestRunner = Join-Path $PSScriptRoot 'guest-runner.ps1'
if (-not (Test-Path -LiteralPath $guestRunner -PathType Leaf)) { throw 'The Sandbox guest runner is missing.' }
$tokens = $null
$parseErrors = $null
$null = [Management.Automation.Language.Parser]::ParseFile($guestRunner, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ('The guest runner has syntax errors: ' + ($parseErrors | Out-String)) }

$systemDirectory = if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    Join-Path $env:SystemRoot 'Sysnative'
} else { Join-Path $env:SystemRoot 'System32' }
$sandboxExecutable = Join-Path $systemDirectory 'WindowsSandbox.exe'
if (-not $PrepareOnly -and -not (Test-Path -LiteralPath $sandboxExecutable -PathType Leaf)) {
    throw 'Windows Sandbox is unavailable. Enable Windows Sandbox in Windows Features and restart, or use -PrepareOnly.'
}

$global:LASTEXITCODE = 1
$sourceCommit = (& git -C $projectRoot rev-parse --verify HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
    throw 'Could not identify the repository commit for the test manifest.'
}
$installerHash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$outputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist\sandbox-tests'))
if (-not $outputRoot.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Sandbox output escaped the project directory.'
}
# Do not redirect the writable guest share through an existing directory link.
foreach ($directory in @((Join-Path $projectRoot 'dist'), $outputRoot)) {
    if (Test-Path -LiteralPath $directory) {
        $item = Get-Item -LiteralPath $directory -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "The test output parent must be an ordinary directory: $directory"
        }
    }
}
$runDirectory = Join-Path $outputRoot $runId
$inputDirectory = Join-Path $runDirectory 'input'
$resultsDirectory = Join-Path $runDirectory 'results'
if (Test-Path -LiteralPath $runDirectory) { throw 'The unique Sandbox run directory already exists.' }
$null = New-Item -ItemType Directory -Path $inputDirectory, $resultsDirectory -Force
$copiedInstaller = Join-Path $inputDirectory $installer.Name
Copy-Item -LiteralPath $installer.FullName -Destination $copiedInstaller
Copy-Item -LiteralPath $guestRunner -Destination (Join-Path $inputDirectory 'guest-runner.ps1')
if ((Get-FileHash -LiteralPath $copiedInstaller -Algorithm SHA256).Hash -ine $installerHash -or
    (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash -ine $installerHash) {
    throw 'The installer changed or its test copy failed SHA-256 verification. Sandbox was not started.'
}
$manifest = [ordered]@{
    run_id = $runId
    installer_filename = $installer.Name
    installer_sha256 = $installerHash
    version = $version
    source_commit = $sourceCommit
}
[IO.File]::WriteAllText((Join-Path $inputDirectory 'manifest.json'),
    (ConvertTo-Json -InputObject $manifest), [Text.UTF8Encoding]::new($false))

# Capture guard/startup failures before the guest runner can start its transcript.
# This fixed guest-only script is stored in the WSB command, never run on the host.
$guestStartupScript = @'
$ErrorActionPreference = 'Stop';
$startupLog = 'C:\ESPInstallerTestResults\guest-startup.log';
try {
    ('Guest runner starting: ' + [DateTime]::UtcNow.ToString('o')) | Out-File -LiteralPath $startupLog -Encoding utf8;
    & 'C:\ESPInstallerTestInput\guest-runner.ps1' *>&1 | Out-File -LiteralPath $startupLog -Encoding utf8 -Append;
} catch {
    ($_ | Out-String) | Out-File -LiteralPath $startupLog -Encoding utf8 -Append;
    exit 1;
}
'@
$guestStartupScript = ($guestStartupScript -split '\r?\n' | ForEach-Object { $_.Trim() }) -join ' '
$guestLogonCommand = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command "' + $guestStartupScript + '"'

# XML escaping is required for profile/project paths containing '&', for example.
$inputXml = [Security.SecurityElement]::Escape($inputDirectory)
$resultsXml = [Security.SecurityElement]::Escape($resultsDirectory)
$commandXml = [Security.SecurityElement]::Escape($guestLogonCommand)
$configurationPath = Join-Path $runDirectory 'installer-test.wsb'
$configuration = @"
<Configuration>
  <vGPU>Enable</vGPU>
  <Networking>Enable</Networking>
  <MemoryInMB>8192</MemoryInMB>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$inputXml</HostFolder>
      <SandboxFolder>C:\ESPInstallerTestInput</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$resultsXml</HostFolder>
      <SandboxFolder>C:\ESPInstallerTestResults</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>$commandXml</Command>
  </LogonCommand>
</Configuration>
"@
$null = [xml]$configuration
[IO.File]::WriteAllText($configurationPath, $configuration, [Text.UTF8Encoding]::new($false))

$sandboxProcessId = $null
if (-not $PrepareOnly) {
    $sandbox = Start-Process -FilePath $sandboxExecutable -ArgumentList ('"' + $configurationPath + '"') -WindowStyle Hidden -PassThru
    $sandboxProcessId = $sandbox.Id
    $sandbox.Dispose()
    Write-Host 'Sandbox launcher started. Wait for results\status.json to report ready before sending test commands.'
} else {
    Write-Host 'Sandbox test inputs prepared; no Sandbox or installer was started.'
}
[pscustomobject]@{
    RunId = $runId
    RunDirectory = $runDirectory
    InputDirectory = $inputDirectory
    ResultsDirectory = $resultsDirectory
    ConfigurationPath = $configurationPath
    InstallerSha256 = $installerHash
    SandboxLauncherProcessId = $sandboxProcessId
    Launched = -not $PrepareOnly
}
