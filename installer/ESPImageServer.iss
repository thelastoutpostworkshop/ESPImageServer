; Build with: iscc installer\ESPImageServer.iss
; The resulting ESPImageServer-Setup.exe is the maker-facing Windows installer.

#define AppName "ESPImageServer"
#define AppVersion "0.1.88"
#define AppPublisher "ESPImageServer"
#define ModelId "stabilityai/sd-turbo"

[Setup]
AppId={{18AA2901-70A7-4C30-9C55-6B78F51F6CC0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=ESPImageServer-Setup-0.1.88
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
Source: "..\desktop\release\win-unpacked\*"; DestDir: "{app}\desktop"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
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
  ModelPage: TInputOptionWizardPage;
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
    'Choose image-generation hardware',
    'Select the hardware this computer should use.',
    'NVIDIA CUDA is much faster, but requires a compatible NVIDIA driver. CPU mode works on any PC but is slow.',
    True, True);
  ComputePage.Add('CPU compatibility mode');
  ComputePage.Add('NVIDIA CUDA acceleration');
  if NvidiaDetected then
    ComputePage.SelectedValueIndex := 1
  else
    ComputePage.SelectedValueIndex := 0;

  ModelPage := CreateInputOptionPage(ComputePage.ID,
    'Choose image model',
    'The selected model will download during installation.',
    'This installer downloads one model so ESPImageServer is ready immediately. You can download and switch to the other supported models later from the Models page in the web app. SD-Turbo is the fast, display-focused default. DreamShaper 8 creates artistic images, SSD-1B provides more detail, and SDXL Base 1.0 offers the best detail but requires a powerful NVIDIA GPU.',
    True, True);
  ModelPage.Add('SD-Turbo - fast, 512 x 512, recommended');
  ModelPage.Add('DreamShaper 8 - creative artwork, NVIDIA GPU recommended');
  ModelPage.Add('Segmind SSD-1B - higher quality, slower, NVIDIA GPU recommended');
  ModelPage.Add('SDXL Base 1.0 - best detail, powerful NVIDIA GPU required');
  ModelPage.SelectedValueIndex := 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { Inno Setup silently runs the previous uninstaller during an upgrade.
      Preserve the virtual environment, models, and user images in that case.
      A user-initiated uninstall remains a full removal. }
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
  SelectedModel: String;
begin
  if ComputePage.SelectedValueIndex = 1 then
    ComputeChoice := 'NVIDIA CUDA acceleration'
  else
    ComputeChoice := 'CPU compatibility mode';

  if ModelPage.SelectedValueIndex = 0 then
    SelectedModel := 'stabilityai/sd-turbo (fast, 512 x 512)'
  else if ModelPage.SelectedValueIndex = 1 then
    SelectedModel := 'Lykon/dreamshaper-8 (creative artwork, 512 x 512)'
  else if ModelPage.SelectedValueIndex = 2 then
    SelectedModel := 'segmind/SSD-1B (higher quality, 1024 x 1024)'
  else
    SelectedModel := 'stabilityai/stable-diffusion-xl-base-1.0 (best detail, 1024 x 1024)';

  Result := MemoUserInfoInfo + MemoDirInfo + MemoTypeInfo + MemoComponentsInfo +
    MemoGroupInfo + MemoTasksInfo + NewLine + 'Image generation:' + NewLine +
    Space + 'Model: ' + SelectedModel + NewLine +
    Space + 'Hardware: ' + ComputeChoice + NewLine +
    Space + 'Model download: during installation' + NewLine +
    Space + 'Other supported models: available later from the web app Models page';
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
  if ModelPage.SelectedValueIndex = 0 then
    Parameters := Parameters + ' -ModelId "stabilityai/sd-turbo" -InferenceSteps 1 -GuidanceScale 0 -GenerationWidth 512 -GenerationHeight 512'
  else if ModelPage.SelectedValueIndex = 1 then
    Parameters := Parameters + ' -ModelId "Lykon/dreamshaper-8" -InferenceSteps 25 -GuidanceScale 7 -GenerationWidth 512 -GenerationHeight 512'
  else if ModelPage.SelectedValueIndex = 2 then
    Parameters := Parameters + ' -ModelId "segmind/SSD-1B" -InferenceSteps 20 -GuidanceScale 9 -GenerationWidth 1024 -GenerationHeight 1024'
  else
    Parameters := Parameters + ' -ModelId "stabilityai/stable-diffusion-xl-base-1.0" -InferenceSteps 30 -GuidanceScale 7 -GenerationWidth 1024 -GenerationHeight 1024';

  BootstrapProgress := CreateOutputProgressPage('Installing ESPImageServer',
    'Setting up the local image-generation environment.');
  BootstrapProgress.SetProgress(1, 6);
  BootstrapProgress.SetText('Installing the local image-generation environment...',
    'This can take several minutes while PyTorch and the selected model are prepared. Please keep this window open.');
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
    '- Downloading the selected image model' + #13#10 + #13#10 +
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
