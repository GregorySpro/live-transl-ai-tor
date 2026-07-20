; Inno Setup script — live-transl-ai-tor
; Prérequis : Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Build après PyInstaller : ISCC installer.iss

#define AppName      "live-transl-ai-tor"
#define AppVersion   "1.0.0"
#define AppPublisher "GregorySpro"
#define AppURL       "https://github.com/GregorySpro/live-transl-ai-tor"
#define AppExeName   "live-transl-ai-tor.exe"
#define DistDir      "dist\live-transl-ai-tor"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=live-transl-ai-tor-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Icône : décommenter si disponible
; SetupIconFile=assets\icon.ico
UninstallDisplayName={#AppName}
; UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "french";    MessagesFile: "compiler:Languages\French.isl"
Name: "english";   MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tout le dossier PyInstaller onedir
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Lance l'appli à la fin de l'installation (optionnel)
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nettoie les fichiers créés par l'app au runtime
Type: filesandordirs; Name: "{userappdata}\.live-transl-ai-tor"
