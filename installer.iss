; Inno Setup — live-transl-ai-tor (bootstrap installer)
; L'installeur est léger : les dépendances lourdes (torch, etc.)
; sont téléchargées automatiquement au premier lancement.

#define AppName      "live-transl-ai-tor"
#define AppVersion   "1.1.0"
#define AppPublisher "GregorySpro"
#define AppURL       "https://github.com/GregorySpro/live-transl-ai-tor"
#define AppExeName   "live-transl-ai-tor.exe"
#define BootstrapDir "dist\live-transl-ai-tor-bootstrap"

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
UninstallDisplayName={#AppName}

[Languages]
Name: "french";  MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Bootstrap (fenêtre de setup + launcher)
Source: "{#BootstrapDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Code source de l'application
Source: "app.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "src\*";               DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nettoie l'environnement Python installé dans LocalAppData
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
; Nettoie le runtime Python placé à la racine du disque (contournement junctions)
Type: filesandordirs; Name: "C:\ltai-py"
