[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkDirectory,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

# Run from Inno PrepareToInstall, outside the cancellable Python bootstrap job.
# Microsoft's system-wide prerequisite may start an elevated Windows Installer
# service. Killing the Python job must never interrupt that transaction.
$ErrorActionPreference = 'Stop'
$VcRedistributableUrl = 'https://aka.ms/vc14/vc_redist.x64.exe'

function Write-VcRuntimeLog([string]$Message) {
    Add-Content -LiteralPath $script:VcRuntimeLogPath -Value $Message -Encoding UTF8
    Write-Host $Message
}

function Receive-VcRedistributable([string]$Destination) {
    $previousProtocol = [Net.ServicePointManager]::SecurityProtocol
    $previousProgress = $ProgressPreference
    try {
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocol -bor [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $VcRedistributableUrl -OutFile $Destination -UseBasicParsing -TimeoutSec 120
    } finally {
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
        $ProgressPreference = $previousProgress
    }
}

function Get-VcRedistributableVersion([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)' -or
        $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -ne 'Microsoft Corporation') {
        throw 'The Visual C++ runtime download does not have a valid Microsoft Corporation signature. It will not be run.'
    }
    # A valid Microsoft signature alone does not establish the product or CPU
    # architecture. Inspect signed version resources before executing anything.
    $info = (Get-Item -LiteralPath $Path).VersionInfo
    if ($info.ProductName -notmatch 'Microsoft Visual C\+\+.*Redistributable.*\(x64\)' -or $info.FileMajorPart -ne 14) {
        throw 'The downloaded file is not the Microsoft Visual C++ v14 x64 Redistributable. It will not be run.'
    }
    return [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
}

function Get-InstalledVcRuntimeVersion {
    $latest = $null
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $baseKey = $null
        $runtimeKey = $null
        try {
            $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
            $runtimeKey = $baseKey.OpenSubKey('SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')
            if ($null -eq $runtimeKey -or $runtimeKey.GetValue('Installed', 0) -ne 1) { continue }
            $candidate = $null
            if ([version]::TryParse(([string]$runtimeKey.GetValue('Version', '')).TrimStart('v', 'V'), [ref]$candidate) -and
                $candidate.Major -eq 14 -and ($null -eq $latest -or $candidate -gt $latest)) {
                $latest = $candidate
            }
        } catch {
            Write-VcRuntimeLog "Could not read the x64 Visual C++ runtime registration ($view): $($_.Exception.Message)"
        } finally {
            if ($null -ne $runtimeKey) { $runtimeKey.Dispose() }
            if ($null -ne $baseKey) { $baseKey.Dispose() }
        }
    }
    return $latest
}

function Test-VcRuntimeFiles([version]$RequiredVersion) {
    $systemDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $systemDirectory = Join-Path $env:SystemRoot 'Sysnative'
    }
    foreach ($name in @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')) {
        $path = Join-Path $systemDirectory $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
        $info = (Get-Item -LiteralPath $path).VersionInfo
        $version = [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
        if ($version -lt $RequiredVersion) { return $false }
    }
    return $true
}

function Start-VcRedistributableProcess([string]$Path, [string]$Operation, [string]$LogPath) {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Path
    $startInfo.Arguments = "$Operation /quiet /norestart /log `"$LogPath`""
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    return [Diagnostics.Process]::Start($startInfo)
}

function Invoke-VcRedistributable([string]$Path, [string]$Operation, [string]$LogPath) {
    $process = Start-VcRedistributableProcess $Path $Operation $LogPath
    try {
        # Let Microsoft's bootstrapper request elevation and finish its own
        # transaction. The app installer disables cancellation during this step.
        if (-not $process.WaitForExit(600000)) {
            # Do not kill a machine-wide MSI transaction. Return control to the
            # app wizard so the user can close it instead of waiting forever.
            throw "The Microsoft Visual C++ installer has not finished after 10 minutes and may still be running. Let it finish, or restart Windows, before retrying ESPImageServer setup. App installation has not started. See $LogPath."
        }
        return $process.ExitCode
    } finally {
        $process.Dispose()
    }
}

function Invoke-VcRuntimePrerequisite([string]$WorkDirectory, [string]$LogDirectory) {
    $download = Join-Path $WorkDirectory 'vc_redist.x64.exe'
    $installerLog = Join-Path $LogDirectory 'vc-redist.log'
    try {
        Write-VcRuntimeLog "Downloading Microsoft's current Visual C++ x64 runtime from $VcRedistributableUrl"
        try {
            Receive-VcRedistributable $download
        } catch {
            throw "Unable to download the Visual C++ x64 runtime. Check your internet connection and retry setup. $($_.Exception.Message)"
        }
        $required = Get-VcRedistributableVersion $download
        Write-VcRuntimeLog "Verified Microsoft Visual C++ x64 Redistributable version $required."
        $installed = Get-InstalledVcRuntimeVersion
        if ($null -ne $installed -and $installed -ge $required -and (Test-VcRuntimeFiles $required)) {
            Write-VcRuntimeLog "Visual C++ x64 runtime $installed is already installed."
            return 0
        }
        $operation = if ($null -ne $installed -and $installed -ge $required) { '/repair' } else { '/install' }
        Write-VcRuntimeLog "Preparing the Visual C++ x64 runtime ($operation). Approve the Windows administrator prompt if shown."
        $exitCode = Invoke-VcRedistributable $download $operation $installerLog
        Write-VcRuntimeLog "Microsoft runtime setup exited with code $exitCode. Details: $installerLog"
        if ($exitCode -eq 3010) {
            Write-VcRuntimeLog 'The Visual C++ runtime requires a Windows restart. Restart, then run ESPImageServer setup again.'
            return 3010
        }
        if ($exitCode -in @(1223, -2147023673, 1602, -2147023294)) {
            throw 'Visual C++ runtime installation was cancelled or administrator approval was declined. Run setup again and approve the Microsoft runtime installation.'
        }
        # Burn can return HRESULT_FROM_WIN32(ERROR_PRODUCT_VERSION), not just
        # the raw MSI code. Neither is success without checking the result.
        if ($exitCode -notin @(0, 1638, -2147023258)) {
            throw "Visual C++ x64 runtime installation failed (exit code $exitCode). See $installerLog."
        }
        $installed = Get-InstalledVcRuntimeVersion
        if ($null -eq $installed -or $installed -lt $required -or -not (Test-VcRuntimeFiles $required)) {
            throw "The required Visual C++ x64 runtime is still missing or incomplete. Repair the Microsoft Visual C++ x64 Redistributable and retry setup. See $installerLog."
        }
        Write-VcRuntimeLog "Visual C++ x64 runtime $installed is ready."
        return 0
    } finally {
        # The work directory belongs to this setup invocation. Never remove a
        # shared runtime or any installed application files during cleanup.
        if (Test-Path -LiteralPath $download -PathType Leaf) {
            Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
        }
    }
}

$exitCode = 1
try {
    if (-not [IO.Path]::IsPathRooted($WorkDirectory) -or -not [IO.Path]::IsPathRooted($LogDirectory)) {
        throw 'Runtime prerequisite work and log directories must be absolute.'
    }
    $null = New-Item -ItemType Directory -Path $WorkDirectory -Force
    $null = New-Item -ItemType Directory -Path $LogDirectory -Force
    $script:VcRuntimeLogPath = Join-Path $LogDirectory 'prerequisite.log'
    $exitCode = Invoke-VcRuntimePrerequisite $WorkDirectory $LogDirectory
    $outcome = if ($exitCode -eq 0) { 'success' } else { 'restart' }
    [IO.File]::WriteAllText((Join-Path $WorkDirectory 'outcome.txt'), $outcome, [Text.Encoding]::ASCII)
} catch {
    $exitCode = 1
    $message = $_.Exception.Message
    Write-Host "ERROR: $message"
    if (Test-Path -LiteralPath $LogDirectory -PathType Container) {
        Add-Content -LiteralPath (Join-Path $LogDirectory 'prerequisite.log') -Value "ERROR: $message" -Encoding UTF8
    }
    [IO.File]::WriteAllText((Join-Path $WorkDirectory 'error.txt'), $message, [Text.UTF8Encoding]::new($false))
}
exit $exitCode
