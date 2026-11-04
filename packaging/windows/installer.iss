; Установщик Windows-версии (Inno Setup 6). Собирается в .github/workflows/windows.yml
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C1F4E2B-5A7D-4E39-9B61-2F5RP0LINUX1}
AppName=GTA5RP Launcher (unofficial)
AppVersion={#AppVersion}
AppPublisher=bagira818
AppPublisherURL=https://alinaz18.github.io/gta5rp-launcher-linux/
AppSupportURL=https://github.com/alinaz18/gta5rp-launcher-linux/issues
DefaultDirName={localappdata}\Programs\GTA5RP Launcher Unofficial
DefaultGroupName=GTA5RP Launcher (unofficial)
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=GTA5RP-Launcher-Setup-{#AppVersion}
SetupIconFile=..\..\build\icon.ico
UninstallDisplayIcon={app}\GTA5RP Launcher.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\GTA5RP Launcher\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\GTA5RP Launcher (unofficial)"; Filename: "{app}\GTA5RP Launcher.exe"
Name: "{group}\{cm:UninstallProgram,GTA5RP Launcher}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\GTA5RP Launcher (unofficial)"; Filename: "{app}\GTA5RP Launcher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GTA5RP Launcher.exe"; Description: "{cm:LaunchProgram,GTA5RP Launcher}"; Flags: nowait postinstall skipifsilent
