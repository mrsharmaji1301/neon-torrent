; Inno Setup script for NEON Torrent. Built by tools\build_installer.py, which passes /DLayout and /DOutDir.
#define AppName "NEON Torrent"
#define AppVer "1.0.1"

[Setup]
AppId={{B6E1F2A4-3C7D-4E9A-8F21-5D4C3B2A1E90}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher=NEON
DefaultDirName=F:\Apps\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
LicenseFile=PRIVACY.txt
SetupIconFile=NeonTorrent.ico
UninstallDisplayIcon={app}\NeonTorrent.ico
UninstallDisplayName={#AppName}
OutputDir={#OutDir}
OutputBaseFilename=NEON-Torrent-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Layout}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "NeonTorrent.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; the app's own pythonw copy started with -m, so no console window ever opens
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\NeonTorrent.exe"; Parameters: "-m neon_torrent"; WorkingDir: "{app}"; IconFilename: "{app}\NeonTorrent.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\NeonTorrent.exe"; Parameters: "-m neon_torrent"; WorkingDir: "{app}"; IconFilename: "{app}\NeonTorrent.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\NeonTorrent.exe"; Parameters: "-m neon_torrent"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
