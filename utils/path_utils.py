"""
统一路径管理 —— 所有模块通过此模块获取路径。

路径策略（区分打包内部资源 vs 外部用户数据）：

  ┌─────────────────────────────────────────────────────────┐
  │  get_app_dir()     用户数据目录（exe 同级）              │
  │  用途: config.json, data/, data/split/                 │
  │  源码 → 项目根 | standalone → exe 同级 | onefile → exe  │
  │                    同级（sys.argv[0] 原始 exe 路径）    │
  ├─────────────────────────────────────────────────────────┤
  │  get_bundled_dir() 打包资源目录（onefile 解压目录）      │
  │  用途: resources/, tools/                              │
  │  源码 → 项目根 | standalone → exe 同级 | onefile → 临时 │
  │                    解压目录（sys.executable）           │
  └─────────────────────────────────────────────────────────┘

注：Nuitka 编译模式用 "__compiled__" in globals() 判定。
  - get_app_dir → Path(sys.argv[0]).resolve().parent：onefile 下 sys.argv[0]
    仍是用户启动的原始 exe 路径 → 用户数据（config.json / data/）落在 exe 同级
  - get_bundled_dir → Path(sys.executable).resolve().parent：onefile 下
    sys.executable 指向自解压出的临时 exe → 内置资源在解压目录
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
    """返回 data/split/ 目录（不自动创建，由 processor_service 按需创建）"""
    return get_data_dir() / "split"


def get_config_path() -> Path:
    """返回 config.json 路径（不存在时调用方负责创建）"""
    return get_app_dir() / "config.json"


# ── 打包内置资源（源码 / standalone / onefile 解压目录） ──

def get_tools_dir() -> Path:
    """返回 tools/ 目录（存放 wowsunpack.exe 等）"""
    return get_bundled_dir() / "tools"


# ── 游戏目录辅助 ────────────────────────────────────────

def find_latest_bin_folder(game_path) -> str | None:
    """在游戏目录 bin/ 下查找最大的数字版本号子目录，返回目录名（如 '3859335'）。

    供 extractor_service / data_extractor / localization_service 共用，
    消除三处"找最新 bin 目录"的重复实现。无 bin 目录或无版本文件夹返回 None。
    """
    import os
    bin_path = os.path.join(str(game_path), "bin")
    if not os.path.exists(bin_path):
        return None
    folders = [f for f in os.listdir(bin_path)
               if f.isdigit() and os.path.isdir(os.path.join(bin_path, f))]
    if not folders:
        return None
    folders.sort(key=int)
    return folders[-1]
