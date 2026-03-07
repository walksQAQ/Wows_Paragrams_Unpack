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

    def initialize_mapping(self):
        # 初始化加载
        self.load_mod_names()
        self.load_ship_names()
        self._log("升级品解析器映射表已同步")

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
        mod_id = data.get("id", "N/A")
        display_name = self.name_mapping.get(raw_name.upper(), raw_name)
        
        cost = data.get("costCR", 0)
        slot = data.get("slot", 0)
        slot_str = f"第 {slot+1} 槽位" if slot != -1 else f"已禁用升级品"

        display_area.insert(tk.END, f"升级品名称: {display_name}\n"
                                    f"编号: {mod_index}\n"
                                    f"ID: {mod_id}\n"
                                    f"价格: {cost:,} 银币\n"
                                    f"安装槽位: {slot_str}\n")
        display_area.insert(tk.END, "=" * 45 + "\n\n")

        # --- 2. 核心加成属性 (Modifiers) ---
        # 定义不需要计算百分比、直接显示原值的词条
        NO_PERCENTAGE_KEYS = {"planeExtraHangarSize","AAAuraDamageBonus","additionalConsumables","planeAdditionalConsumables","AAExtraBubbles","smokeGeneratorAdditionalConsumables","asNumPacksBonus","speedBoostersAdditionalConsumables"}
        FACTOR_KEYS = {"AABubbleDamageBonus"}
        SECOND_KEYS = {"crashCrewWorkTimeBonus","torpedoBomberAimingTime","fighterAimingTime"}
        KILOMETER_KEYS = {"visionXRayMineDist","visionXRayTorpedoDist"}
        SP_PERCENT_KEYS = {"engineBackwardForsageMaxSpeed", "engineBackwardForsagePower", "engineForwardForsageMaxSpeed", "engineForwardForsagePower","hydrophoneWaveSpeedCoeff","regeneratedHPPartCoef","boostCoeffForsage"}

        modifiers = data.get("modifiers", {})
        if modifiers:
            display_area.insert(tk.END, "[属性加成]\n")
            for key, value in modifiers.items():
                label = NameMapping.MODIFIER_MAP.get(key, key)

                # 数值转化逻辑
                if isinstance(value, dict):
                    display_area.insert(tk.END, f"  - {label}:\n")
                    for ship_type, factor in value.items():
                        short_name = NameMapping.SHIP_CLASS_MAP.get(ship_type, ship_type)

                        # 对字典内的数值同样进行百分比/原值判定
                        if key in NO_PERCENTAGE_KEYS:
                            display_area.insert(tk.END, f"      {short_name}: {factor}\n")
                        else:
                            percent = round((factor - 1.0) * 100, 3)
                            percent_str = f"{percent:g}"  # 自动处理小数位，7.5% 不丢，10.0% 变 10%
                            sign = "+" if percent > 0 else ""
                            display_area.insert(tk.END, f"      {short_name}: {sign}{percent_str}%\n")

                elif isinstance(value, (float, int)):
                    # 逻辑：如果 key 在排除列表中，直接显示原值
                    if key in NO_PERCENTAGE_KEYS:
                        value = f"+{value}" if value > 0 else f"{value}"
                        display_area.insert(tk.END, f"  - {label}: {value}\n")
                    elif key in FACTOR_KEYS:
                        result = round(value * 7, 3)
                        sign = "+" if result > 0 else ""
                        display_area.insert(tk.END, f"      {label}: {sign}{result:.0f}\n")
                    elif key in SECOND_KEYS:
                        value = f"+{value}" if value > 0 else f"{value}"
                        display_area.insert(tk.END, f"  - {label}: {value}s\n")
                    elif key in KILOMETER_KEYS:
                        percent = value/1000
                        display_area.insert(tk.END, f"  - {label}: {percent}km\n")
                    elif key in SP_PERCENT_KEYS:
                        percent = round(value * 100, 1)

                        # 如果是整数位（比如 20.0），则去掉小数点显示为 20
                        if percent == int(percent):
                            percent = int(percent)
                        sign = "+" if percent > 0 else ""
                        display_area.insert(tk.END, f"  - {label}: {sign}{percent}%\n")
                    else:
                        # 否则执行百分比转化逻辑 (0.8 -> -20%, 1.1 -> +10%)
                        percent = round((value - 1.0) * 100, 3)
                        percent_str = f"{percent:g}"
                        sign = "+" if percent > 0 else ""
                        # 针对减益属性，负值通常代表“强化”
                        display_area.insert(tk.END, f"  - {label}: {sign}{percent_str}%\n")
                else:
                    display_area.insert(tk.END, f"  - {label}: {value}\n")

        # --- 3. 限制条件 (Restrictions) ---
        # 检查是否有特定的限制列表
        restrictions = [
            ("禁用舰船", self.ship_name_map_restrict_list(data.get("excludes", []), self.ship_name_mapping)),
            ("可用舰船", self.ship_name_map_restrict_list(data.get("ships", []), self.ship_name_mapping)),
            ("可用分类", self.map_restrict_list(data.get("group", []), NameMapping.SHIP_GROUP_MAP)),
            ("可用国籍", self.map_restrict_list(data.get("nation", []), NameMapping.NATION_MAP)),
            ("可用舰种", self.map_restrict_list(data.get("shiptype", []), NameMapping.SHIP_CLASS_MAP)),
            ("可用等级", data.get("shiplevel", [])),
        ]

        # 只有当限制列表不为空时才显示
        has_restriction = any(len(val) > 0 for _, val in restrictions)
        if has_restriction:
            display_area.insert(tk.END, "\n[使用限制]\n")
            for label, items in restrictions:
                if items:
                    display_area.insert(tk.END, f"  - {label}: {', '.join(map(str, items))}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")

    # 内部工具函数：将 ID 列表转为中文名
    def map_restrict_list(self, items, mapping_dict, fallback_prefix=""):
        if not items: return []
        result = []
        for i in items:
            key = str(i)
            # 优先级：映射表 -> 加上前缀后的映射表(针对等级等) -> 原样返回
            name = mapping_dict.get(key, mapping_dict.get(f"{fallback_prefix}{key}", key))
            result.append(name)
        return result

    def ship_name_map_restrict_list(self, items, mapping_dict):
        """
        专项处理：解决 PASB012_North_Carolina_1945 匹配 PASB012 的问题
        """
        if not items:
            return []

        result = []
        for raw_id in items:
            # 1. 处理长 ID：截取第一个下划线前的部分 (如 PASB012)
            # 2. 统一转大写
            clean_id = str(raw_id).split('_')[0].upper()

            # 3. 匹配策略
            name = mapping_dict.get(clean_id) or \
                   mapping_dict.get(f"IDS_{clean_id}") or \
                   raw_id  # 找不到则显示原始长 ID

            result.append(name)
        return result