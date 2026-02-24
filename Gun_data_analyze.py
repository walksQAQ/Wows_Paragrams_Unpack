import os
import json
import tkinter as tk


class GunDataAnalyzer:
    # 国家名称映射 (延用你的配置)
    NATION_MAP = {
        "USA": "美国", "Japan": "日本", "Germany": "德国", "Russia": "苏联",
        "United_Kingdom": "英国", "France": "法国", "Italy": "意大利",
        "Pan_Asia": "泛亚", "Europe": "欧洲", "Netherlands": "荷兰",
        "Commonwealth": "英联邦", "Pan_America": "泛美", "Spain": "西班牙"
    }

    # 武器种类映射
    SPECIES_MAP = {
        "Main": "主炮",
        "Secondary": "副炮",
        "Torpedo": "鱼雷发射管",
        "AAircraft": "防空炮",
        "DCharge": "深弹发射器"
    }

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

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
        species = self.SPECIES_MAP.get(species_raw, species_raw)

        nation_raw = type_info.get("nation", "Unknown")
        nation = self.NATION_MAP.get(nation_raw, nation_raw)

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
            # display_area.insert(tk.END, f"  - 射击扇区: {data.get('shootSector', [])}°\n")

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
            display_area.insert(tk.END, f"\n[精度参数]\n")
            # display_area.insert(tk.END, f"  - Sigma: {data.get('minRadius', 'N/A')}\n")

            # 纵向散步系数
            r_zero = data.get("radiusOnZero", 0)
            r_delim = data.get("radiusOnDelim", 0)
            r_max = data.get("radiusOnMax", 0)
            delim = data.get("delim", 0)
            display_area.insert(tk.END, f"  - 纵向散步系数: {r_zero} ~ {r_delim}(R={delim*100:.0f}%) ~ {r_max}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")