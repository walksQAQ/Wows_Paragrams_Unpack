"""
数据提取服务 —— 通过解包工具从 .pkg 中提取 GameParams.data。

根据游戏版本自动选择对应的解包工具。
"""

from __future__ import annotations

import os
import shutil
import subprocess

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_tools_dir, get_data_dir, get_app_dir


_DATA_FILE_NAMES = ["GameParams.data", "GameParams_py2.data"]


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


def _pick_unpacker(game_path: str, latest_bin: str, wows_type: str) -> str:
    """根据服务器类型和版本号选择对应的解包工具"""
    import re
    tools_dir = get_tools_dir()
    if wows_type == "Wargaming":
        return str(tools_dir / "wowsunpack.exe")
    # Lesta: 判断版本选择 pfsunpack 或 pfsunpack2
    exe_path = os.path.join(game_path, "bin", latest_bin, "bin64", "Korabli64.exe")
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
        res = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(exe_path, None, size, res)
        ptr, u_size = ctypes.c_void_p(), ctypes.c_uint()
        current_ver = "Unknown"
        for lang in ['041904b0', '040904b0', '080404b0']:
            q = f"\\StringFileInfo\\{lang}\\FileVersion"
            if ctypes.windll.version.VerQueryValueW(res, q, ctypes.byref(ptr), ctypes.byref(u_size)):
                current_ver = ctypes.wstring_at(ptr)
                break
    except Exception:
        current_ver = "Unknown"
    ver_digits = [int(x) for x in re.findall(r'\d+', current_ver)]
    if ver_digits and tuple(ver_digits) >= (26, 6):
        return str(tools_dir / "pfsunpack2.exe")
    return str(tools_dir / "pfsunpack.exe")


def _extract_with_tool(target_dir, game_path, latest_bin, unpack_exe, app_dir):
    """使用解包工具从 .pkg 中提取 .data 文件"""
    idx_path = os.path.join(game_path, "bin", latest_bin, "idx")
    bus.log_message.emit(f"🔧 正在使用解包工具提取数据...")
    command = [unpack_exe, "-x", idx_path, "-p", "../../../res_packages",
               "-I", "content/*.data"]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(app_dir))
    try:
        stdout, stderr = proc.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise Exception("解包工具执行超时（180秒）")
    if proc.returncode != 0:
        err_msg = stderr.decode('utf-8', errors='replace').strip() or f"退出码 {proc.returncode}"
        raise Exception(f"解包失败: {err_msg}")
    found = False
    for fn in _DATA_FILE_NAMES:
        src = app_dir / "content" / fn
        if src.exists():
            shutil.move(str(src), str(target_dir / fn))
            found = True
    shutil.rmtree(str(app_dir / "content"), ignore_errors=True)
    if not found:
        raise Exception(f"解包完成但未找到 {_DATA_FILE_NAMES}")


def run_extract() -> None:
    ctx = app_ctx.ctx
    game_path = ctx.game_path
    wows_type = ctx.wows_type

    def _extract():
        import ctypes, re
        bus.task_progress.emit(5, "检测游戏版本")
        latest_bin = _get_latest_bin(game_path)
        if not latest_bin:
            raise Exception("无法找到有效的版本文件夹")
        app_ctx.set_bin_folder(latest_bin)

        bus.task_progress.emit(10, "读取版本号")
        # 读版本号
        exe_name = "WorldOfWarships64.exe" if wows_type == "Wargaming" else "Korabli64.exe"
        exe_path = os.path.join(game_path, "bin", latest_bin, "bin64", exe_name)
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
            res = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(exe_path, None, size, res)
            ptr, u_size = ctypes.c_void_p(), ctypes.c_uint()
            current_ver = "Unknown"
            for lang in ['041904b0', '040904b0', '080404b0']:
                q = f"\\StringFileInfo\\{lang}\\FileVersion"
                if ctypes.windll.version.VerQueryValueW(res, q, ctypes.byref(ptr), ctypes.byref(u_size)):
                    current_ver = ctypes.wstring_at(ptr)
                    break
        except Exception:
            current_ver = "Unknown"

        bus.task_progress.emit(15, "执行解包工具")  # noqa: F821
        # 选择解包工具并执行
        unpack_exe = _pick_unpacker(game_path, latest_bin, wows_type)
        if not os.path.isfile(unpack_exe):
            raise Exception(f"解包工具不存在: {unpack_exe}")
        target_path = get_data_dir()
        app_dir = get_app_dir()
        _extract_with_tool(target_path, game_path, latest_bin, unpack_exe, app_dir)

        # 清理可能残留的旧数据
        old_content = app_dir / "content"
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
