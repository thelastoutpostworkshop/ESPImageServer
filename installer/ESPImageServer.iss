; Build with: iscc installer\ESPImageServer.iss
; The resulting ESPImageServer-Setup.exe is the maker-facing Windows installer.

#define AppName "ESPImageServer"
#define AppVersion "1.1.10"
#define AppPublisher "ESPImageServer"
#ifndef DesktopBuildOutput
  #define DesktopBuildOutput "..\desktop\release\win-unpacked"
#endif
#ifndef RuntimeBuildOutput
  #error Run build-installer.ps1 to prepare and supply the private Python runtime (RuntimeBuildOutput).
#endif

[Setup]
AppId={{18AA2901-70A7-4C30-9C55-6B78F51F6CC0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
SetupMutex=Global\ESPImageServerSetup
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=ESPImageServer-Setup-1.1.10
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\espimageserver-icon.ico
WizardImageFile=assets\wizard-sidebar.png
WizardSmallImageFile=assets\wizard-corner.png
WizardImageBackColor=#071426
WizardSmallImageBackColor=#FFFFFF
PrivilegesRequired=lowest
; CUDA 12.8 requires Windows 10 22H2; InitializeSetup also rejects Windows 11 21H2.
MinVersion=10.0.19045
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Files]
Source: "ensure-vc-runtime.ps1"; Flags: dontcopy
; Package only application source. Developer metadata beside the package must
; not become empty .egg-info directories that pip discovers as broken installs.
Source: "..\src\esp_image_server\*"; DestDir: "{app}\src\esp_image_server"; Excludes: "__pycache__,__pycache__\*,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\frontend\dist\*"; DestDir: "{app}\web"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#DesktopBuildOutput}\*"; DestDir: "{app}\desktop"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#RuntimeBuildOutput}\.venv\*"; DestDir: "{app}\runtime-base"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#RuntimeBuildOutput}\runtime-manifest.json"; DestDir: "{app}\runtime-base"; Flags: ignoreversion
Source: "{#RuntimeBuildOutput}\requirements-resolved.txt"; DestDir: "{app}\runtime-base"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "runtime-setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "verify-gpu.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap-supervisor.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "BootstrapProcess.cs"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints-cpu.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints-cuda.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "cleanup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "start_server.bat"; DestDir: "{app}"; DestName: "Start ESPImageServer.bat"; Flags: ignoreversion
Source: "assets\espimageserver-icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}\ESPImageServer"; Filename: "{app}\desktop\ESPImageServer.exe"; IconFilename: "{app}\espimageserver-icon.ico"
Name: "{userdesktop}\ESPImageServer"; Filename: "{app}\desktop\ESPImageServer.exe"; IconFilename: "{app}\espimageserver-icon.ico"; Tasks: desktopicon

[InstallDelete]
; Replace only the packaged base. The active runtime is promoted by bootstrap
; after all checks pass; settings, models, and creations are separate.
Type: filesandordirs; Name: "{app}\runtime-base"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\desktop\ESPImageServer.exe"; Description: "Start ESPImageServer"; Flags: nowait postinstall skipifsilent; Check: CanLaunchApplication

[Code]
type
  { Inno Setup 6 runs as a 32-bit process, including in 64-bit install mode.
    These are the Win32 STARTUPINFOW and PROCESS_INFORMATION layouts. }
  TBootstrapStartupInfo = record
    Size: Longword;
    Reserved, Desktop, Title: Longword;
    X, Y, XSize, YSize, XCountChars, YCountChars, FillAttribute: Longword;
    Flags: Longword;
    ShowWindow, ReservedSize: Word;
    ReservedData, StdInput, StdOutput, StdError: Longword;
  end;
  TBootstrapProcessInfo = record
    ProcessHandle, ThreadHandle, ProcessId, ThreadId: Longword;
  end;

var
  HardwarePage: TOutputMsgWizardPage;
  BootstrapProgress: TOutputMarqueeProgressWizardPage;
  BootstrapOutput: TNewMemo;
  BootstrapCancelButton: TNewButton;
  BootstrapCancelRequested, BootstrapCancelled: Boolean;
  BootstrapStarted, BootstrapSucceeded, BootstrapRunning: Boolean;
  BootstrapFailure, BootstrapControlDirectory: String;
  BootstrapProcessHandle: Longword;
  NvidiaSummary: String;
  VcRuntimeRunning, VcRuntimeReady, VcRuntimeRestartRequired: Boolean;

procedure Sleep(Milliseconds: Longword);
external 'Sleep@kernel32.dll stdcall';

function BootstrapCreateProcess(ApplicationName, CommandLine: String;
  ProcessAttributes, ThreadAttributes: Longword; InheritHandles: Boolean;
  CreationFlags, Environment: Longword; CurrentDirectory: String;
  var StartupInfo: TBootstrapStartupInfo; var ProcessInfo: TBootstrapProcessInfo): Boolean;
external 'CreateProcessW@kernel32.dll stdcall';

function BootstrapWaitForProcess(Handle, Milliseconds: Longword): Longword;
external 'WaitForSingleObject@kernel32.dll stdcall';

function BootstrapGetExitCode(Handle: Longword; var ExitCode: Longword): Boolean;
external 'GetExitCodeProcess@kernel32.dll stdcall';

function BootstrapTerminateProcess(Handle, ExitCode: Longword): Boolean;
external 'TerminateProcess@kernel32.dll stdcall';

function BootstrapCloseHandle(Handle: Longword): Boolean;
external 'CloseHandle@kernel32.dll stdcall';

function BootstrapCurrentProcessId: Longword;
external 'GetCurrentProcessId@kernel32.dll stdcall';

function BootstrapLastError: Longword;
external 'GetLastError@kernel32.dll stdcall';

function SetupTickCount: Int64;
external 'GetTickCount64@kernel32.dll stdcall';

#include "bootstrap-progress.iss"

function InitializeSetup: Boolean;
var
  WindowsVersion: TWindowsVersion;
begin
  GetWindowsVersionEx(WindowsVersion);
  Result := not ((WindowsVersion.Major = 10) and
    (WindowsVersion.Build >= 22000) and (WindowsVersion.Build < 22621));
  if not Result then
    SuppressibleMsgBox('ESPImageServer requires Windows 10 22H2 or Windows 11 22H2 or newer. Update Windows before running setup.',
      mbError, MB_OK, IDOK);
end;

function CanLaunchApplication: Boolean;
begin
  Result := BootstrapSucceeded;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if BootstrapStarted and not BootstrapSucceeded then begin
    if BootstrapCancelled then Result := 2 else Result := 1;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and BootstrapStarted and not BootstrapSucceeded then begin
    if BootstrapCancelled then
      WizardForm.FinishedHeadingLabel.Caption := 'Installation cancelled'
    else
      WizardForm.FinishedHeadingLabel.Caption := 'Installation incomplete';
    WizardForm.FinishedLabel.Caption := BootstrapFailure + #13#10#13#10 +
      'Run this installer again to repair or complete setup.' + #13#10#13#10 +
      'Setup log (if created): ' + ExpandConstant('{app}\bootstrap.log');
    WizardForm.RunList.Visible := False;
  end;
end;

procedure DetectNvidia;
var
  Detected: Boolean;
  ResultCode: Integer;
  ReportPath: String;
  ReportText: AnsiString;
begin
  ReportPath := ExpandConstant('{tmp}\nvidia-hardware.txt');
  Detected := Exec('nvidia-smi.exe', '--query-gpu=name,memory.total --format=csv,noheader --filename="' + ReportPath + '"', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if Detected then begin
    Detected := LoadStringFromFile(ReportPath, ReportText);
    if Detected then begin
      NvidiaSummary := Trim(String(ReportText));
      Detected := NvidiaSummary <> '';
    end;
  end;
  DeleteFile(ReportPath);
  if Detected then
    NvidiaSummary := 'Detected NVIDIA GPU(s), total graphics memory:' + #13#10 + NvidiaSummary
  else
    NvidiaSummary := 'No NVIDIA GPU could be detected through its driver. Install or update the NVIDIA driver to enable CUDA generation.';
end;

procedure BootstrapCancelClick(Sender: TObject);
begin
  if BootstrapCancelRequested then Exit;
  if MsgBox('Cancel ESPImageServer installation? The partial installation can be repaired by running this installer again.',
    mbConfirmation, MB_YESNO) = IDYES then begin
    BootstrapCancelRequested := True;
    BootstrapCancelButton.Enabled := False;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if VcRuntimeRunning then begin
    { The Microsoft prerequisite can use an elevated Windows Installer service.
      Let its transaction finish before allowing setup to close. }
    Cancel := False;
    Confirm := False;
    Exit;
  end;
  if BootstrapRunning then begin
    Cancel := False;
    Confirm := False;
    BootstrapCancelClick(nil);
  end;
end;

procedure StartBootstrapSupervisor;
var
  Executable, CommandLine: String;
  StartupInfo: TBootstrapStartupInfo;
  ProcessInfo: TBootstrapProcessInfo;
begin
  { Explicit native PowerShell path; no PATH lookup or shell association. }
  Executable := ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe');
  CommandLine := '"' + Executable + '" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\bootstrap-supervisor.ps1') + '" -BootstrapPath "' +
    ExpandConstant('{app}\bootstrap.ps1') + '" -ControlDirectory "' +
    BootstrapControlDirectory + '" -ParentProcessId ' + IntToStr(BootstrapCurrentProcessId) + ' -UseCuda';
  StartupInfo.Size := SizeOf(StartupInfo);
  StartupInfo.Reserved := 0; StartupInfo.Desktop := 0; StartupInfo.Title := 0;
  StartupInfo.X := 0; StartupInfo.Y := 0; StartupInfo.XSize := 0; StartupInfo.YSize := 0;
  StartupInfo.XCountChars := 0; StartupInfo.YCountChars := 0; StartupInfo.FillAttribute := 0;
  StartupInfo.Flags := 1; { STARTF_USESHOWWINDOW }
  StartupInfo.ShowWindow := SW_HIDE;
  StartupInfo.ReservedSize := 0; StartupInfo.ReservedData := 0;
  StartupInfo.StdInput := 0; StartupInfo.StdOutput := 0; StartupInfo.StdError := 0;
  if not BootstrapCreateProcess(Executable, CommandLine, 0, 0, False,
    $08000000, 0, ExpandConstant('{app}'), StartupInfo, ProcessInfo) then
    RaiseException('Could not start setup PowerShell: ' + SysErrorMessage(BootstrapLastError));
  BootstrapProcessHandle := ProcessInfo.ProcessHandle;
  BootstrapCloseHandle(ProcessInfo.ThreadHandle);
end;

function StopBootstrapSupervisor: Boolean;
begin
  Result := True;
  if BootstrapProcessHandle = 0 then Exit;
  if BootstrapWaitForProcess(BootstrapProcessHandle, 0) = 0 then Exit;
  { The supervisor owns a kill-on-close Job Object. If it cannot respond to
    cancellation, terminating it also closes that job and stops its children. }
  Result := BootstrapTerminateProcess(BootstrapProcessHandle, 2);
  if Result then
    Result := BootstrapWaitForProcess(BootstrapProcessHandle, 10000) = 0;
end;

procedure DeinitializeSetup;
begin
  if BootstrapProcessHandle <> 0 then begin
    if not StopBootstrapSupervisor then
      Log('Could not stop the setup supervisor during installer shutdown.');
    BootstrapCloseHandle(BootstrapProcessHandle);
    BootstrapProcessHandle := 0;
  end;
end;

procedure InitializeWizard;
begin
  DetectNvidia;
  HardwarePage := CreateOutputMsgPage(wpSelectDir,
    'Image and video generation',
    'Setup will install NVIDIA CUDA acceleration.',
    NvidiaSummary + #13#10#13#10 +
    'Generation requires a supported NVIDIA GPU and driver. Setup downloads the generation dependencies and tests a GPU computation. Memory needs vary by model; detection does not guarantee every model will fit. Models download when selected in the app.');
end;

function VcRuntimeStageMessage(const Stage: String): String;
begin
  case Stage of
    'download': Result := 'Downloading Microsoft Visual C++ runtime...';
    'verify': Result := 'Verifying the Microsoft runtime download...';
    'check': Result := 'Checking the installed Visual C++ runtime...';
    'install': Result := 'Installing Microsoft Visual C++ runtime...';
    'repair': Result := 'Repairing Microsoft Visual C++ runtime...';
    'validate': Result := 'Verifying the installed Visual C++ runtime...';
    'ready': Result := 'Microsoft Visual C++ runtime is ready.';
    'restart': Result := 'Microsoft Visual C++ runtime needs a Windows restart.';
  else
    Result := 'Starting the Microsoft Visual C++ runtime check...';
  end;
end;

function RunVcRuntimeHelper(const Executable, Parameters, WorkDirectory: String;
  Progress: TOutputMarqueeProgressWizardPage): Integer;
var
  StartupInfo: TBootstrapStartupInfo;
  ProcessInfo: TBootstrapProcessInfo;
  CommandLine, Stage, LastStage: String;
  StageText: AnsiString;
  StartedAt: Int64;
  ElapsedSeconds, LastSecond: Integer;
  WaitResult, ExitCode: Longword;
begin
  { Retain a handle to this helper only. It is deliberately not in the Python
    job: never terminate Microsoft's machine-wide prerequisite transaction. }
  CommandLine := '"' + Executable + '" ' + Parameters;
  StartupInfo.Size := SizeOf(StartupInfo);
  StartupInfo.Reserved := 0; StartupInfo.Desktop := 0; StartupInfo.Title := 0;
  StartupInfo.X := 0; StartupInfo.Y := 0; StartupInfo.XSize := 0; StartupInfo.YSize := 0;
  StartupInfo.XCountChars := 0; StartupInfo.YCountChars := 0; StartupInfo.FillAttribute := 0;
  StartupInfo.Flags := 1; { STARTF_USESHOWWINDOW }
  StartupInfo.ShowWindow := SW_HIDE;
  StartupInfo.ReservedSize := 0; StartupInfo.ReservedData := 0;
  StartupInfo.StdInput := 0; StartupInfo.StdOutput := 0; StartupInfo.StdError := 0;
  if not BootstrapCreateProcess(Executable, CommandLine, 0, 0, False,
    $08000000, 0, WorkDirectory, StartupInfo, ProcessInfo) then
    RaiseException('Could not start the Visual C++ runtime check: ' + SysErrorMessage(BootstrapLastError));
  BootstrapCloseHandle(ProcessInfo.ThreadHandle);
  StartedAt := SetupTickCount;
  LastSecond := -1;
  LastStage := '';
  Stage := '';
  try
    repeat
      WaitResult := BootstrapWaitForProcess(ProcessInfo.ProcessHandle, 0);
      if WaitResult = 0 then Break;
      if WaitResult <> $00000102 then { WAIT_TIMEOUT }
        RaiseException('Could not monitor the Visual C++ runtime check: ' + SysErrorMessage(BootstrapLastError));
      StageText := '';
      if LoadStringFromFile(WorkDirectory + '\progress.txt', StageText) then
        Stage := Trim(String(StageText));
      ElapsedSeconds := (SetupTickCount - StartedAt) div 1000;
      if (ElapsedSeconds <> LastSecond) or (Stage <> LastStage) then begin
        Progress.SetText(VcRuntimeStageMessage(Stage),
          Format('Elapsed: %d:%.2d. Approve the Microsoft prompt if asked.', [
            ElapsedSeconds div 60, ElapsedSeconds mod 60]));
        LastSecond := ElapsedSeconds;
        LastStage := Stage;
      end;
      { Animate also pumps wizard messages. Cancel and window-close requests
        still pass through the existing VcRuntimeRunning guard. }
      Progress.Animate;
      Sleep(100);
    until False;
    if not BootstrapGetExitCode(ProcessInfo.ProcessHandle, ExitCode) then
      RaiseException('Could not read the Visual C++ runtime check exit code.');
    Result := Integer(ExitCode);
  finally
    { The helper retains its own bounded wait; closing this observation handle
      must not kill it or an elevated Windows Installer service. }
    BootstrapCloseHandle(ProcessInfo.ProcessHandle);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  WorkDirectory, LogDirectory, CommandLine: String;
  Outcome, ErrorText: AnsiString;
  ResultCode: Integer;
  Progress: TOutputMarqueeProgressWizardPage;
  CancelWasEnabled: Boolean;
begin
  Result := '';
  if VcRuntimeRestartRequired then begin
    NeedsRestart := True;
    Result := 'Restart Windows to finish installing the Microsoft Visual C++ runtime, then run ESPImageServer setup again.';
    Exit;
  end;
  if VcRuntimeReady then Exit;
  WorkDirectory := ExpandConstant('{tmp}\vc-runtime');
  LogDirectory := ExpandConstant('{localappdata}\{#AppName}\setup-logs\') +
    ExtractFileName(ExpandConstant('{tmp}'));
  Progress := CreateOutputMarqueeProgressPage('Preparing Microsoft Visual C++ runtime',
    'This step may take several minutes. Please keep setup open.');
  Progress.SetText(VcRuntimeStageMessage(''),
    'Elapsed: 0:00. Approve the Microsoft prompt if asked.');
  VcRuntimeRunning := True;
  CancelWasEnabled := WizardForm.CancelButton.Enabled;
  WizardForm.CancelButton.Enabled := False;
  Progress.Show;
  Progress.Animate;
  try
    try
      if not ForceDirectories(WorkDirectory) then
        RaiseException('Could not create the runtime prerequisite work directory.');
      { A retry must never accept an earlier helper result. }
      DeleteFile(WorkDirectory + '\outcome.txt');
      DeleteFile(WorkDirectory + '\error.txt');
      DeleteFile(WorkDirectory + '\progress.txt');
      DeleteFile(WorkDirectory + '\progress.pending');
      if FileExists(WorkDirectory + '\outcome.txt') or FileExists(WorkDirectory + '\error.txt') or
        FileExists(WorkDirectory + '\progress.txt') or FileExists(WorkDirectory + '\progress.pending') then
        RaiseException('Could not clear the previous runtime prerequisite result.');
      ExtractTemporaryFile('ensure-vc-runtime.ps1');
      CommandLine := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{tmp}\ensure-vc-runtime.ps1') + '" -WorkDirectory "' +
        WorkDirectory + '" -LogDirectory "' + LogDirectory + '"';
      ResultCode := RunVcRuntimeHelper(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
        CommandLine, WorkDirectory, Progress);
      Outcome := '';
      ErrorText := '';
      LoadStringFromFile(WorkDirectory + '\outcome.txt', Outcome);
      LoadStringFromFile(WorkDirectory + '\error.txt', ErrorText);
      if (ResultCode = 3010) and (Trim(Outcome) = 'restart') then begin
        VcRuntimeRestartRequired := True;
        NeedsRestart := True;
        Result := 'Restart Windows to finish installing the Microsoft Visual C++ runtime, then run ESPImageServer setup again.';
      end else if (ResultCode = 0) and (Trim(Outcome) = 'success') then
        VcRuntimeReady := True
      else if Trim(ErrorText) <> '' then
        Result := UTF8Decode(ErrorText)
      else
        Result := 'The Visual C++ runtime check did not finish successfully (exit code ' + IntToStr(ResultCode) + ').';
    except
      Result := GetExceptionMessage;
    end;
    if Result <> '' then begin
      Result := Result + #13#10#13#10 + 'Runtime setup logs (if created): ' + LogDirectory;
      Log(Result);
    end;
  finally
    Progress.Hide;
    WizardForm.CancelButton.Enabled := CancelWasEnabled;
    VcRuntimeRunning := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { Inno Setup silently runs the previous uninstaller during an upgrade.
      Preserve the virtual environment, models, and user images in that case.
      A user-initiated uninstall removes the app environment and caches while
      preserving any user-selected image-library folder and its metadata. }
    if not UninstallSilent then
      Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{app}\cleanup.ps1') + '" -InstallRoot "' + ExpandConstant('{app}') + '"',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoUserInfoInfo + MemoDirInfo + MemoTypeInfo + MemoComponentsInfo +
    MemoGroupInfo + MemoTasksInfo + NewLine + 'Image and video generation:' + NewLine +
    Space + 'Hardware: NVIDIA CUDA acceleration' + NewLine +
    Space + NvidiaSummary + NewLine +
    Space + 'Microsoft Visual C++ runtime: checked before installation; Windows may request administrator approval' + NewLine +
    Space + 'Models: choose and download them later in the app';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultText, ErrorText: AnsiString;
  ExitCode, WaitResult: Longword;
  CancelPolls, Step, LastStep, ElapsedSeconds, LastSecond: Integer;
  Message, LastMessage: String;
  StartedAt: Int64;
  CancelSent, WizardCancelWasEnabled: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;

  BootstrapStarted := True;
  BootstrapSucceeded := False;
  BootstrapFailure := 'Setup did not finish.';
  BootstrapControlDirectory := ExpandConstant('{tmp}\bootstrap-control');

  BootstrapProgress := CreateOutputMarqueeProgressPage('Installing ESPImageServer',
    'Setting up the local image and video generation environment.');
  Message := 'Starting Python package setup...';
  Step := 0;
  LastStep := -1;
  LastMessage := '';
  LastSecond := -1;
  StartedAt := SetupTickCount;
  BootstrapProgress.SetText(Message, BootstrapElapsedCaption(0));
  BootstrapOutput := TNewMemo.Create(BootstrapProgress);
  BootstrapOutput.Left := 0;
  BootstrapOutput.Top := BootstrapProgress.ProgressBar.Top + BootstrapProgress.ProgressBar.Height + ScaleY(12);
  BootstrapOutput.Width := BootstrapProgress.SurfaceWidth;
  BootstrapOutput.Height := BootstrapProgress.SurfaceHeight - BootstrapOutput.Top - ScaleY(38);
  BootstrapOutput.ScrollBars := ssVertical;
  BootstrapOutput.ReadOnly := True;
  BootstrapOutput.Text := 'Large packages can take several minutes to download and install.' + #13#10 +
    'Models will download when you select them in the app.' + #13#10 + #13#10 +
    'Setup activity:';
  BootstrapOutput.Parent := BootstrapProgress.Surface;
  BootstrapCancelButton := TNewButton.Create(BootstrapProgress);
  BootstrapCancelButton.Caption := 'Cancel installation';
  BootstrapCancelButton.Top := BootstrapOutput.Top + BootstrapOutput.Height + ScaleY(8);
  BootstrapCancelButton.Width := WizardForm.CalculateButtonWidth([BootstrapCancelButton.Caption]);
  BootstrapCancelButton.OnClick := @BootstrapCancelClick;
  BootstrapCancelButton.Parent := BootstrapProgress.Surface;
  BootstrapCancelRequested := False;
  BootstrapCancelled := False;
  BootstrapProgress.Show;
  BootstrapRunning := True;
  WizardCancelWasEnabled := WizardForm.CancelButton.Enabled;
  WizardForm.CancelButton.Enabled := True;
  CancelSent := False;
  CancelPolls := 0;
  try
    try
      { The setup temp directory is unique; another run's result cannot complete it. }
      if not ForceDirectories(BootstrapControlDirectory) then
        RaiseException('Could not create the setup control directory.');
      StartBootstrapSupervisor;
      repeat
        WaitResult := BootstrapWaitForProcess(BootstrapProcessHandle, 0);
        if WaitResult = 0 then Break;
        if WaitResult <> $00000102 then { WAIT_TIMEOUT }
          RaiseException('Could not monitor the setup process: ' + SysErrorMessage(BootstrapLastError));

        if BootstrapCancelRequested then begin
          if not CancelSent then begin
            BootstrapProgress.SetText('Cancelling installation...', 'Stopping setup and its background processes.');
            if not SaveStringToFile(BootstrapControlDirectory + '\cancel.request', 'cancel', False) then
              RaiseException('Could not send the setup cancellation request.');
            CancelSent := True;
          end;
          CancelPolls := CancelPolls + 1;
          if CancelPolls >= 60 then begin { 15 seconds, including cleanup time }
            if not StopBootstrapSupervisor then
              RaiseException('Setup could not confirm its background processes stopped. Restart Windows before retrying setup.');
            BootstrapCancelled := True;
            RaiseException('Installation was cancelled. The unresponsive setup supervisor was stopped.');
          end;
        end;
        { This setup's temp directory cannot contain a previous run's status.
          Never let a late progress update overwrite cancellation feedback. }
        if not BootstrapCancelRequested then begin
          ReadBootstrapProgress(BootstrapControlDirectory + '\progress.txt', Step, Message);
          ElapsedSeconds := (SetupTickCount - StartedAt) div 1000;
          if (Step <> LastStep) or (Message <> LastMessage) then begin
            { Bound the activity history even if a worker repeats many updates. }
            if BootstrapOutput.Lines.Count >= 16 then BootstrapOutput.Lines.Delete(4);
            BootstrapOutput.Lines.Add(BootstrapProgressCaption(Step, Message));
          end;
          if (ElapsedSeconds <> LastSecond) or (Step <> LastStep) or (Message <> LastMessage) then
            BootstrapProgress.SetText(BootstrapProgressCaption(Step, Message),
              BootstrapElapsedCaption(ElapsedSeconds));
          LastStep := Step;
          LastMessage := Message;
          LastSecond := ElapsedSeconds;
        end;
        { Animate pumps messages, including Cancel, throughout long downloads. }
        BootstrapProgress.Animate;
        Sleep(250);
      until False;

      if not BootstrapGetExitCode(BootstrapProcessHandle, ExitCode) then
        RaiseException('Could not read the setup process exit code.');
      ResultText := '';
      ErrorText := '';
      LoadStringFromFile(BootstrapControlDirectory + '\outcome.txt', ResultText);
      LoadStringFromFile(BootstrapControlDirectory + '\error.txt', ErrorText);
      { A cleanup failure takes precedence over the user's cancellation intent. }
      if Trim(ResultText) = 'failed' then begin
        if Trim(ErrorText) <> '' then RaiseException(UTF8Decode(ErrorText));
        RaiseException('Setup or its background-process cleanup failed.');
      end;
      if BootstrapCancelRequested or (Trim(ResultText) = 'cancelled') then begin
        BootstrapCancelled := True;
        if Trim(ErrorText) <> '' then RaiseException(UTF8Decode(ErrorText));
        RaiseException('Installation was cancelled.');
      end;
      if (ExitCode <> 0) or (Trim(ResultText) <> 'success') then begin
        if Trim(ErrorText) <> '' then RaiseException(UTF8Decode(ErrorText));
        RaiseException('Setup PowerShell exited without successful completion (exit code ' +
          IntToStr(ExitCode) + '). It may have been blocked or stopped before it could write a result.');
      end;
      BootstrapSucceeded := True;
      BootstrapProgress.SetText('Installation complete.', 'ESPImageServer is ready to start.');
    except
      BootstrapFailure := GetExceptionMessage;
      Log('ESPImageServer setup: ' + BootstrapFailure);
    end;
  finally
    if not StopBootstrapSupervisor then begin
      BootstrapSucceeded := False;
      BootstrapCancelled := False;
      BootstrapFailure := 'Setup could not confirm its background processes stopped. Restart Windows before retrying setup.';
      Log(BootstrapFailure);
    end;
    if BootstrapProcessHandle <> 0 then begin
      BootstrapCloseHandle(BootstrapProcessHandle);
      BootstrapProcessHandle := 0;
    end;
    BootstrapRunning := False;
    WizardForm.CancelButton.Enabled := WizardCancelWasEnabled;
    BootstrapCancelButton.Visible := False;
    BootstrapProgress.Hide;
  end;
end;
