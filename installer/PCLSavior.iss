#define AppVersion "1.0.0-beta.1"
#ifndef PayloadDir
#define PayloadDir "..\dist\PCL-Savior"
#endif
[Setup]
AppId={{53DD7B16-639F-4AFE-A87E-A9BC82DB75C9}
AppName=PCL Savior
AppVersion={#AppVersion}
AppVerName=PCL Savior {#AppVersion}
AppPublisher=苹果匠
DefaultDirName={localappdata}\Programs\PCL Savior
DefaultGroupName=PCL Savior
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PCL-Savior-{#AppVersion}-windows-x64-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\PCL Savior.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=1.0.0.0
VersionInfoDescription=PCL Savior 安装程序
[Languages]
Name: "chinesesimp"; MessagesFile: "Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\PCL Savior"; Filename: "{app}\PCL Savior.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\PCL Savior"; Filename: "{app}\PCL Savior.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\PCL Savior.exe"; Description: "启动 PCL Savior"; Flags: nowait postinstall skipifsilent
