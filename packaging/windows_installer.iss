; Inno Setup script for the Windows installer. Built by .github/workflows/windows.yml:
;   iscc /DAppVersion=1.0.0 /DSourceDir=<pyinstaller dist\Transect Tool> /DOutDir=<dir> packaging\windows_installer.iss
; Installs per-user (no admin rights needed).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2B8C1E-4A7D-4E9B-9C3A-7E1D2B5F8A60}
AppName=Transect Tool
AppVersion={#AppVersion}
AppPublisher=Transect Tool
DefaultDirName={localappdata}\Programs\Transect Tool
DefaultGroupName=Transect Tool
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=Transect-Tool-{#AppVersion}-windows-setup
SetupIconFile=TransectTool.ico
UninstallDisplayIcon={app}\Transect Tool.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Transect Tool"; Filename: "{app}\Transect Tool.exe"
Name: "{autodesktop}\Transect Tool"; Filename: "{app}\Transect Tool.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Transect Tool.exe"; Description: "Open Transect Tool now"; Flags: nowait postinstall skipifsilent
