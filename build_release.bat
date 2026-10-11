@echo off
chcp 65001 >nul
title 哔哩轻小说 Studio Pro - 自动化打包发布工具

echo ================================================================
echo   🚀 哔哩轻小说 Studio Pro - Windows 绿色便携 EXE 打包流水线
echo ================================================================
echo.

:: 1. 检查 Python 与 PyInstaller 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 检测到未安装 PyInstaller，正在自动安装...
    python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
)

:: 2. 清理历史构建缓存
echo [*] 正在清理旧版本构建缓存 (build/ 与 dist/)...
if exist dist (
    attrib -r -h -s dist\*.* /s /d >nul 2>&1
    attrib -r -h -s dist >nul 2>&1
    rmdir /s /q dist
)
if exist build rmdir /s /q build

:: 3. 执行 PyInstaller 打包构建
echo.
echo [*] 正在执行 PyInstaller 目录式编译打包，请稍候...
echo ----------------------------------------------------------------
pyinstaller build_exe.spec --noconfirm
echo ----------------------------------------------------------------

:: 4. 验证构建产物
if not exist "dist\BiliNovelStudio\BiliNovelStudio.exe" (
    echo.
    echo [错误] 构建失败：未能生成 dist\BiliNovelStudio\BiliNovelStudio.exe！
    echo 请检查上方 PyInstaller 报错信息。
    pause
    exit /b 1
)

echo.
echo [√] EXE 编译构建成功！输出目录: dist\BiliNovelStudio\

:: 4.1 为绿色便携目录注入专属文件夹图标 (desktop.ini)
echo [*] 正在为绿色便携目录注入专属视觉图标...
copy /y "gui\app_icon.ico" "dist\BiliNovelStudio\app_icon.ico" >nul
(
echo [.ShellClassInfo]
echo IconResource=app_icon.ico,0
echo [ViewState]
echo Mode=
echo Vid=
echo FolderType=Generic
) > "dist\BiliNovelStudio\desktop.ini"
attrib +h "dist\BiliNovelStudio\app_icon.ico"
attrib +h +s "dist\BiliNovelStudio\desktop.ini"
attrib +r "dist\BiliNovelStudio"

:: 5. 自动打包为绿色便携 ZIP 压缩包 (包含顶层目录与专属图标)
echo.
echo [*] 正在生成绿色免安装便携发布包 (BiliNovelStudio_Portable.zip)...
powershell -Command "if (Test-Path 'dist\BiliNovelStudio_Portable.zip') { Remove-Item 'dist\BiliNovelStudio_Portable.zip' -Force }; Compress-Archive -Path 'dist\BiliNovelStudio' -DestinationPath 'dist\BiliNovelStudio_Portable.zip' -Force"

if exist "dist\BiliNovelStudio_Portable.zip" (
    echo [√] 绿色便携发布包已打包完成: dist\BiliNovelStudio_Portable.zip
)

:: 6. 检测并编译 Inno Setup 安装包 (Setup.exe)
echo.
echo [*] 正在检测 Inno Setup 编译器 (ISCC.exe)...
set "ISCC_PATH="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if "%ISCC_PATH%"=="" (
    where iscc >nul 2>&1
    if %errorlevel% equ 0 set "ISCC_PATH=iscc"
)

if not "%ISCC_PATH%"=="" (
    echo [*] 发现 Inno Setup 编译器: %ISCC_PATH%
    echo [*] 正在编译安装向导安装包 (BiliNovelStudio_Setup_v1.1.0.exe)...
    "%ISCC_PATH%" installer.iss /Q
    if exist "dist\BiliNovelStudio_Setup_v1.1.0.exe" (
        echo [√] Windows 安装包制作完成: dist\BiliNovelStudio_Setup_v1.1.0.exe
    )
) else (
    echo [提示] 本机未检测到 Inno Setup 6。
    echo        若需在本地生成 Setup.exe 安装程序，可执行命令快速安装:
    echo        winget install JRSoftware.InnoSetup
    echo        安装完成后重新运行本脚本即可自动生成安装向导程序。
)

:: 7. 刷新 Windows Explorer 图标缓存
ie4uinit.exe -show >nul 2>&1

echo.
echo ================================================================
echo   🎉 全部打包构建完成！
echo   - 绿色免安装目录: dist\BiliNovelStudio\
echo   - 开箱即用发布包: dist\BiliNovelStudio_Portable.zip
if exist "dist\BiliNovelStudio_Setup_v1.1.0.exe" (
    echo   - 安装向导安装包: dist\BiliNovelStudio_Setup_v1.1.0.exe
)
echo ================================================================
echo.
pause
