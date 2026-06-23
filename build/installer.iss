; ==============================================================================
;  DJ Tracks — Inno Setup installer script
; ==============================================================================
;  Build with:
;    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
;
;  Produces:
;    dist\installer\DJTracks-Setup-<version>.exe
;
;  Per-user install (no admin / UAC prompt required).
; ==============================================================================

#define MyAppName       "DJ Tracks"
#define MyAppVersion    "2.1.0"
#define MyAppPublisher  "thiba"
#define MyAppExeName    "DJ Tracks.exe"

[Setup]
AppId={{8C2B0F90-7F1E-4D3B-9B6E-DJ-TRACKS-APP}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} v{#MyAppVersion}
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=DJTracks-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\icon.ico
ShowLanguageDialog=no
WizardImageStretch=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\DJ Tracks\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
