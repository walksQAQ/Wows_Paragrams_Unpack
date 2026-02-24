import ctypes
import os
import sys
import shutil
import subprocess

class GameParams_extractor:
    def __init__(self, game_path, wows_type):
        self.game_path = game_path
        self.wows_type = wows_type  # 确保赋值
        self.target_path = os.path.join(os.getcwd(), "data")

        # 确定工具路径
        if getattr(sys, 'frozen', False):
            base_tool_path = sys._MEIPASS
        else:
            base_tool_path = os.path.dirname(os.path.abspath(__file__))

        # 根据服务器类型选择工具和EXE名称
        if wows_type == "Wargaming":
            self.unpack_exe = os.path.join(base_tool_path, "wowsunpack.exe")
            self.exe_name = "WorldOfWarships64.exe"
        elif wows_type == "Lesta":
            self.unpack_exe = os.path.join(base_tool_path, "pfsunpack.exe")
            self.exe_name = "Korabli64.exe"

    def get_game_exe_version(self, game_path, latest_bin, exe_name):
        """隔离出来的代码：读取 EXE 的属性版本"""
        file_path = os.path.join(game_path, "bin", latest_bin, "bin64", exe_name)
        if not os.path.exists(file_path):
            return "Unknown"
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(file_path, None)
            res = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(file_path, None, size, res)

            # 锁定读取 "FileVersion"（即截图里文件版本那一行的值）
            ptr, u_size = ctypes.c_void_p(), ctypes.c_uint()
            # 兼容俄语、英语、中文内码
            for lang in ['041904b0', '040904b0', '080404b0']:
                query = f"\\StringFileInfo\\{lang}\\FileVersion"
                if ctypes.windll.version.VerQueryValueW(res, query, ctypes.byref(ptr), ctypes.byref(u_size)):
                    return ctypes.wstring_at(ptr)
            return "Unknown"
        except:
            return "Error"

    def _get_latest_bin(self):
        bin_path = os.path.join(self.game_path, "bin")
        if not os.path.exists(bin_path): return None
        folders = [f for f in os.listdir(bin_path) if f.isdigit() and os.path.isdir(os.path.join(bin_path, f))]
        if not folders: return None
        folders.sort(key=int)
        return folders[-1]

    def extract(self):
        try:
            latest_bin = self._get_latest_bin()
            if not latest_bin:
                return False, "无法在游戏目录中找到有效的版本文件夹"

            # --- 在解压开始前，清空 data 目录下的旧文件 ---
            old_files = ["GameParams.data", "GameParams_py2.data"]
            for old_name in old_files:
                old_path = os.path.join(self.target_path, old_name)
                if os.path.exists(old_path):
                    os.remove(old_path)

            # 调用隔离出的代码获取版本
            current_ver = self.get_game_exe_version(self.game_path, latest_bin, self.exe_name)

            idx_path = os.path.join(self.game_path, "bin", latest_bin, "idx")
            pkg_path = "../../../res_packages"

            # 执行解压
            command = [self.unpack_exe, "-x", idx_path, "-p", pkg_path, "-I", "content/*.data"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            stdout, stderr = process.communicate()

            # 识别文件
            possible_files = ["GameParams.data", "GameParams_py2.data"]
            source_file = None
            found_filename = ""
            for filename in possible_files:
                check_path = os.path.join(os.getcwd(), "content", filename)
                if os.path.exists(check_path):
                    source_file, found_filename = check_path, filename
                    break

            if source_file:
                dest_file = os.path.join(self.target_path, found_filename)
                if os.path.exists(dest_file):
                    os.remove(dest_file)
                shutil.move(source_file, dest_file)
                shutil.rmtree(os.path.join(os.getcwd(), "content"), ignore_errors=True)

                return True, {
                    "msg": f"提取成功: {self.wows_type} {current_ver}",
                    "version": current_ver,
                }
            return False, "未生成数据文件"
        except Exception as e:
            return False, f"提取失败: {str(e)}"

    def extract_scripts(self):
        """独立提取 scripts 文件夹 (结构与 extract 完全对齐)"""
        try:
            latest_bin = self._get_latest_bin()
            if not latest_bin:
                return False, "Scripts提取失败: 无法找到有效的版本文件夹"

            # 清理旧 scripts 目录
            scripts_dest_path = os.path.join(self.target_path, "scripts")
            if os.path.exists(scripts_dest_path):
                shutil.rmtree(scripts_dest_path)

            # 调用获取版本 (严格传入 3 个参数)
            current_ver = self.get_game_exe_version(self.game_path, latest_bin, self.exe_name)

            idx_path = os.path.join(self.game_path, "bin", latest_bin, "idx")
            pkg_path = "../../../res_packages"

            # 执行解压 - scripts/*
            command = [self.unpack_exe, "-x", idx_path, "-p", pkg_path, "-I", "scripts/*"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            process.communicate()

            # 移动结果目录
            temp_scripts_path = os.path.join(os.getcwd(), "scripts")
            if os.path.exists(temp_scripts_path):
                if not os.path.exists(self.target_path): os.makedirs(self.target_path)
                shutil.move(temp_scripts_path, scripts_dest_path)

                return True, {
                    "msg": f"Scripts 提取成功: {self.wows_type} {current_ver}",
                    "version": current_ver,
                }
            return False, "未生成 scripts 文件夹"
        except Exception as e:
            return False, f"Scripts 提取失败: {str(e)}"