"""
browser_launcher.py — 跨平台 Playwright 浏览器智能探测与持久化启动器
支持 Windows / Linux (桌面与无头服务器 / Docker) / macOS 自动回退与无头自适应。

Disclaimer / 免责声明:
本项目仅供 Python 自动化技术交流与个人离线阅读研究使用。
小说内容及插图版权均归原作者及轻小说出版方所有。
严禁将本项目及衍生工具用于任何商业营利目的。
"""

import os
import shutil
import sys

from runtime_env import is_headless_linux


DEFAULT_ADBLOCK_HOST_RULES = (
    "MAP *googlesyndication* 127.0.0.1, "
    "MAP *doubleclick* 127.0.0.1, "
    "MAP *pagead2* 127.0.0.1, "
    "MAP *hm.baidu.com* 127.0.0.1, "
    "MAP *cnzz* 127.0.0.1, "
    "MAP *googletagmanager* 127.0.0.1, "
    "MAP *googletagservices* 127.0.0.1, "
    "MAP *adservice.google* 127.0.0.1, "
    "MAP *adsbygoogle* 127.0.0.1, "
    "MAP *bxb.im* 127.0.0.1, "
    "MAP *pos.baidu.com* 127.0.0.1, "
    "MAP *clarity.ms* 127.0.0.1, "
    "MAP *cpatrk.net* 127.0.0.1"
)


def resolve_headless(headless=None, default_desktop=True, logger=None) -> bool:
    """
    根据运行平台与显示环境解析最终是否启用无头模式：
    - Linux 无图形界面环境（未设置 DISPLAY 与 WAYLAND_DISPLAY）强制启用 headless=True，防止 X Server 报错崩溃；
    - 其余情况尊重调用方传入值（未传入时使用 default_desktop）。
    """
    if is_headless_linux():
        if headless is False and logger:
            logger("warn", "ENGINE", "检测到当前为无图形界面的 Linux 服务器环境，已自动切换为无头模式 (headless=True)")
        return True
    if headless is None:
        return bool(default_desktop)
    return bool(headless)


def build_chromium_args(enable_background_unthrottle: bool = True, host_rules: str = DEFAULT_ADBLOCK_HOST_RULES):
    """构建跨平台 Chromium / Edge 启动参数（兼容 Linux Docker 与低 /dev/shm 服务器）"""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ]

    if sys.platform.startswith("linux"):
        args.extend([
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-quic",
        ])

    if enable_background_unthrottle:
        args.extend([
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
        ])

    if host_rules:
        args.append(f"--host-resolver-rules={host_rules}")

    return args


def _find_linux_system_browser():
    """在 Linux 系统中扫描常见预装浏览器可执行路径"""
    candidates = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "microsoft-edge-stable",
    ]
    found = []
    seen = set()
    for name in candidates:
        path = shutil.which(name)
        if path:
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((name, path))
    return found


def get_browser_candidates():
    """
    按当前平台与环境变量生成浏览器启动候选队列，每项为 (label, kwargs_dict)：
    1. 环境变量优先：BILINOVEL_BROWSER_PATH / BILINOVEL_BROWSER_CHANNEL
    2. Windows：msedge -> chrome -> Playwright 内置 Chromium
    3. Linux：Playwright 内置 Chromium -> 系统已安装 chromium / chrome / msedge -> channel 兜底
    4. macOS：chrome -> msedge -> Playwright 内置 Chromium
    """
    env_path = os.environ.get("BILINOVEL_BROWSER_PATH", "").strip()
    if env_path:
        return [(f"custom({env_path})", {"executable_path": env_path})]

    env_channel = os.environ.get("BILINOVEL_BROWSER_CHANNEL", "").strip().lower()
    if env_channel:
        if env_channel in ("chromium", "bundled", "playwright"):
            return [("playwright-chromium", {})]
        return [(f"channel:{env_channel}", {"channel": env_channel})]

    if sys.platform == "win32":
        return [
            ("msedge", {"channel": "msedge"}),
            ("chrome", {"channel": "chrome"}),
            ("playwright-chromium", {}),
        ]

    if sys.platform == "darwin":
        return [
            ("chrome", {"channel": "chrome"}),
            ("msedge", {"channel": "msedge"}),
            ("playwright-chromium", {}),
        ]

    # Linux (桌面与主流发行版服务器 / Docker)
    candidates = [("playwright-chromium", {})]
    for name, path in _find_linux_system_browser():
        candidates.append((f"system:{name}", {"executable_path": path}))
    candidates.extend([
        ("chrome", {"channel": "chrome"}),
        ("msedge", {"channel": "msedge"}),
    ])
    return candidates


def format_browser_install_hint() -> str:
    """生成针对当前操作系统的浏览器安装提示"""
    if sys.platform.startswith("linux"):
        return (
            "未检测到可用的 Chromium / Chrome / Edge 浏览器。\n"
            "请在 Linux 服务器或终端中执行以下命令安装 Playwright Chromium 及系统依赖：\n"
            "  playwright install chromium\n"
            "  playwright install-deps chromium\n"
            "或安装系统浏览器（如 Debian/Ubuntu: sudo apt install -y chromium），"
            "也可通过环境变量 BILINOVEL_BROWSER_PATH 指定浏览器可执行路径。"
        )
    if sys.platform == "darwin":
        return (
            "未检测到可用的 Chrome / Edge / Chromium 浏览器。\n"
            "请安装 Google Chrome，或执行: playwright install chromium"
        )
    return (
        "未检测到可用的 Microsoft Edge / Chrome / Chromium 浏览器。\n"
        "请安装 Microsoft Edge 浏览器，或执行: playwright install chromium"
    )


async def launch_persistent_browser(
    playwright_instance,
    user_data_dir: str,
    headless=None,
    default_desktop_headless: bool = True,
    enable_background_unthrottle: bool = True,
    host_rules: str = DEFAULT_ADBLOCK_HOST_RULES,
    logger=None,
):
    """
    跨平台启动 Playwright 持久化浏览器上下文，按平台优先级自动回退可用浏览器。
    返回 (context, resolved_browser_label)。
    """
    os.makedirs(user_data_dir, exist_ok=True)
    effective_headless = resolve_headless(headless, default_desktop=default_desktop_headless, logger=logger)
    launch_args = build_chromium_args(
        enable_background_unthrottle=enable_background_unthrottle,
        host_rules=host_rules,
    )
    candidates = get_browser_candidates()
    proxy_server = os.environ.get("BILINOVEL_PROXY", "").strip()
    proxy_kwargs = {"proxy": {"server": proxy_server}} if proxy_server else {}
    errors = []

    for label, extra_kwargs in candidates:
        try:
            ctx = await playwright_instance.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=effective_headless,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
                **proxy_kwargs,
                **extra_kwargs,
            )
            if logger and label != "msedge":
                logger("info", "ENGINE", f"浏览器内核已就绪: {label} (headless={effective_headless})")
            return ctx, label
        except Exception as e:
            errors.append(f"[{label}] {e}")
            continue

    hint = format_browser_install_hint()
    detail = " | ".join(errors[-3:]) if errors else "未知错误"
    raise RuntimeError(f"{hint}\n底层错误详情: {detail}")
