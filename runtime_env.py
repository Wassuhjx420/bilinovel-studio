"""
runtime_env.py — 运行时环境与物理路径动态感知模块
支持源码开发模式与 PyInstaller 打包后的 Windows EXE 模式双轨自适应。
"""

import os
import sys


def is_frozen() -> bool:
    """判断当前程序是否在 PyInstaller 打包环境中运行"""
    return getattr(sys, "frozen", False)


def get_resource_dir() -> str:
    """
    获取静态只读资源根目录（用于加载内置的前端静态网页 gui/、默认模板、解密字典等）。
    - 打包模式下：优先返回 sys._MEIPASS（临时解压目录）或 exe 所在目录；
    - 源码模式下：返回项目根目录。
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_storage_dir() -> str:
    """
    获取数据可读写持久化根目录（用于保存下载小说 novels/、浏览器会话 .edge_profile/、临时缓存等）。
    - 打包模式下：严格锚定在 sys.executable 所在物理目录，避免数据随临时文件夹被系统清理；
    - 源码模式下：返回项目根目录。
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_gui_dir() -> str:
    """获取前端静态资源目录"""
    return os.path.join(get_resource_dir(), "gui")


def get_novels_dir() -> str:
    """获取小说持久化产物存储目录"""
    novels_dir = os.path.join(get_storage_dir(), "novels")
    os.makedirs(novels_dir, exist_ok=True)
    return novels_dir


def get_profile_dir() -> str:
    """获取 Edge 浏览器持久化上下文目录"""
    profile_dir = os.path.join(get_storage_dir(), ".edge_profile")
    os.makedirs(profile_dir, exist_ok=True)
    return profile_dir


def get_cache_dir() -> str:
    """获取临时缓存目录"""
    cache_dir = os.path.join(get_storage_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir
