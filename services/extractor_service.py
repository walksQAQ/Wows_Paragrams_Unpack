"""
数据提取服务 —— 通过 data_extractor（纯 Python 解包器）从 .pkg 中提取 GameParams.data。

原实现依赖外部 exe（wowsunpack / pfsunpack / pfsunpack2），现统一改为
纯 Python 的 data_extractor 模块（见 data_extractor/extractor.py）。
"""

from __future__ import annotations

import ctypes
import os
import shutil

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_data_dir, get_app_dir


_DATA_FILE_NAMES = ["GameParams_py3.data", "GameParams_py2.data", "GameParams.data"]


def _get_latest_bin(game_path: str) -> str | None:
    bin_path = os.path.join(game_path, "bin")
    if not os.path.exists(bin_path):
        return None
    folders = [f for f in os.listdir(bin_path)
               if f.isdigit() and os.path.isdir(os.path.join(bin_path, f))]
    if not folders:
        return None
    folders.sort(key=int)
    return folders[-1]


def _read_exe_version(game_path: str, latest_bin: str, wows_type: str) -> str:
    """读取游戏主程序版本号（用于设置 app_ctx 版本）。"""
    exe_name = "WorldOfWarships64.exe" if wows_type == "Wargaming" else "Korabli64.exe"
    exe_path = os.path.join(game_path, "bin", latest_bin, "bin64", exe_name)
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
        res = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(exe_path, None, size, res)
        ptr, u_size = ctypes.c_void_p(), ctypes.c_uint()
        for lang in ['041904b0', '040904b0', '080404b0']:
            q = f"\\StringFileInfo\\{lang}\\FileVersion"
            if ctypes.windll.version.VerQueryValueW(res, q, ctypes.byref(ptr), ctypes.byref(u_size)):
                return ctypes.wstring_at(ptr)
    except Exception:
        pass
    return "Unknown"


def _extract_data_files(game_path: str, latest_bin: str, target_dir) -> list[str]:
    """用 data_extractor（纯 Python 解包器）从 .pkg 中提取 GameParams 数据文件。

    替代原外部 exe（wowsunpack / pfsunpack / pfsunpack2）方案，统一走
    data_extractor.GameExtractor（Kraken 纯 Python 解压，低内存流式写盘）。
    """
    from data_extractor import GameExtractor

    bus.log_message.emit("🔧 正在使用 data_extractor 提取数据...")
    extractor = GameExtractor(game_path, bin_folder=latest_bin)
    try:
        # 找到实际存在的 GameParams 数据文件（兼容 GameParams.data / _py2.data）
        candidates = [
            e for e in extractor.list_files(["content/GameParams*.data"])
            if not e.is_directory
        ]
        if not candidates:
            raise Exception(f"未在文件树中找到 {_DATA_FILE_NAMES}")
        found: list[str] = []
        for entry in candidates:
            filename = entry.path.rsplit("/", 1)[-1]
            out = target_dir / filename
            extractor.extract_single(entry.path, out)
            found.append(filename)
            bus.log_message.emit(f"✅ 已提取 {entry.path}")
        return found
    finally:
        extractor.close()


def run_extract() -> None:
    ctx = app_ctx.ctx
    game_path = ctx.game_path
    wows_type = ctx.wows_type

    def _extract():
        bus.task_progress.emit(5, "检测游戏版本")
        latest_bin = _get_latest_bin(game_path)
        if not latest_bin:
            raise Exception("无法找到有效的版本文件夹")
        app_ctx.set_bin_folder(latest_bin)

        bus.task_progress.emit(10, "读取版本号")
        current_ver = _read_exe_version(game_path, latest_bin, wows_type)

        bus.task_progress.emit(15, "执行解包")
        target_path = get_data_dir()
        _extract_data_files(game_path, latest_bin, target_path)

        # 清理可能残留的旧数据（原外部工具遗留的 content/ 目录）
        old_content = get_app_dir() / "content"
        if old_content.exists():
            shutil.rmtree(str(old_content), ignore_errors=True)

        return current_ver

    def _ok(version: str):
        app_ctx.set_game_version(version)
        app_ctx.set_game_data_state(True)
        bus.log_message.emit(f"✅ {version} 提取成功！")
        bus.task_progress.emit(50, "提取完成，准备解析")
        bus.can_process_data.emit(True)
        bus.data_loaded.emit(version)

    def _err(msg: str):
        bus.log_message.emit(f"❌ 提取失败: {msg}")
        bus.can_process_data.emit(False)
        bus.data_loaded.emit("")

    run_async(_extract, on_finished=_ok, on_error=_err)
