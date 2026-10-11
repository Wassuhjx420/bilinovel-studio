; =====================================================================
; 哔哩轻小说 Studio Pro - 现代化极简 Windows 安装向导脚本
; =====================================================================

#define MyAppName "哔哩轻小说 Studio Pro"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BiliNovelStudio"
#define MyAppURL "https://github.com"
#define MyAppExeName "BiliNovelStudio.exe"

[Setup]
; 基础信息与唯一 GUID
AppId={{9F82A34B-62DE-4D90-A8D3-195EC9F77621}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 安装路径与分组
DefaultDirName={autopf}\BiliNovelStudio
DefaultGroupName={#MyAppName}

; 极简向导流设计：跳过冗余欢迎页与多余确认页，实现两步快速安装
DisableWelcomePage=yes
DisableReadyPage=yes
DisableProgramGroupPage=yes

; 产物配置
OutputDir=dist
OutputBaseFilename=BiliNovelStudio_Setup_v1.0.0

; 专属应用程序与卸载图标绑定
SetupIconFile=gui\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; 极限高压缩比
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 窗口视觉优化
WizardSizePercent=100

[Languages]
; 引入纯正简体中文语言定义，彻底杜绝任何英文提示
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
; 默认自动勾选创建桌面快捷方式
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\BiliNovelStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram}"; Flags: nowait postinstall skipifsilent
