; Build with: iscc installer\ESPImageServer.iss
; The resulting ESPImageServer-Setup.exe is the maker-facing Windows installer.

#define AppName "ESPImageServer"
#define AppVersion "1.0.63"
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
OutputBaseFilename=ESPImageServer-Setup-1.0.63
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
Filename: "{app}\desktop\ESPImageServer.exe"; Description: "Start ESPImageServer"; Flags: nowait postinstall skipifsilent

[Code]
var
  ComputePage: TInputOptionWizardPage;
  BootstrapProgress: TOutputProgressWizardPage;
  BootstrapOutput: TNewMemo;
  BootstrapCancelButton: TNewButton;
  BootstrapCancelRequested: Boolean;

procedure Sleep(Milliseconds: Longword);
external 'Sleep@kernel32.dll stdcall';

function NvidiaDetected: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('nvidia-smi.exe', '--query-gpu=name --format=csv,noheader', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure BootstrapCancelClick(Sender: TObject);
begin
  if MsgBox('Cancel ESPImageServer installation? The partial installation can be repaired by running this installer again.',
    mbConfirmation, MB_YESNO) = IDYES then begin
    BootstrapCancelRequested := True;
    BootstrapCancelButton.Enabled := False;
  end;
end;

procedure InitializeWizard;
begin
  ComputePage := CreateInputOptionPage(wpSelectDir,
    'Choose image and video generation hardware',
    'Select the hardware this computer should use.',
    'NVIDIA CUDA is much faster, but requires a compatible NVIDIA driver. CPU mode works on any PC but is slow.',
    True, True);
  ComputePage.Add('CPU compatibility mode');
  ComputePage.Add('NVIDIA CUDA acceleration');
  if NvidiaDetected then
    ComputePage.SelectedValueIndex := 1
  else
    ComputePage.SelectedValueIndex := 0;

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
var
  ComputeChoice: String;
begin
  if ComputePage.SelectedValueIndex = 1 then
    ComputeChoice := 'NVIDIA CUDA acceleration'
  else
    ComputeChoice := 'CPU compatibility mode';

  Result := MemoUserInfoInfo + MemoDirInfo + MemoTypeInfo + MemoComponentsInfo +
    MemoGroupInfo + MemoTasksInfo + NewLine + 'Image generation:' + NewLine +
    Space + 'Hardware: ' + ComputeChoice + NewLine +
    Space + 'Models: choose and download them later in the app';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Parameters: String;
  ProcessID: Integer;
  ResultText: AnsiString;
  TaskKillResult: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\bootstrap.ps1') + '"';
  if ComputePage.SelectedValueIndex = 1 then
    Parameters := Parameters + ' -UseCuda';

  BootstrapProgress := CreateOutputProgressPage('Installing ESPImageServer',
    'Setting up the local image-generation environment.');
  BootstrapProgress.SetProgress(1, 6);
  BootstrapProgress.SetText('Installing the local image-generation environment...',
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
  BootstrapProgress.Show;
  ResultText := '';
  try
    { A previous setup result would otherwise make the asynchronous bootstrap
      appear complete before the new PowerShell process has started. }
    DeleteFile(ExpandConstant('{app}\installer_result.txt'));
    DeleteFile(ExpandConstant('{app}\installer_status.txt'));
    DeleteFile(ExpandConstant('{app}\bootstrap.log'));
    if (not Exec('powershell.exe', Parameters, ExpandConstant('{app}'), SW_HIDE,
        ewNoWait, ProcessID)) then
      RaiseException('Could not start ESPImageServer setup.');

    while not FileExists(ExpandConstant('{app}\installer_result.txt')) do begin
      if BootstrapCancelRequested then begin
        BootstrapProgress.SetText('Cancelling installation...', 'Stopping the setup process.');
        Exec('taskkill.exe', '/PID ' + IntToStr(ProcessID) + ' /T /F', '', SW_HIDE,
          ewWaitUntilTerminated, TaskKillResult);
        ResultText := 'cancelled';
        Break;
      end;
      { SetProgress pumps the installer message queue, keeping the progress page responsive. }
      BootstrapProgress.SetProgress(1, 6);
      Sleep(250);
    end;

    if ResultText = '' then
      LoadStringFromFile(ExpandConstant('{app}\installer_result.txt'), ResultText);
    if ResultText = 'cancelled' then
      RaiseException('Installation was cancelled. You can run this installer again to repair or complete setup.');
    if Trim(ResultText) <> 'success' then
      RaiseException('ESPImageServer setup did not finish. See bootstrap.log in the installation folder.');
    BootstrapProgress.SetProgress(6, 6);
    BootstrapProgress.SetText('Installation complete.', 'ESPImageServer is ready to start.');
  finally
    BootstrapCancelButton.Visible := False;
    BootstrapProgress.Hide;
  end;
end;
