[CmdletBinding()]
param()

# Guest-only runner. Never invoke this script on the host. The host mounts only
# a dedicated input directory (read-only) and this run's results directory.
$ErrorActionPreference = 'Stop'
$inputRoot = 'C:\ESPInstallerTestInput'
$resultsRoot = 'C:\ESPInstallerTestResults'
$workRoot = 'C:\ESPInstallerTest'
$guardPassed = $false
$transcribing = $false
$active = $null
$snapshotSequence = 0

function Write-JsonFile([string]$Path, $Value) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($resultsRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Result path escaped the dedicated results directory.'
    }
    $temporary = $full + '.pending'
    [IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $Value -Depth 12), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $full -Force
}

function Copy-SharedLog([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    $reader = $null
    $writer = $null
    try {
        $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Destination)) -Force
        $reader = [IO.File]::Open($Source, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $writer = [IO.File]::Open($Destination, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        $reader.CopyTo($writer)
    } catch {
        Write-Host "Log not available yet: $Source ($($_.Exception.Message))"
    } finally {
        if ($null -ne $writer) { $writer.Dispose() }
        if ($null -ne $reader) { $reader.Dispose() }
    }
}

function Get-ApplicationRegistration {
    foreach ($hive in @('HKCU', 'HKLM')) {
        $key = $hive + ':\Software\Microsoft\Windows\CurrentVersion\Uninstall\{18AA2901-70A7-4C30-9C55-6B78F51F6CC0}_is1'
        if (Test-Path -LiteralPath $key) {
            $record = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
            if ($null -eq $record) { continue }
            [pscustomobject]@{ hive = $hive; version = $record.DisplayVersion; install_location = $record.InstallLocation }
        }
    }
}

function Get-ApplicationProcesses {
    try {
        foreach ($process in Get-CimInstance Win32_Process) {
            $command = [string]$process.CommandLine
            $executable = [string]$process.ExecutablePath
            if ($command.IndexOf($installRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                $executable.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
                $executable.StartsWith($workRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
                # Do not export command lines or environment variables.
                [pscustomobject]@{ pid = $process.ProcessId; parent_pid = $process.ParentProcessId;
                    name = $process.Name; executable = $executable }
            }
        }
    } catch { Write-Host "Process inventory unavailable: $($_.Exception.Message)" }
}

function Save-Snapshot([string]$Label) {
    $script:snapshotSequence += 1
    $name = ('{0:D4}-{1}' -f $script:snapshotSequence, $Label)
    $destination = Join-Path $resultsRoot ('snapshots\' + $name)
    $null = New-Item -ItemType Directory -Path $destination -Force
    $files = @()
    foreach ($relative in @('bootstrap.log', 'installer_status.txt', 'installer_result.txt',
        'runtime-promotion.json', 'runtime-base\runtime-manifest.json',
        'runtime-base\requirements-resolved.txt', 'runtime\runtime-manifest.json', 'runtime\runtime-ready.txt')) {
        $source = Join-Path $installRoot $relative
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            $item = Get-Item -LiteralPath $source -ErrorAction SilentlyContinue
            if ($null -eq $item) { continue }
            $files += [pscustomobject]@{ path = $relative; bytes = $item.Length; modified_utc = $item.LastWriteTimeUtc.ToString('o') }
            Copy-SharedLog $source (Join-Path $destination $relative)
        }
    }
    $runtimeFolders = @()
    if (Test-Path -LiteralPath $installRoot -PathType Container) {
        $runtimeFolders = @(Get-ChildItem -LiteralPath $installRoot -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^runtime($|-base$|-staging-|-backup-)' } |
            ForEach-Object { $_.Name })
    }
    $runtimeLogs = Join-Path $env:LOCALAPPDATA 'ESPImageServer\setup-logs'
    if (Test-Path -LiteralPath $runtimeLogs -PathType Container) {
        foreach ($file in Get-ChildItem -LiteralPath $runtimeLogs -Recurse -File -Filter '*.log' -ErrorAction SilentlyContinue) {
            $relative = $file.FullName.Substring($runtimeLogs.Length).TrimStart('\')
            Copy-SharedLog $file.FullName (Join-Path $destination ('vc-runtime\' + $relative))
        }
    }
    $shortcuts = @()
    foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('DesktopDirectory'),
        [Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('CommonDesktopDirectory'))) {
        if ($folder -and (Test-Path -LiteralPath $folder -PathType Container)) {
            $shortcuts += @(Get-ChildItem -LiteralPath $folder -Filter '*ESPImageServer*.lnk' -Recurse -File -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName })
        }
    }
    Write-JsonFile (Join-Path $destination 'snapshot.json') ([ordered]@{
        run_id = $manifest.run_id; captured_utc = [DateTime]::UtcNow.ToString('o'); install_root = $installRoot;
        installation_exists = (Test-Path -LiteralPath $installRoot); files = $files; runtime_folders = $runtimeFolders;
        registration = @(Get-ApplicationRegistration); shortcuts = $shortcuts; owned_processes = @(Get-ApplicationProcesses)
    })
    return ('snapshots\' + $name)
}

function Write-CommandResult([string]$Id, [string]$Action, [string]$Status, $ExitCode, [string]$Message, [string]$Snapshot) {
    Write-JsonFile (Join-Path $resultsRoot ('command-results\' + $Id + '.json')) ([ordered]@{
        run_id = $manifest.run_id; id = $Id; action = $Action; status = $Status;
        updated_utc = [DateTime]::UtcNow.ToString('o'); exit_code = $ExitCode; message = $Message; snapshot = $Snapshot
    })
}

function Request-BootstrapCancellation {
    if ($null -eq $active -or $active.action -notlike 'install-*' -or $active.process.HasExited) {
        throw 'Cancellation requires this runner''s live installer process.'
    }
    $processes = @(Get-CimInstance Win32_Process)
    $byId = @{}
    foreach ($entry in $processes) { $byId[[int]$entry.ProcessId] = $entry }
    $supervisorPath = Join-Path $installRoot 'bootstrap-supervisor.ps1'
    $bootstrapPath = Join-Path $installRoot 'bootstrap.ps1'
    $powershellPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $candidates = @()
    foreach ($entry in $processes) {
        if ([string]$entry.ExecutablePath -ine $powershellPath) { continue }
        $line = [string]$entry.CommandLine
        if ($line -notmatch ('(?i)(?:^|\s)-File\s+"' + [regex]::Escape($supervisorPath) + '"(?:\s|$)') -or
            $line -notmatch ('(?i)(?:^|\s)-BootstrapPath\s+"' + [regex]::Escape($bootstrapPath) + '"(?:\s|$)')) { continue }
        $parentMatch = [regex]::Match($line, '(?i)(?:^|\s)-ParentProcessId\s+(\d+)(?:\s|$)')
        $controlMatch = [regex]::Match($line, '(?i)(?:^|\s)-ControlDirectory\s+"([^"]+)"(?:\s|$)')
        if (-not $parentMatch.Success -or -not $controlMatch.Success -or
            [int]$parentMatch.Groups[1].Value -ne [int]$entry.ParentProcessId) { continue }
        # Inno's outer executable can spawn an inner setup process. Require a
        # live ancestry chain back to our retained installer handle.
        $ancestor = [int]$entry.ParentProcessId
        $correlated = $false
        for ($depth = 0; $depth -lt 8; $depth++) {
            if ($ancestor -eq $active.process.Id) { $correlated = $true; break }
            if (-not $byId.ContainsKey($ancestor)) { break }
            $ancestor = [int]$byId[$ancestor].ParentProcessId
        }
        if (-not $correlated) { continue }
        $control = [IO.Path]::GetFullPath($controlMatch.Groups[1].Value)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if (-not $tempRoot.StartsWith($env:USERPROFILE + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not $control.StartsWith($tempRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { continue }
        $relative = $control.Substring($tempRoot.Length + 1)
        if ($relative -notmatch '^is-[A-Za-z0-9]+\.tmp\\bootstrap-control$' -or
            -not (Test-Path -LiteralPath $control -PathType Container)) { continue }
        foreach ($directory in @($control, [IO.Path]::GetDirectoryName($control), $tempRoot)) {
            if (((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Refusing a cancellation control directory containing a reparse point.'
            }
        }
        $candidates += [pscustomobject]@{ pid = [int]$entry.ProcessId; control = $control }
    }
    if ($candidates.Count -ne 1 -or $active.process.HasExited) {
        throw 'A unique live bootstrap supervisor owned by this installer was not found; retry when dependency setup starts.'
    }
    $supervisor = [Diagnostics.Process]::GetProcessById($candidates[0].pid)
    try {
        $null = $supervisor.Handle
        if ($supervisor.HasExited -or $active.process.HasExited) { throw 'Installer supervisor exited before cancellation.' }
        [IO.File]::WriteAllText((Join-Path $candidates[0].control 'cancel.request'), 'cancel', [Text.Encoding]::ASCII)
    } finally { $supervisor.Dispose() }
    return ('Requested cancellation of guest bootstrap supervisor ' + $candidates[0].pid + '. This exercises the bootstrap cancellation protocol, not a wizard click.')
}

function Start-TestProcess([string]$Id, [string]$Action) {
    $log = Join-Path $resultsRoot ($Id + '-inno.log')
    if ($Action -eq 'uninstall-interactive') {
        $executable = Join-Path $installRoot 'unins000.exe'
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'The guest application has no uninstaller.' }
        $arguments = '/NORESTART /LOG="' + $log + '"'
    } else {
        $source = Join-Path $inputRoot $manifest.installer_filename
        $expected = [string]$manifest.installer_sha256
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ine $expected) { throw 'Input installer hash does not match the manifest.' }
        $executable = Join-Path $workRoot $manifest.installer_filename
        Copy-Item -LiteralPath $source -Destination $executable -Force
        if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -ine $expected) { throw 'Guest installer copy failed hash verification.' }
        $arguments = '/SP- /NORESTART /DIR="' + $installRoot + '" /LOG="' + $log + '"'
        if ($Action -like 'install-silent*') { $arguments += ' /VERYSILENT /SUPPRESSMSGBOXES' }
    }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $executable
    $start.Arguments = $arguments
    $start.WorkingDirectory = $workRoot
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $Action -like 'install-silent*'
    $start.WindowStyle = if ($Action -like 'install-silent*') { [Diagnostics.ProcessWindowStyle]::Hidden } else { [Diagnostics.ProcessWindowStyle]::Normal }
    if ($Action -eq 'install-silent-with-hostile-python-env') {
        # Scope the deliberately invalid environment to this guest child only.
        $start.EnvironmentVariables['PYTHONHOME'] = Join-Path $workRoot 'does-not-exist-python-home'
        $start.EnvironmentVariables['PYTHONPATH'] = Join-Path $workRoot 'does-not-exist-python-path'
    }
    $process = [Diagnostics.Process]::Start($start)
    $null = $process.Handle
    return [pscustomobject]@{ id = $Id; action = $Action; process = $process; started_utc = [DateTime]::UtcNow }
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($env:USERNAME -ine 'WDAGUtilityAccount' -or ($identity.Name -split '\\')[-1] -ine 'WDAGUtilityAccount') {
        throw 'This runner is restricted to the Windows Sandbox WDAGUtilityAccount. It must never run on the host.'
    }
    foreach ($folder in @($inputRoot, $resultsRoot)) {
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw "Missing dedicated Sandbox mapping: $folder" }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $inputRoot 'manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.run_id -notmatch '^[A-Za-z0-9_-]{1,80}$' -or $manifest.version -notmatch '^\d+\.\d+\.\d+$' -or
        $manifest.installer_sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        $manifest.installer_filename -cne ('ESPImageServer-Setup-' + $manifest.version + '.exe')) {
        throw 'The test manifest contains an invalid run, version, filename, or checksum.'
    }
    $localData = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
    $expectedLocalData = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'AppData\Local'))
    if ($localData -ine $expectedLocalData -or [IO.Path]::GetFullPath($env:LOCALAPPDATA) -ine $localData) {
        throw 'Sandbox account data directories do not match; refusing to choose an installation path.'
    }
    $installRoot = Join-Path $localData 'Programs\ESPImageServer'
    if (-not $installRoot.StartsWith($env:USERPROFILE + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Installation path escaped the guest profile.' }
    $guardPassed = $true
    foreach ($folder in @($workRoot, (Join-Path $resultsRoot 'commands'), (Join-Path $resultsRoot 'command-results'), (Join-Path $resultsRoot 'snapshots'))) {
        $null = New-Item -ItemType Directory -Path $folder -Force
    }
    Start-Transcript -LiteralPath (Join-Path $resultsRoot 'runner.log') -Append | Out-Null
    $transcribing = $true
    $commandsAvailable = @()
    foreach ($name in @('python', 'python3', 'py', 'winget')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $commandsAvailable += [pscustomobject]@{ name = $name; found = ($null -ne $command);
            source = $(if ($command) { $command.Source } else { $null }); store_alias = ($command -and $command.Source -like '*\Microsoft\WindowsApps\*') }
    }
    $runtime = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
    $video = @()
    try { $video = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterCompatibility) } catch { Write-Host 'Video controller inventory unavailable.' }
    Write-JsonFile (Join-Path $resultsRoot 'environment.json') ([ordered]@{
        run_id = $manifest.run_id; account = $identity.Name; os_version = [Environment]::OSVersion.Version.ToString();
        is_64_bit_process = [Environment]::Is64BitProcess; install_root = $installRoot;
        command_availability = $commandsAvailable; vc_runtime = @{ installed = $runtime.Installed; version = $runtime.Version };
        video_controllers = $video; installer_sha256 = $manifest.installer_sha256
    })
    $null = Save-Snapshot 'initial'
    $finish = $false
    while (-not $finish) {
        if ($null -ne $active -and $active.process.HasExited) {
            $exitCode = $active.process.ExitCode
            $snapshot = Save-Snapshot ($active.id + '-exited')
            Write-CommandResult $active.id $active.action 'completed' $exitCode 'Process exited; inspect logs and snapshot to classify acceptance.' $snapshot
            $active.process.Dispose()
            $active = $null
        }
        foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $resultsRoot 'commands') -Filter '*.json' -File | Sort-Object Name)) {
            $id = $file.BaseName
            if ($id -notmatch '^[A-Za-z0-9_-]{1,80}$') { continue }
            $resultPath = Join-Path $resultsRoot ('command-results\' + $id + '.json')
            if (Test-Path -LiteralPath $resultPath) { continue }
            try { $command = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json } catch { continue }
            $action = [string]$command.action
            try {
                if ($command.id -cne $id -or $command.run_id -cne $manifest.run_id) { throw 'Command identity/run does not match this Sandbox session.' }
                if ($action -notin @('install-silent', 'install-silent-with-hostile-python-env', 'install-interactive', 'uninstall-interactive', 'cancel-bootstrap', 'collect', 'finish')) { throw 'Unsupported Sandbox test action.' }
                if ($action -eq 'collect') {
                    $snapshot = Save-Snapshot $id
                    Write-CommandResult $id $action 'completed' $null 'Snapshot collected.' $snapshot
                } elseif ($action -eq 'cancel-bootstrap') {
                    $message = Request-BootstrapCancellation
                    $snapshot = Save-Snapshot $id
                    Write-CommandResult $id $action 'completed' $null $message $snapshot
                } elseif ($action -eq 'finish') {
                    if ($null -ne $active) { throw 'Cannot finish while an installer or uninstaller is running.' }
                    $snapshot = Save-Snapshot $id
                    Write-CommandResult $id $action 'completed' $null 'Runner finished; Sandbox remains open.' $snapshot
                    $finish = $true
                    break
                } else {
                    if ($null -ne $active) { throw 'Another installer action is still running.' }
                    $active = Start-TestProcess $id $action
                    Write-CommandResult $id $action 'running' $null ('Started guest process ' + $active.process.Id) ''
                }
            } catch { Write-CommandResult $id $action 'failed' $null $_.Exception.Message '' }
        }
        Write-JsonFile (Join-Path $resultsRoot 'status.json') ([ordered]@{
            run_id = $manifest.run_id; state = $(if ($finish) { 'finished' } elseif ($active) { 'running' } else { 'ready' });
            heartbeat_utc = [DateTime]::UtcNow.ToString('o'); active_id = $(if ($active) { $active.id } else { $null });
            active_action = $(if ($active) { $active.action } else { $null });
            active_pid = $(if ($active) { $active.process.Id } else { $null });
            elapsed_seconds = $(if ($active) { [int]([DateTime]::UtcNow - $active.started_utc).TotalSeconds } else { 0 })
        })
        if (-not $finish) { Start-Sleep -Seconds 2 }
    }
} catch {
    if ($guardPassed) {
        Write-JsonFile (Join-Path $resultsRoot 'status.json') @{ state = 'failed'; message = $_.Exception.Message; updated_utc = [DateTime]::UtcNow.ToString('o') }
    }
    throw
} finally {
    if ($active) { $active.process.Dispose() }
    if ($transcribing) { Stop-Transcript | Out-Null }
}
