import json
import os
import sys
import tkinter as tk

from NameMapping import Mapping as NameMapping

class ProjectileDataAnalyzer:

    def __init__(self, log_func=None):
        if getattr(sys, 'frozen', False):
            # 如果是打包后的路径
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是源代码路径
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_func = log_func  # 核心：保存 UI 传入的日志函数
        self.ammo_name_mapping = {}
        self.initialize_mapping()

    def initialize_mapping(self):
        self.load_ammo_name_mapping()

    def _log(self, message):
        """内部调用的日志工具"""
        if self.log_func:
            self.log_func(message)  # 如果有回调，发给 UI
        else:
            print(message)  # 否则打印到控制台

    def load_ammo_name_mapping(self):
        """加载由 POToolKit 生成的弹药翻译字典"""
        # 路径指向 POToolkit 生成的 ammo_names.json
        ammo_json_path = os.path.join(self.base_dir, "data", "ammo_names.json")
        if os.path.exists(ammo_json_path):
            try:
                with open(ammo_json_path, 'r', encoding='utf-8') as f:
                    self.ammo_name_mapping = json.load(f)
            except Exception as e:
                self.log_func(f"加载弹药翻译失败: {e}")

    def analyze(self, display_area, data):
        """
        解析并向 UI 插入弹药详细数据
        """
        # --- 1. 基础信息提取 ---
        proj_name = data.get("name", "Unknown_Projectile")
        proj_id = data.get("id", "N/A")
        proj_index = data.get("index", "N/A")
        final_name = self.ammo_name_mapping.get(proj_name.upper(), proj_name)

        type_info = data.get("typeinfo", {})
        species = type_info.get("species", "Unknown")
        raw_ammo_type = str(data.get("ammoType", "Unknown")).upper()

        ammo_sub_type = NameMapping.AMMO_TYPE_MAP.get(raw_ammo_type, "Unknown")

        nation_raw = type_info.get("nation", "Unknown")
        nation = NameMapping.NATION_MAP.get(nation_raw, nation_raw)

        display_type = NameMapping.PROJECTILE_TYPE_MAP.get(species, NameMapping.PROJECTILE_TYPE_MAP.get(raw_ammo_type.lower(), species))

        display_area.insert(tk.END, f"弹药名称: {final_name}\n"
                                    f"编号: {proj_index}\n"
                                    f"ID: {proj_id}\n"
                                    f"国家: {nation}\n"
                                    f"类型: {display_type}\n")
        display_area.insert(tk.END, "=" * 45 + "\n\n")

        alpha_dmg = data.get("alphaDamage", 0)
        dmg = data.get("damage", 0)

        # --- 2. 核心性能分支 ---

        # 火箭弹分支 (Rocket)
        if species == "Rocket":
            display_area.insert(tk.END, "[火箭弹属性]\n")
            display_area.insert(tk.END, f"  - 火箭弹类型: {ammo_sub_type}\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")

            # 物理参数
            display_area.insert(tk.END, f"  - 火箭弹质量: {data.get('bulletMass', 0)} kg\n")
            display_area.insert(tk.END, f"  - 火箭弹初速: {data.get('bulletSpeed', 0)} m/s\n")

            # 穿深与点火
            if raw_ammo_type == "HE":
                display_area.insert(tk.END, f"  - 穿深: {data.get('alphaPiercingHE', 0):.1f} mm\n")
                burn_prob = data.get("burnProb", 0) * 100
                display_area.insert(tk.END, f"  - 基础点火率: {burn_prob:.1f}%\n")
            elif raw_ammo_type == "CS":
                display_area.insert(tk.END, f"  - 穿深: {data.get('alphaPiercingCS', 0):.1f} mm\n")
            elif raw_ammo_type == "AP":
                display_area.insert(tk.END, f"  - 火箭弹硬度: {data.get('bulletKrupp', 0)}\n")

            # 攻击序列与物理参数
            seq = data.get("attackSequenceDurations", [])
            if seq:
                display_area.insert(tk.END, f"  - 攻击延迟序列: {seq} s\n")

            display_area.insert(tk.END, f"  - 飞行初速: {data.get('bulletSpeed', 0)} m/s\n")
            display_area.insert(tk.END, f"  - 爆炸损坏半径: {data.get('explosionRadius', 0) / 3:.1f} m\n")

        # 炸弹分支 (Bomb)
        elif species == "Bomb":
            display_area.insert(tk.END, "[炸弹属性]\n")
            display_area.insert(tk.END, f"  - 炸弹类型: {ammo_sub_type}\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")

            # 物理参数
            display_area.insert(tk.END, f"  - 炸弹质量: {data.get('bulletMass', 0)} kg\n")
            display_area.insert(tk.END, f"  - 投弹初速: {data.get('bulletSpeed', 0)} m/s\n")

            # 穿深与点火
            if raw_ammo_type == "HE":
                display_area.insert(tk.END, f"  - 穿深: {data.get('alphaPiercingHE', 0):.1f} mm\n")
                burn_prob = data.get("burnProb", 0) * 100
                display_area.insert(tk.END, f"  - 基础点火率: {burn_prob:.1f}%\n")
            elif raw_ammo_type == "CS":
                display_area.insert(tk.END, f"  - 穿深: {data.get('alphaPiercingCS', 0):.1f} mm\n")
            elif raw_ammo_type == "AP":
                display_area.insert(tk.END, f"  - 炸弹硬度: {data.get('bulletKrupp', 0)}\n")

            # 爆炸与范围
            exp_radius = data.get("explosionRadius", 0)
            display_area.insert(tk.END, f"  - 爆炸损坏半径: {exp_radius / 3:.1f} m\n")

            # 引信与跳弹 (AP 轰炸机特有)
            if raw_ammo_type in ["AP", "CS"]:
                display_area.insert(tk.END, "\n[引信与跳弹机制]\n")
                display_area.insert(tk.END, f"  - 强制跳弹角: {data.get('bulletAlwaysRicochetAt', 0)}°\n")
                display_area.insert(tk.END, f"  - 概率跳弹角: {data.get('bulletRicochetAt', 0)}°\n")
                if raw_ammo_type == "AP":
                    display_area.insert(tk.END, f"  - 引信长度: {data.get('bulletDetonator', 0)} s\n")
                    display_area.insert(tk.END, f"  - 引信触发阈值: {data.get('bulletDetonatorThreshold', 0)} mm\n")

        # 深水炸弹分支逻辑 (DepthCharge)
        elif species == "DepthCharge":
            display_area.insert(tk.END, "[深水炸弹属性]\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")

            # 深弹深度伤害系数 (核心威力衰减)
            buoyancy = data.get("buoyancyToDamageCoeff", {})
            if buoyancy:
                display_area.insert(tk.END, "  - 不同深度伤害效率:\n")
                order = ["SURFACE", "PERISCOPE", "SEMI_DEEP_WATER", "DEEP_WATER", "DEEP_WATER_INVUL"]
                for state in order:
                    if state in buoyancy:
                        coeff = buoyancy[state]
                        display_area.insert(tk.END, f"    * {NameMapping.BUOYANCY_MAP.get(state)}: {coeff * 100:.0f}%\n")

            # 物理与下潜参数
            display_area.insert(tk.END, f"\n  - 下潜速度: {data.get('speed', 0)} m/s\n")
            display_area.insert(tk.END, f"  - 爆炸计时: {data.get('timer', 0)} s\n")
            display_area.insert(tk.END, f"  - 最大自毁深度: {abs(data.get('maxDepth', 0))} m\n")

            # 溅射半径
            display_area.insert(tk.END, f"  - 对舰/潜溅射半径: {data.get('depthSplashSize', 0)} m\n")
            display_area.insert(tk.END, f"  - 对鱼雷溅射半径: {data.get('depthSplashSizeToTorpedo', 0)} m\n")

        # 鱼雷分支逻辑 (Torpedo)
        elif species == "Torpedo":
            # 确定细分鱼雷类型
            burnProb = data.get("burnProb", 0) * 100
            t_type = data.get("torpedoType", 0)
            is_deep = data.get("isDeepWater", False)
            is_burn = True if data.get("customUIPostfix") == "_subBurn" else False

            if t_type == 1:
                display_type = "声呐导向鱼雷"
            elif is_deep:
                display_type = "深水鱼雷"
            elif is_burn:
                display_type = "热能鱼雷"
            else:
                display_type = "鱼雷"

            display_area.insert(tk.END, "[鱼雷属性]\n")
            display_area.insert(tk.END, f"  - 类型: {display_type}\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg * 0.33:.0f}\n")
            display_area.insert(tk.END, f"  - 溅射伤害: {dmg:.0f}\n")

            # 热能鱼雷
            if is_burn:
                display_area.insert(tk.END, f"  - 基础点火率: {burnProb:.0f}%\n")

            # 深水鱼雷限制
            if is_deep:
                ignore_list = data.get("ignoreClasses", [])
                zh_ignores = [NameMapping.SHIP_CLASS_MAP.get(c, c) for c in ignore_list]
                display_area.insert(tk.END, f"  - 无法攻击目标: {', '.join(zh_ignores)}\n")

            # 航速与射程校准 (原始值 * 30 / 1000)
            raw_dist = data.get("maxDist", 0)
            display_area.insert(tk.END, f"  - 航速: {data.get('speed', 0)} kts\n")
            display_area.insert(tk.END, f"  - 最大射程: {(raw_dist * 30) / 1000:.1f} km\n")

            # 漏水系数百分比化 (uwCritical)
            uw_crit = data.get("uwCritical", 0)
            display_area.insert(tk.END, f"  - 基础漏水率: {uw_crit * 100:.0f}%\n")

            # 隐蔽与触发
            display_area.insert(tk.END, f"  - 被发现距离: {data.get('visibilityFactor', 0)} km\n")
            display_area.insert(tk.END, f"  - 鱼雷触发延迟: {data.get('armingTime', 0)} s\n")

            # --- 潜艇导引鱼雷专属参数 ---
            if t_type == 1:
                sub_params = data.get("SubmarineTorpedoParams", {})
                if sub_params:
                    display_area.insert(tk.END, "\n[声呐导引性能]\n")

                    # 转向性能 (取列表首位)
                    max_yaw = sub_params.get("maxYaw", [0])[0]
                    yaw_speed = sub_params.get("yawChangeSpeed", [0])[0]
                    display_area.insert(tk.END, f"  - 最大转向角: {max_yaw}°\n")
                    display_area.insert(tk.END, f"  - 转向角速度: {yaw_speed}°/s\n")

                    # 关断距离 (导引停止距离)
                    drop_dist = sub_params.get("dropTargetAtDistance", {})
                    if drop_dist:
                        display_area.insert(tk.END, "  - 导引脱锁距离:\n")
                        for ship_class, dist_list in drop_dist.items():
                            zh_class = NameMapping.SHIP_CLASS_MAP.get(ship_class, ship_class)
                            val = dist_list[0] if isinstance(dist_list, list) else dist_list
                            display_area.insert(tk.END, f"    * {zh_class}: {val} m\n")

        # 火炮炮弹分支逻辑 (HE/AP/SAP)
        elif species == "Artillery":
            display_area.insert(tk.END, "[火炮炮弹属性]\n")
            mass = data.get("bulletMass", 0)
            diameter = data.get("bulletDiametr", 0) * 1000  # 转换为毫米
            speed = data.get("bulletSpeed", 0)
            drag = data.get("bulletAirDrag", 0)
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")

            display_area.insert(tk.END, f"  - 炮弹类型: {ammo_sub_type}\n")
            display_area.insert(tk.END, f"  - 炮弹质量: {mass} kg\n")
            display_area.insert(tk.END, f"  - 炮弹口径: {diameter:.1f} mm\n")
            display_area.insert(tk.END, f"  - 出膛初速: {speed} m/s\n")
            display_area.insert(tk.END, f"  - 阻力系数: {drag}\n")
            if raw_ammo_type == "AP":
                krupp = data.get("bulletKrupp", 0)
                display_area.insert(tk.END, f"  - 弹头硬度: {krupp}\n")

            if raw_ammo_type == "HE":
                he_pen = data.get("alphaPiercingHE", 0)
                burn_prob = data.get("burnProb", 0) * 100
                exp_radius = data.get("explosionRadius", 0)
                display_area.insert(tk.END, f"  - 穿深: {he_pen:.1f} mm\n")
                display_area.insert(tk.END, f"  - 基础点火率: {burn_prob:.1f}%\n")
                display_area.insert(tk.END, f"  - 爆炸损坏半径: {exp_radius / 3:.1f} m\n")  # 转换游戏内单位

            elif raw_ammo_type == "CS":  # SAP
                cs_pen = data.get("alphaPiercingCS", 0)
                display_area.insert(tk.END, f"  - 穿深: {cs_pen:.1f} mm\n")

            # 引信与跳弹机制 (AP/SAP)
            if raw_ammo_type in ["AP", "CS"]:
                display_area.insert(tk.END, "\n[引信与跳弹机制]\n")
                ric_always = data.get("bulletAlwaysRicochetAt", 0)
                ric_start = data.get("bulletRicochetAt", 0)
                norm = data.get("bulletCapNormalizeMaxAngle", 0)

                display_area.insert(tk.END, f"  - 强制跳弹角: {ric_always}°\n")
                display_area.insert(tk.END, f"  - 概率跳弹角: {ric_start}°\n")
                display_area.insert(tk.END, f"  - 弹头转正角: {norm}°\n")

                if raw_ammo_type == "AP":
                    detonator = data.get("bulletDetonator", 0)
                    threshold = data.get("bulletDetonatorThreshold", 0)
                    display_area.insert(tk.END, f"  - 引信长度: {detonator} s\n")
                    display_area.insert(tk.END, f"  - 引信触发阈值: {threshold} mm\n")

        # 激光分支逻辑
        elif species == "Laser":
            display_area.insert(tk.END, f"[激光属性]\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")
            # 激光通常将穿深数值放在 alphaPiercingHE
            pen = data.get("alphaPiercingHE", 0)
            display_area.insert(tk.END, f"  - 穿深: {pen:.1f} mm\n")
            display_area.insert(tk.END, f"  - 飞行初速: {data.get('bulletSpeed', 0)} m/s\n")

            # 激光特有的 HeatEffect (热效应)
            on_hit = data.get("onHit", {})
            heat_effect = on_hit.get("HeatEffect", {})
            if heat_effect:
                display_area.insert(tk.END, "\n[命中热效应]\n")
                display_area.insert(tk.END, f"  - 热量积累值: {heat_effect.get('heat', 0)}\n")
                display_area.insert(tk.END, f"  - 热效应半径: {heat_effect.get('heatZoneRadius', 0)} m\n")
                dmg_types = heat_effect.get("damageTypes", [])
                display_area.insert(tk.END, f"  - 影响伤害类型: {', '.join(dmg_types)}\n")

        # 波浪分支逻辑 (Wave)
        elif species == "Wave":
            display_area.insert(tk.END, f"[波浪属性]\n")
            display_area.insert(tk.END, f"  - 标伤: {alpha_dmg:.0f}\n")
            display_area.insert(tk.END, f"  - 最大伤害比例: {data.get('maxDamagePercent', 0):.1f}%\n")
            display_area.insert(tk.END, f"  - 最小伤害比例: {data.get('minDamagePercent', 0):.1f}%\n")

            display_area.insert(tk.END, f"\n  - 波浪扩散速度: {data.get('waveSpeed', 0)} m/s\n")
            display_area.insert(tk.END, f"  - 波浪覆盖扇区: {data.get('waveSector', 0)}°\n")

        # --- 4. 通用水下物理参数 (如有) ---
        if "bulletUnderwaterDistFactor" in data:
            display_area.insert(tk.END, "\n[水下物理参数]\n")
            display_area.insert(tk.END, f"  - 水下行程折减系数: {data.get('bulletUnderwaterDistFactor')}\n")
            display_area.insert(tk.END, f"  - 水下穿深折减系数: {data.get('bulletUnderwaterPenetrationFactor')}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")