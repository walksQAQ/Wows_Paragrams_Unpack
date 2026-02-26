import tkinter as tk

import NameMapping

from NameMapping import Mapping as NameMapping

class ModernizationDataAnalyzer:

    def __init__(self, name_mapping=None):
        self.name_mapping = name_mapping or {}

    def analyze(self, display_area, data):
        """
        解析并向 UI 插入升级品（插件）详细数据
        """
        # --- 1. 基础信息提取 ---
        mod_index = data.get("index", "Unknown")
        mod_id = data.get("id", "N/A")
        raw_name = data.get("name", mod_index)

        # 尝试获取映射名，如果没有则美化原始 ID
        display_name = self.name_mapping.get(mod_index, raw_name)

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
            ("禁用舰船", data.get("excludes", [])),
            ("可用分类", data.get("group", [])),
            ("可用舰船", data.get("ships", [])),
            ("可用国籍", data.get("nation", [])),
            ("可用等级", data.get("shiplevel", [])),
            ("可用舰种", data.get("shiptype", [])),
        ]

        # 只有当限制列表不为空时才显示
        has_restriction = any(len(val) > 0 for _, val in restrictions)
        if has_restriction:
            display_area.insert(tk.END, "\n[使用限制]\n")
            for label, items in restrictions:
                if items:
                    display_area.insert(tk.END, f"  - {label}: {', '.join(map(str, items))}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")