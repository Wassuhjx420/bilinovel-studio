@echo off
chcp 65001 >nul
title 哔哩轻小说 Studio Pro - 桌面启动器

echo ================================================================
echo   🚀 哔哩轻小说极速爬虫 & 出版级 EPUB 制作工具 Studio Pro
echo ================================================================
echo.

:: 1. 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    echo 请前往 https://www.python.org/ 下载并安装 Python (建议 3.10 及以上版本)。
    echo 安装时请务必勾选 "Add Python to PATH" (添加到系统环境变量)。
    echo.
    pause
    exit /b 1
)

:: 2. 检查核心依赖包
echo [*] 正在检查运行环境依赖...
python -c "import playwright, bs4, ebooklib" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 首次运行或检测到依赖不完整，正在自动安装运行依赖 (requirements.txt)...
    echo.
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo [重试] 镜像源安装失败，尝试官方源安装...
        python -m pip install -r requirements.txt
    )
    echo.
)

:: 3. 启动桌面客户端 (优先使用 pythonw 启动无黑框纯桌面模式)
echo [*] 正在启动客户端服务，请稍候...
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw launch_gui.py
    exit /b 0
) else (
    python launch_gui.py
    if %errorlevel% neq 0 (
        echo.
        echo [提示] 程序异常退出，请查看上方日志信息。
        pause
    )
)
