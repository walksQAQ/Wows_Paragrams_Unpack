import os
import sys
import tkinter as tk

from NameMapping import Mapping as NameMapping

class GunDataAnalyzer:

    def __init__(self, log_func=None):
        if getattr(sys, 'frozen', False):
            # 如果是打包后的路径
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是源代码路径
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_func = log_func  # 核心：保存 UI 传入的日志函数

    def initialize_mapping(self):
        self._log("Nothing to initialize")

    def _log(self, message):
        """内部调用的日志工具"""
        if self.log_func:
            self.log_func(message)  # 如果有回调，发给 UI
        else:
            print(message)  # 否则打印到控制台

    def get_dispersion_formula(self, weapon_data):
        """
        根据统一逻辑解析横向散布公式: Rh = (IR-MR)/(ID/1000) * R + MR*30
        """
        ir = weapon_data.get('idealRadius')
        mr = weapon_data.get('minRadius')
        id_dist = weapon_data.get('idealDistance')

        if ir is None or mr is None or id_dist is None:
            return "数据缺失"

        # 1. 计算斜率 (处理 ID 差异)
        slope = (ir - mr) / (id_dist / 1000)
        # 2. 计算截距 (MR * 30)
        intercept = mr * 30

        # 返回格式化后的字符串
        return f"{round(slope, 2)}R + {round(intercept, 2)}"

    def analyze(self, display_area, data):
        """
        解析并向 UI 插入武器模块详细数据
        """
        # --- 1. 基础信息提取 ---
        gun_name = data.get("name", "Unknown_Gun")
        gun_id = data.get("id", "N/A")
        gun_index = data.get("index", "N/A")

        type_info = data.get("typeinfo", {})
        species_raw = type_info.get("species", "Unknown")
        species = NameMapping.WEAPON_SPECIES_MAP.get(species_raw, species_raw)

        nation_raw = type_info.get("nation", "Unknown")
        nation = NameMapping.NATION_MAP.get(nation_raw, nation_raw)

        display_area.insert(tk.END, f"组件名称: {gun_name}\n"
                                    f"组件编号: {gun_index}\n"
                                    f"ID: {gun_id}\n"
                                    f"国家: {nation}\n"
                                    f"种类: {species}\n")
        display_area.insert(tk.END, "=" * 45 + "\n\n")

        # --- 2. 核心性能参数 ---

        # 炮身/管径参数
        num_barrels = data.get("numBarrels", 1)
        display_area.insert(tk.END, f"[通用属性]\n")
        display_area.insert(tk.END, f"  - 联装数: {num_barrels}\n")
        if "barrelDiameter" in data:
            barrel_diameter = data.get("barrelDiameter", 0) * 1000  # 换算为mm
            display_area.insert(tk.END, f"  - 火炮口径: {barrel_diameter:.1f} mm\n")

        # 装填与射击
        if "shotDelay" in data:
            shot_delay = data.get("shotDelay", 0)
            display_area.insert(tk.END, f"  - 装填时间: {shot_delay:.1f} s\n")

        # 旋转速度
        if "rotationSpeed" in data:
            rot_speed = data.get("rotationSpeed", [0, 0])
            display_area.insert(tk.END, f"  - 水平回转速度: {rot_speed[0]} °/s\n")
            display_area.insert(tk.END, f"  - 垂直回转速度: {rot_speed[1]} °/s\n")

        # 弹药列表
        ammo_list = data.get("ammoList", [])
        if ammo_list:
            display_area.insert(tk.END, f"  - 可用弹药: {', '.join(ammo_list)}\n")

        # --- 3. 模块血量 (HitLocation) ---
        # 寻找 JSON 中以 HitLocation 开头的键
        hl_key = next((k for k in data.keys() if k.startswith("HitLocation")), None)
        if hl_key:
            hl_data = data[hl_key]
            display_area.insert(tk.END, f"\n[模块生存性]\n")
            display_area.insert(tk.END, f"  - 模块血量: {hl_data.get('maxHP', 0):.0f}\n")
            display_area.insert(tk.END, f"  - 自动维修时间: {hl_data.get('autoRepairTime', 0)} s\n")
            display_area.insert(tk.END, f"    - 最短自动维修时间: {hl_data.get('autoRepairTimeMin', 0)} s\n")

        # --- 4. 分支逻辑 (特定武器属性) ---

        # 鱼雷管特有逻辑
        if species_raw == "Torpedo":
            display_area.insert(tk.END, f"\n[鱼雷管属性]\n")
            t_angles = data.get("torpedoAngles", [])
            if t_angles:
                display_area.insert(tk.END, f"  - 鱼雷散布界: {t_angles}°\n")
                display_area.insert(tk.END, f"  - 鱼雷最短射击间隔: {data.get('timeBetweenShots',0)} s\n")

            # 弹鼓/序列装填参数
            drum_params = data.get("drumChargeTimeParams", [])
            if any(v != 0 for v in drum_params[:2]):  # 只有当参数不全为0时显示
                display_area.insert(tk.END, f"\n[特殊装填机制]\n")
                display_area.insert(tk.END, f"  - 弹鼓基础装填时间: {drum_params[0]} s\n")
                display_area.insert(tk.END, f"  - 序列增量时间: {drum_params[1]} s\n")

        # 防空/副炮特有逻辑 (光环距离/强度)
        if "antiAirAuraDistance" in data:
            dist = data.get("antiAirAuraDistance", 0)

        # 散布参数 (主炮/副炮)
        if "idealRadius" in data:
            display_area.insert(tk.END, f"\n[精度与散布参数]\n")

            # 调用提取出的公式函数
            h_formula = self.get_dispersion_formula(data)

            # 纵向散步系数 (Raw)
            rz = data.get("radiusOnZero", 0)
            rd = data.get("radiusOnDelim", 0)
            rm = data.get("radiusOnMax", 0)
            dl = data.get("delim", 0)

            display_area.insert(tk.END, f"  - 默认横向散布公式: {h_formula}\n")
            display_area.insert(tk.END, f"  - 默认纵向散步系数: {rz} ~ {rd}(R={dl*100:.0f}%) ~ {rm}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")