; Build with: iscc installer\ESPImageServer.iss
; The resulting ESPImageServer-Setup.exe is the maker-facing Windows installer.

#define AppName "ESPImageServer"
#define AppVersion "0.1.0"
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
OutputBaseFilename=ESPImageServer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Files]
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "start_server.bat"; DestDir: "{app}"; DestName: "Start ESPImageServer.bat"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}\Start ESPImageServer"; Filename: "{cmd}"; Parameters: "/k ""{app}\Start ESPImageServer.bat"""
Name: "{autodesktop}\ESPImageServer"; Filename: "{cmd}"; Parameters: "/k ""{app}\Start ESPImageServer.bat"""; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{cmd}"; Parameters: "/k ""{app}\Start ESPImageServer.bat"""; Description: "Start ESPImageServer"; Flags: nowait postinstall skipifsilent

[Code]
var
  ComputePage: TInputOptionWizardPage;
  ModelPage: TInputOptionWizardPage;
  BootstrapProgress: TOutputProgressWizardPage;

function NvidiaDetected: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('nvidia-smi.exe', '--query-gpu=name --format=csv,noheader', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
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
    'Choose model download timing',
    'Selected model: {#ModelId}',
    'This image model is several gigabytes. Download it now to verify setup, or let the first server start download it.',
    True, True);
  ModelPage.Add('Download the model now');
  ModelPage.Add('Download the model on first server start');
  ModelPage.SelectedValueIndex := 0;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  ComputeChoice: String;
  DownloadChoice: String;
begin
  if ComputePage.SelectedValueIndex = 1 then
    ComputeChoice := 'NVIDIA CUDA acceleration'
  else
    ComputeChoice := 'CPU compatibility mode';

  if ModelPage.SelectedValueIndex = 0 then
    DownloadChoice := 'Download during installation'
  else
    DownloadChoice := 'Download on first server start';

  Result := MemoUserInfoInfo + MemoDirInfo + MemoTypeInfo + MemoComponentsInfo +
    MemoGroupInfo + MemoTasksInfo + NewLine + 'Image generation:' + NewLine +
    Space + 'Model: {#ModelId}' + NewLine +
    Space + 'Hardware: ' + ComputeChoice + NewLine +
    Space + 'Model download: ' + DownloadChoice;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Parameters: String;
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\bootstrap.ps1') + '"';
  if ComputePage.SelectedValueIndex = 1 then
    Parameters := Parameters + ' -UseCuda';
  if ModelPage.SelectedValueIndex = 0 then
    Parameters := Parameters + ' -DownloadModel';

  BootstrapProgress := CreateOutputProgressPage('Installing ESPImageServer',
    'Downloading and configuring the local image-generation environment.');
  BootstrapProgress.SetText('This may take several minutes. Please keep this window open.', '');
  BootstrapProgress.Show;
  try
    if (not Exec('powershell.exe', Parameters, ExpandConstant('{app}'), SW_HIDE,
        ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      RaiseException('ESPImageServer setup did not finish. See bootstrap.log in the installation folder.');
  finally
    BootstrapProgress.Hide;
  end;
end;
