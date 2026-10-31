#define AppName "Road Rage Trip"
#define AppVersion "0.20.0beta"
#define AppPublisher "The Road Rage Trip"
#define AppExeName "RoadRageTrip.exe"
; startup.gd's packaged map: Paths.package_path("assets/osm/finland-latest.osm.pbf")
#define PbfDir "server\_internal\theroadragetrip\assets\osm"
#define PbfUrl "https://download.geofabrik.de/europe/finland-latest.osm.pbf"

[Setup]
AppId={{8A5A2C8A-5AC3-4D7E-9B4F-6A5D2F4E1C30}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\RoadRageTrip
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=RoadRageTrip-{#AppVersion}-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\RoadRageTrip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "finlandmap"; Description: "Download the Finland map (OpenStreetMap, about 0.8 GB) and use it as the map source"; GroupDescription: "Offline map:"; Flags: unchecked

[UninstallDelete]
Type: files; Name: "{app}\{#PbfDir}\finland-latest.osm.pbf"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;
  MapDownloaded: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;

// Inno's download page pattern: fetch into {tmp} on the Ready page. A failure
// keeps the install; the game stays on Overpass and offers the download again.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or not WizardIsTaskSelected('finlandmap') then
    Exit;
  DownloadPage.Clear;
  DownloadPage.Add('{#PbfUrl}', 'finland-latest.osm.pbf', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      MapDownloaded := True;
    except
      if DownloadPage.AbortedByUser then
        Log('Finland map download cancelled')
      else
        SuppressibleMsgBox('The Finland map could not be downloaded: ' + GetExceptionMessage + #13#10 +
          'The game will offer the download again when it is needed.', mbError, MB_OK, IDOK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

// startup.gd's _pbf_path() finds it here and makes "pbf" the default source.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Target: String;
begin
  if (CurStep <> ssPostInstall) or not MapDownloaded then
    Exit;
  Target := ExpandConstant('{app}\{#PbfDir}\finland-latest.osm.pbf');
  ForceDirectories(ExtractFileDir(Target));
  if not FileCopy(ExpandConstant('{tmp}\finland-latest.osm.pbf'), Target, False) then
    SuppressibleMsgBox('Could not save the Finland map to ' + Target, mbError, MB_OK, IDOK);
end;
