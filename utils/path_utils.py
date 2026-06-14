"""
统一路径管理 —— 所有模块通过此模块获取路径。

路径策略（区分打包内部资源 vs 外部用户数据）：

  ┌─────────────────────────────────────────────────────────┐
  │  get_app_dir()     用户数据目录（exe 同级）              │
  │  用途: config.json, data/, data/split/                 │
  │  源码 → 项目根 | standalone → exe 同级 | onefile → CWD │
  ├─────────────────────────────────────────────────────────┤
  │  get_bundled_dir() 打包资源目录（onefile 解压目录）      │
  │  用途: resources/, tools/                              │
  │  源码 → 项目根 | standalone → exe 同级 | onefile → 临时 │
  └─────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import sys
from pathlib import Path


def _get_source_root() -> Path:
    """源码模式下的项目根目录"""
    return Path(__file__).resolve().parent.parent


def get_app_dir() -> Path:
    """用户数据目录：exe 同级（config.json, data/ 等存放于此）"""
    if "__compiled__" in globals():
        # Nuitka 编译模式：sys.argv[0] 始终是原始 exe 路径（onefile / standalone 均适用）
        return Path(sys.argv[0]).resolve().parent
    return _get_source_root()


def get_bundled_dir() -> Path:
    """打包资源目录：resources/, tools/ 等内置资源的实际位置"""
    if "__compiled__" in globals():
        # onefile / standalone 下，内置资源都在 sys.executable 同级
        return Path(sys.executable).resolve().parent
    return _get_source_root()


# ── 用户数据（exe 同级目录） ──────────────────────────────

def get_data_dir() -> Path:
    """返回 data/ 目录，不存在则自动创建"""
    d = get_app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_split_dir() -> Path:
    """返回 data/split/ 目录，不存在则自动创建"""
    d = get_data_dir() / "split"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_path() -> Path:
    """返回 config.json 路径（不存在时调用方负责创建）"""
    return get_app_dir() / "config.json"


def get_json_mapping_path(filename: str) -> Path:
    """返回 data/ 下的 JSON 映射文件路径"""
    return get_data_dir() / filename


# ── 打包内置资源（源码 / standalone / onefile 解压目录） ──

def get_tools_dir() -> Path:
    """返回 tools/ 目录（存放 wowsunpack.exe 等）"""
    return get_bundled_dir() / "tools"


def get_resource_path(*segments: str) -> Path:
    """返回 resources/ 下的资源路径"""
    return get_bundled_dir().joinpath("resources", *segments)
