; AuthenAPI — ตัวติดตั้ง (Inno Setup 6)
; build:  ISCC.exe /DAppVersion=2.1.0 installer\AuthenAPI.iss
; ต้อง build AuthenAPI.exe ด้วย PyInstaller ไว้ที่ dist-release\AuthenAPI.exe ก่อน
; ผลลัพธ์: dist-release\AuthenAPI-Setup.exe (แนบไปกับ GitHub release ทุกครั้ง)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; ⚠️ ห้ามเปลี่ยน AppId — ใช้ระบุว่าเป็นโปรแกรมเดิมตอนอัปเดต/ถอนการติดตั้ง
AppId={{8F3C2A51-6B7D-4E2A-9C1F-3D5B7A9E1C42}
AppName=AuthenAPI
AppVersion={#AppVersion}
AppVerName=AuthenAPI {#AppVersion}
AppPublisher=AuthenChart
AppPublisherURL=https://github.com/arofatsabuding/authenchart-printer-windows
AppUpdatesURL=https://github.com/arofatsabuding/authenchart-printer-windows/releases
VersionInfoVersion={#AppVersion}
; ค่าเริ่มต้น C:\Program Files\AuthenAPI — ผู้ใช้เปลี่ยนได้ในหน้า "Select Destination Location"
DefaultDirName={autopf}\AuthenAPI
DisableDirPage=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-release
OutputBaseFilename=AuthenAPI-Setup
SetupIconFile=..\logo.ico
UninstallDisplayIcon={app}\AuthenAPI.exe
UninstallDisplayName=AuthenAPI
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; ปิดโปรแกรมที่เปิดอยู่ก่อนติดตั้งทับ (กันไฟล์ถูกล็อก)
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "สร้าง shortcut บน Desktop"; GroupDescription: "ตัวเลือกเพิ่มเติม:"
Name: "startup"; Description: "เปิด AuthenAPI อัตโนมัติเมื่อเปิดเครื่อง"; GroupDescription: "ตัวเลือกเพิ่มเติม:"

[Files]
Source: "..\dist-release\AuthenAPI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AuthenAPI"; Filename: "{app}\AuthenAPI.exe"; IconFilename: "{app}\logo.ico"
Name: "{autodesktop}\AuthenAPI"; Filename: "{app}\AuthenAPI.exe"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon
Name: "{autostartup}\AuthenAPI"; Filename: "{app}\AuthenAPI.exe"; IconFilename: "{app}\logo.ico"; Tasks: startup

[InstallDelete]
; shortcut ที่เวอร์ชันเก่า (<= 2.0.x ติดตั้งตัวเองแบบไม่มีตัวติดตั้ง) สร้างไว้ — ลบทิ้งกันเปิดซ้ำ 2 ตัวตอนเปิดเครื่อง
Type: files; Name: "{userstartup}\AuthenAPI.lnk"
Type: files; Name: "{userdesktop}\AuthenAPI.lnk"

[Run]
; ไม่มี skipifsilent — ตอนอัปเดตอัตโนมัติ (/SILENT) จะเปิดโปรแกรมกลับขึ้นมาเอง
; runasoriginaluser — เปิดด้วยสิทธิ์ผู้ใช้ปกติ ไม่ใช่ admin (config จะได้อยู่ใน %APPDATA% ของผู้ใช้คนนั้น)
Filename: "{app}\AuthenAPI.exe"; Description: "เปิด AuthenAPI ตอนนี้"; Flags: nowait postinstall runasoriginaluser

[Code]
procedure KillRunningApp();
var
  ResultCode: Integer;
begin
  { PyInstaller onefile มี 2 โปรเซสชื่อเดียวกัน — /T ปิดทั้งต้นไม้ }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM AuthenAPI.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Sleep(800);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  KillRunningApp();
  Result := True;
end;
