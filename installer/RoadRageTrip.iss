#define AppName "Road Rage Trip"
#define AppVersion "0.7.0beta"
#define AppPublisher "The Road Rage Trip"
#define AppExeName "RoadRageTrip.exe"

[Setup]
AppId={{8A5A2C8A-5AC3-4D7E-9B4F-6A5D2F4E1C30}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\RoadRageTrip
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=RoadRageTrip-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Files]
Source: "..\dist\RoadRageTrip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
