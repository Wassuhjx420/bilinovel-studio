"""
runtime_env.py — 运行时环境与物理路径动态感知模块
支持源码开发模式、PyInstaller 打包模式以及 Linux 服务器 / Docker 环境变量挂载。
"""

import os
import sys


def is_frozen() -> bool:
    """判断当前程序是否在 PyInstaller 打包环境中运行"""
    return getattr(sys, "frozen", False)


def is_linux() -> bool:
    """判断当前是否为 Linux 系统"""
    return sys.platform.startswith("linux")


def is_headless_linux() -> bool:
    """判断当前是否为无图形显示环境的 Linux 服务器 / 容器（无 DISPLAY 且无 WAYLAND_DISPLAY）"""
    if not is_linux():
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def get_resource_dir() -> str:
    """
    获取静态只读资源根目录（用于加载内置的前端静态网页 gui/、默认模板、解密字典等）。
    - 打包模式下：优先返回 sys._MEIPASS（临时解压目录）或可执行文件所在目录；
    - 源码模式下：返回项目根目录。
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_storage_dir() -> str:
    """
    获取数据可读写持久化根目录（用于保存下载小说 novels/、浏览器会话 .edge_profile/、临时缓存等）。
    - 优先读取环境变量 BILINOVEL_DATA_DIR（便于 Linux 服务器 / Docker 持久化挂载卷）；
    - 打包模式下：严格锚定在 sys.executable 所在物理目录，避免数据随临时文件夹被系统清理；
    - 源码模式下：返回项目根目录。
    """
    env_data_dir = os.environ.get("BILINOVEL_DATA_DIR", "").strip()
    if env_data_dir:
        resolved = os.path.abspath(os.path.expanduser(env_data_dir))
        os.makedirs(resolved, exist_ok=True)
        return resolved
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_gui_dir() -> str:
    """获取前端静态资源目录"""
    return os.path.join(get_resource_dir(), "gui")


def get_novels_dir() -> str:
    """获取小说持久化产物存储目录（支持环境变量 BILINOVEL_NOVELS_DIR 覆盖）"""
    env_novels_dir = os.environ.get("BILINOVEL_NOVELS_DIR", "").strip()
    if env_novels_dir:
        novels_dir = os.path.abspath(os.path.expanduser(env_novels_dir))
    else:
        novels_dir = os.path.join(get_storage_dir(), "novels")
    os.makedirs(novels_dir, exist_ok=True)
    return novels_dir


def get_profile_dir() -> str:
    """获取浏览器持久化上下文目录（保留 .edge_profile 目录名以兼容历史会话）"""
    profile_dir = os.path.join(get_storage_dir(), ".edge_profile")
    os.makedirs(profile_dir, exist_ok=True)
    return profile_dir


def get_cache_dir() -> str:
    """获取临时缓存目录"""
    cache_dir = os.path.join(get_storage_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir
