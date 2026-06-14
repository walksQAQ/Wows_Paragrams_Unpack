"""
统一路径管理 —— 所有模块通过此模块获取路径。

Nuitka 打包兼容：
  - Nuitka 下没有 sys._MEIPASS，sys.frozen 为 True 时
    sys.executable 指向打包后的 exe
  - 所有资源文件通过 --include-data-dir 打包到 exe 同级目录
    或用 --include-data-files 打包
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """返回可执行文件所在目录（Nuitka / 源码均兼容）"""
    if getattr(sys, "frozen", False):
        # Nuitka 打包后 sys.executable 是 exe 路径
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """返回 data/ 目录，不存在则自动创建"""
    d = get_app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_split_dir() -> Path:
    """返回 data/split/ 目录"""
    d = get_data_dir() / "split"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_path() -> Path:
    """返回 config.json 路径"""
    return get_app_dir() / "config.json"


def get_tools_dir() -> Path:
    """返回 tools/ 目录（存放 wowsunpack.exe 等）"""
    d = get_app_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_resource_path(*segments: str) -> Path:
    """返回 resources/ 下的资源路径"""
    return get_app_dir().joinpath("resources", *segments)


def get_json_mapping_path(filename: str) -> Path:
    """返回 data/ 下的 JSON 映射文件路径"""
    return get_data_dir() / filename
