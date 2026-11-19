; Windows installer for clipped (Inno Setup 6): clipped-windows-x64-setup.exe
;
;   pyinstaller packaging/clipped.spec --noconfirm
;   iscc /DAppVersion=0.1.0 packaging\clipped.iss
;
; Installs for the current user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\clipped, adds Start Menu and Desktop icons and an
; uninstaller. Your keys, settings and queue live in %LOCALAPPDATA%\clipped
; and the Windows keychain, so updating or uninstalling never touches them.

#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif

[Setup]
AppId={{8E6A2D4C-3F1B-4C7A-9D25-6B1E0F4A7C93}
AppName=clipped
AppVersion={#AppVersion}
AppVerName=clipped {#AppVersion}
AppPublisher=evzero
AppPublisherURL=https://evzero.org
AppSupportURL=https://github.com/ritviksajeev/clipped
DefaultDirName={localappdata}\Programs\clipped
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=clipped-windows-x64-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\clipped.exe
UninstallDisplayName=clipped
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a clipped icon on the Desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\clipped\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; files from an older version that the new one no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; The same AppUserModelID the app sets at runtime, so a pinned taskbar icon is clipped's.
Name: "{autoprograms}\clipped"; Filename: "{app}\clipped.exe"; IconFilename: "{app}\clipped.exe"; AppUserModelID: "evzero.clipped"
Name: "{autodesktop}\clipped"; Filename: "{app}\clipped.exe"; IconFilename: "{app}\clipped.exe"; AppUserModelID: "evzero.clipped"; Tasks: desktopicon

[Run]
Filename: "{app}\clipped.exe"; Description: "Open clipped"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM clipped.exe /F"; Flags: runhidden; RunOnceId: "StopClipped"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
