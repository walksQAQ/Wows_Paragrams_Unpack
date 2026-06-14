"""
数据提取服务 —— 从游戏安装目录提取 GameParams.data。

通过调用 tools/ 下的外部解包程序完成提取。
"""

from __future__ import annotations

import os
import shutil
import subprocess

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_tools_dir, get_data_dir, get_app_dir


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


def run_extract() -> None:
    ctx = app_ctx.ctx
    game_path = ctx.game_path
    wows_type = ctx.wows_type

    def _extract():
        import ctypes, re
        latest_bin = _get_latest_bin(game_path)
        if not latest_bin:
            raise Exception("无法找到有效的版本文件夹")

        tools_dir = get_tools_dir()
        exe_name = "WorldOfWarships64.exe" if wows_type == "Wargaming" else "Korabli64.exe"
        exe_path = os.path.join(game_path, "bin", latest_bin, "bin64", exe_name)

        # 读版本号
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

        # 选解包工具
        if wows_type == "Wargaming":
            unpack_exe = str(tools_dir / "wowsunpack.exe")
        else:
            ver_digits = [int(x) for x in re.findall(r'\d+', current_ver)]
            if ver_digits and tuple(ver_digits) >= (26, 6):
                unpack_exe = str(tools_dir / "pfsunpack2.exe")
            else:
                unpack_exe = str(tools_dir / "pfsunpack.exe")

        target_path = get_data_dir()
        idx_path = os.path.join(game_path, "bin", latest_bin, "idx")
        app_dir = get_app_dir()

        # 检查解包工具是否存在
        if not os.path.isfile(unpack_exe):
            raise Exception(f"解包工具不存在: {unpack_exe}")

        command = [unpack_exe, "-x", idx_path, "-p", "../../../res_packages", "-I", "content/*.data"]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(app_dir))
        try:
            stdout, stderr = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise Exception(f"解包工具执行超时（120秒）")
        if proc.returncode != 0:
            err_msg = stderr.decode('utf-8', errors='replace').strip() or f"退出码 {proc.returncode}"
            raise Exception(f"解包工具执行失败: {err_msg}")

        found = False
        for fn in ["GameParams.data", "GameParams_py2.data"]:
            src = app_dir / "content" / fn
            if src.exists():
                shutil.move(str(src), str(target_path / fn))
                found = True
        shutil.rmtree(str(app_dir / "content"), ignore_errors=True)
        if not found:
            raise Exception(f"未在 {app_dir / 'content'} 找到生成的数据文件，请检查解包工具")
        return current_ver

    def _ok(version: str):
        app_ctx.set_game_version(version)
        app_ctx.set_game_data_state(True)
        bus.log_message.emit(f"✅ {version} 提取成功！")
        bus.can_process_data.emit(True)
        bus.data_loaded.emit(version)

    def _err(msg: str):
        bus.log_message.emit(f"❌ 提取失败: {msg}")
        bus.can_process_data.emit(False)
        bus.data_loaded.emit("")

    run_async(_extract, on_finished=_ok, on_error=_err)
