# -*- mode: python ; coding: utf-8 -*-
"""
build_exe.spec — 哔哩轻小说 Studio Pro 专属 PyInstaller 打包规格文件
支持内置 Playwright Node.js 驱动层、Vue 3 前端静态资源及 PyWebView 桌面运行时。
"""

import os
import sys
import playwright

# 动态定位 Playwright Node.js 驱动目录
playwright_dir = os.path.dirname(playwright.__file__)
playwright_driver_dir = os.path.join(playwright_dir, 'driver')

block_cipher = None

# 数据资源清单：(源物理路径, 打包后相对路径)
datas = [
    # 1. 前端完整静态资源（HTML / JS / CSS / 图标）
    ('gui', 'gui'),
    # 2. Playwright 二进制驱动层 (包含 node.exe 与 driver 通信包)
    (playwright_driver_dir, os.path.join('playwright', 'driver')),
]

# 核心隐藏导入（确保动态加载模块不丢失）
hiddenimports = [
    'playwright',
    'playwright.async_api',
    'playwright._impl._driver',
    'bs4',
    'ebooklib',
    'ebooklib.epub',
    'rubbish_secret_map',
    'runtime_env',
    'gui_service',
    'scrape_linovelib',
    'to_epub',
    # PyWebView 桌面客户端相关
    'webview',
    'webview.platforms',
    'webview.platforms.winforms',
    'clr',
]

# 排除多余庞大无关库，极致精简产物体积
excludes = [
    'matplotlib',
    'numpy',
    'scipy',
    'pandas',
    'PIL',
    'pytest',
    'unittest',
    'IPython',
    'jupyter',
]

a = Analysis(
    ['launch_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BiliNovelStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 纯粹现代 GUI 应用模式，彻底隐藏黑色控制台黑框
    icon='gui/app_icon.ico',  # 专属高质感应用程序图标
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BiliNovelStudio',
)
