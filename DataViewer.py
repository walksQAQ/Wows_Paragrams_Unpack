import os
import json
import sys
import tkinter as tk

from Ship_data_analyze import ShipDataAnalyzer
from Projectile_data_analyze import ProjectileDataAnalyzer
from Gun_data_analyze import GunDataAnalyzer
from Modernization_data_analyze import ModernizationDataAnalyzer

class DataViewer:
    def __init__(self, folder_listbox, file_listbox, display_area):
        self.folder_listbox = folder_listbox
        self.file_listbox = file_listbox
        self.display_area = display_area
        # 确保路径指向主程序目录下的 data/split
        if getattr(sys, 'frozen', False):
            # 打包后的路径
            self.main_dir = os.path.dirname(sys.executable)
        else:
            # 源码运行路径
            self.main_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_path = os.path.join(os.getcwd(), "data", "split")
        self.current_folder = ""
        self.ship_analyzer = ShipDataAnalyzer()  # 实例化一次，加载一次映射表
        self.projectile_analyzer = ProjectileDataAnalyzer()  # 实例化一次，加载一次映射表
        self.gun_analyzer = GunDataAnalyzer()  # 实例化一次，加载一次映射表
        self.modernization_analyzer = ModernizationDataAnalyzer() # 实例化一次，加载一次映射表

    def refresh(self):
        self.folder_listbox.delete(0, tk.END)
        if not os.path.exists(self.base_path): return
        folders = [f for f in os.listdir(self.base_path) if os.path.isdir(os.path.join(self.base_path, f))]
        for f in sorted(folders):
            self.folder_listbox.insert(tk.END, f"📁 {f}")

    def reload_all_analyzers(self, log_func=None):
        """
        统一刷新所有内嵌分析器的翻译映射，并发送日志到 UI
        """
        if log_func:
            log_func("正在同步所有分析器的本地化字典...")
        self.ship_analyzer.initialize_mapping()
        # TODO:还没写的初始化映射表
        # self.projectile_analyzer.initialize_mapping()
        # self.gun_analyzer.initialize_mapping()
        # self.modernization_analyzer.initialize_mapping()
        # 如果需要，也可以在此处打印日志确认
        if log_func:
            log_func("分析器映射表重载完成")

    def on_folder_select(self, event):
        selection = self.folder_listbox.curselection()
        if not selection: return
        self.file_listbox.delete(0, tk.END)
        self.current_folder = self.folder_listbox.get(selection[0]).replace("📁 ", "")
        target_path = os.path.join(self.base_path, self.current_folder)

        if os.path.exists(target_path):
            files = [f for f in os.listdir(target_path) if f.endswith(".json")]
            for f in sorted(files):
                # 核心改动：使用 splitext 移除 .json 后缀展示
                file_name_only = os.path.splitext(f)[0]
                self.file_listbox.insert(tk.END, f"📄 {file_name_only}")

    def on_file_select(self, event):
        selection = self.file_listbox.curselection()
        if not selection or not self.current_folder: return

        file_display_name = self.file_listbox.get(selection[0]).replace("📄 ", "")
        file_path = os.path.join(self.base_path, self.current_folder, f"{file_display_name}.json")

        self.display_area.delete("1.0", tk.END)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # --- 逻辑分流 ---
            if self.current_folder == "Ship":
                # 调用分离出来的舰船分析代码
                self.ship_analyzer.analyze(self.display_area, data)
            elif self.current_folder == "Projectile":
                self.projectile_analyzer.analyze(self.display_area, data)
            elif self.current_folder == "Gun":
                self.gun_analyzer.analyze(self.display_area, data)
            elif self.current_folder == "Modernization":
                self.modernization_analyzer.analyze(self.display_area, data)
            else:
                # 默认逻辑：显示原始 JSON 格式化文本
                self._display_raw_json(data)


        except Exception as e:

            self.display_area.insert(tk.END, f"读取或分析数据失败: {e}")

    def _display_raw_json(self, data):

        """通用 JSON 展示逻辑"""

        self.display_area.insert(tk.END, json.dumps(data, indent=4, ensure_ascii=False))