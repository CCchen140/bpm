#define MyAppName "栖图"
#define MyAppVersion "V0.0.1"
#define MyAppDistDir "..\\dist\\栖图_V0.0.1"
#define MyAppExeName "栖图.exe"

[Setup]
AppId={{8E9B4F2B-2A8D-4E2E-9D2A-8F3A2CE3D5F7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename={#MyAppName}_{#MyAppVersion}_Setup
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加任务"; Flags: checkedonce

[Files]
Source: "{#MyAppDistDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"
Name: "{commondesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
