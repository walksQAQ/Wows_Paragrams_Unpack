import json
import os
import sys
import tkinter as tk
from NameMapping import Mapping as NameMapping


class ModernizationDataAnalyzer:

    def __init__(self, log_func=None):
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # 核心修正：保存外部传入的回调函数
        self.external_log = log_func

        self.name_mapping = {}
        self.ship_name_mapping = {}
        self.initialize_mapping()

    def initialize_mapping(self):
        # 初始化加载
        self.load_mod_names()
        self.load_ship_names()

    def _log(self, message):
        """核心修正：内部统一调用的日志工具，不再与变量名冲突"""
        if self.external_log:
            self.external_log(message)
        else:
            print(f"[Log] {message}")

    def load_mod_names(self):
        json_path = os.path.join(self.base_dir, "data", "modernization_names.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8-sig') as f:
                    raw_data = json.load(f)
                    self.name_mapping = {str(k).upper(): v for k, v in raw_data.items()}
            except Exception as e:
                self._log(f"加载升级品翻译失败: {e}")  # 使用 _log
        else:
            self._log(f"找不到映射文件: {json_path}")  # 使用 _log

    def load_ship_names(self):
        mapping_path = os.path.join(self.base_dir, "data", "ship_names.json")
        try:
            if os.path.exists(mapping_path):
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    self.ship_name_mapping = json.load(f)
        except Exception as e:
            self._log(f"读取船名映射出错: {e}")  # 使用 _log

    def analyze(self, display_area, data):
        """解析并渲染数据"""
        # (这部分逻辑保持不变，只需确保内部不再调用 self.log_func 即可)
        mod_index = data.get("index", "Unknown")
        raw_name = data.get("name", mod_index)
        display_name = self.name_mapping.get(raw_name.upper(), raw_name)

        # ... 后续渲染代码 ...
        display_area.insert(tk.END, f"升级品名称: {display_name}\n")
        # (此处省略其余 analyze 代码，保持你原有的逻辑即可)