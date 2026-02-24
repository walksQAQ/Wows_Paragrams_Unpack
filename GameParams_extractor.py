import ctypes
import os
import sys
import shutil
import subprocess

class GameParams_extractor:
    def __init__(self, game_path, wows_type):
        self.game_path = game_path
        self.wows_type = wows_type

        # --- 路径定位逻辑：区分内部工具和外部数据 ---
        if getattr(sys, 'frozen', False):
            # 打包后的物理目录（EXE 所在位置）
            self.exe_dir = os.path.dirname(sys.executable)
            # 打包后的内部资源目录（临时解压路径）
            self.base_tool_path = sys._MEIPASS
        else:
            # 源码运行目录
            self.exe_dir = os.path.dirname(os.path.abspath(__file__))
            self.base_tool_path = self.exe_dir

        # 锁定外部 data 目录
        self.target_path = os.path.join(self.exe_dir, "data")

        # 根据服务器类型选择内部工具
        if wows_type == "Wargaming":
            self.unpack_exe = os.path.join(self.base_tool_path, "wowsunpack.exe")
            self.exe_name = "WorldOfWarships64.exe"
        elif wows_type == "Lesta":
            self.unpack_exe = os.path.join(self.base_tool_path, "pfsunpack.exe")
            self.exe_name = "Korabli64.exe"

    def get_game_exe_version(self, game_path, latest_bin, exe_name):
        """读取文件属性版本"""
        file_path = os.path.join(game_path, "bin", latest_bin, "bin64", exe_name)
        if not os.path.exists(file_path):
            return "Unknown"
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(file_path, None)
            res = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(file_path, None, size, res)
            ptr, u_size = ctypes.c_void_p(), ctypes.c_uint()
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
        """提取 GameParams.data"""
        try:
            latest_bin = self._get_latest_bin()
            if not latest_bin:
                return False, "无法找到有效的版本文件夹"

            # 确保外部目标目录存在
            os.makedirs(self.target_path, exist_ok=True)

            # 清理旧文件
            old_files = ["GameParams.data", "GameParams_py2.data"]
            for old_name in old_files:
                old_path = os.path.join(self.target_path, old_name)
                if os.path.exists(old_path): os.remove(old_path)

            current_ver = self.get_game_exe_version(self.game_path, latest_bin, self.exe_name)

            idx_path = os.path.join(self.game_path, "bin", latest_bin, "idx")
            pkg_path = "../../../res_packages"

            # 执行解压：cwd=self.exe_dir 确保产生的 content 文件夹在 EXE 旁边
            command = [self.unpack_exe, "-x", idx_path, "-p", pkg_path, "-I", "content/*.data"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
                                       cwd=self.exe_dir)
            process.communicate()

            # 移动结果文件
            possible_files = ["GameParams.data", "GameParams_py2.data"]
            found = False
            for filename in possible_files:
                temp_src = os.path.join(self.exe_dir, "content", filename)
                if os.path.exists(temp_src):
                    dest_file = os.path.join(self.target_path, filename)
                    shutil.move(temp_src, dest_file)
                    found = True

            # 清理临时目录
            shutil.rmtree(os.path.join(self.exe_dir, "content"), ignore_errors=True)

            if found:
                return True, {"msg": f"提取成功: {self.wows_type} {current_ver}", "version": current_ver}
            return False, "未生成数据文件，请检查解压工具是否正常运行"
        except Exception as e:
            return False, f"提取失败: {str(e)}"

    def extract_scripts(self):
        """独立提取 scripts 文件夹"""
        try:
            latest_bin = self._get_latest_bin()
            if not latest_bin:
                return False, "无法找到有效的版本文件夹"

            # 清理旧外部目录
            scripts_dest_path = os.path.join(self.target_path, "scripts")
            if os.path.exists(scripts_dest_path):
                shutil.rmtree(scripts_dest_path)

            current_ver = self.get_game_exe_version(self.game_path, latest_bin, self.exe_name)

            idx_path = os.path.join(self.game_path, "bin", latest_bin, "idx")
            pkg_path = "../../../res_packages"

            # 执行解压
            command = [self.unpack_exe, "-x", idx_path, "-p", pkg_path, "-I", "scripts/*"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
                                       cwd=self.exe_dir)
            process.communicate()

            # 移动目录
            temp_scripts_path = os.path.join(self.exe_dir, "scripts")
            if os.path.exists(temp_scripts_path):
                # 确保外部 data 目录存在
                os.makedirs(self.target_path, exist_ok=True)
                shutil.move(temp_scripts_path, scripts_dest_path)
                return True, {"msg": f"Scripts 提取成功: {self.wows_type} {current_ver}", "version": current_ver}
            return False, "未生成 scripts 文件夹"
        except Exception as e:
            return False, f"Scripts 提取失败: {str(e)}"