; Build with: iscc installer\ESPImageServer.iss
; The resulting ESPImageServer-Setup.exe is the maker-facing Windows installer.

#define AppName "ESPImageServer"
#define AppVersion "1.1.10"
#define AppPublisher "ESPImageServer"
#ifndef DesktopBuildOutput
  #define DesktopBuildOutput "..\desktop\release\win-unpacked"
#endif

[Setup]
AppId={{18AA2901-70A7-4C30-9C55-6B78F51F6CC0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
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
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Files]
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__\*,*.pyc,*.egg-info\*"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\frontend\dist\*"; DestDir: "{app}\web"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#DesktopBuildOutput}\*"; DestDir: "{app}\desktop"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap-supervisor.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "BootstrapProcess.cs"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints-cpu.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints-cuda.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "cleanup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "start_server.bat"; DestDir: "{app}"; DestName: "Start ESPImageServer.bat"; Flags: ignoreversion
Source: "assets\espimageserver-icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}\ESPImageServer"; Filename: "{app}\desktop\ESPImageServer.exe"; IconFilename: "{app}\espimageserver-icon.ico"
Name: "{autodesktop}\ESPImageServer"; Filename: "{app}\desktop\ESPImageServer.exe"; IconFilename: "{app}\espimageserver-icon.ico"; Tasks: desktopicon

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
  BootstrapProgress: TOutputProgressWizardPage;
  BootstrapOutput: TNewMemo;
  BootstrapCancelButton: TNewButton;
  BootstrapCancelRequested, BootstrapCancelled: Boolean;
  BootstrapStarted, BootstrapSucceeded, BootstrapRunning: Boolean;
  BootstrapFailure, BootstrapControlDirectory: String;
  BootstrapProcessHandle: Longword;
  NvidiaSummary: String;

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
    Space + 'Models: choose and download them later in the app';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultText, ErrorText: AnsiString;
  ExitCode, WaitResult: Longword;
  CancelPolls: Integer;
  CancelSent, WizardCancelWasEnabled: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;

  BootstrapStarted := True;
  BootstrapSucceeded := False;
  BootstrapFailure := 'Setup did not finish.';
  BootstrapControlDirectory := ExpandConstant('{tmp}\bootstrap-control');

  BootstrapProgress := CreateOutputProgressPage('Installing ESPImageServer',
    'Setting up the local image and video generation environment.');
  BootstrapProgress.SetProgress(1, 6);
  BootstrapProgress.SetText('Installing the local image and video generation environment...',
    'This can take several minutes while PyTorch and ESPImageServer are prepared. Please keep this window open.');
  BootstrapOutput := TNewMemo.Create(BootstrapProgress);
  BootstrapOutput.Left := 0;
  BootstrapOutput.Top := BootstrapProgress.ProgressBar.Top + BootstrapProgress.ProgressBar.Height + ScaleY(12);
  BootstrapOutput.Width := BootstrapProgress.SurfaceWidth;
  BootstrapOutput.Height := BootstrapProgress.SurfaceHeight - BootstrapOutput.Top - ScaleY(38);
  BootstrapOutput.ScrollBars := ssVertical;
  BootstrapOutput.ReadOnly := True;
  BootstrapOutput.Text := 'Installation is in progress.' + #13#10 + #13#10 +
    '- Creating the local Python environment' + #13#10 +
    '- Installing PyTorch and ESPImageServer packages' + #13#10 +
    '- Models will download only when selected in the app' + #13#10 + #13#10 +
    'The installer will continue automatically when this is complete.';
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
        { SetProgress pumps messages, including the Cancel button and window Close. }
        BootstrapProgress.SetProgress(1, 6);
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
      BootstrapProgress.SetProgress(6, 6);
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
