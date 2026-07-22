"""
ProjectileAnalyzer —— 弹药/投射物数据分析器。
"""

from __future__ import annotations

from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class ProjectileAnalyzer(BaseAnalyzer):

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        self.ammo_name_mapping: dict = {}

    def initialize_mapping(self) -> None:
        raw = self.load_json_mapping("ammo_names.json")
        self.ammo_name_mapping = {k.upper(): v for k, v in raw.items()}
        self._log("ProjectileAnalyzer 映射表已同步")

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        proj_name = raw_data.get("name", "Unknown_Projectile")
        proj_id = raw_data.get("id", "N/A")
        proj_index = raw_data.get("index", "N/A")
        final_name = self.ammo_name_mapping.get(proj_name.upper(), proj_name)

        type_info = raw_data.get("typeinfo", {})
        species = type_info.get("species", "Unknown")
        raw_ammo_type = str(raw_data.get("ammoType", "Unknown")).upper()
        ammo_sub_type = NM.AMMO_TYPE_MAP.get(raw_ammo_type, "Unknown")
        nation_raw = type_info.get("nation", "Unknown")
        nation = NM.NATION_MAP.get(nation_raw, nation_raw)
        display_type = NM.PROJECTILE_TYPE_MAP.get(species, species)

        t.writeln(f"弹药名称: {final_name}")
        t.writeln(f"编号: {proj_index}")
        t.writeln(f"ID: {proj_id}")
        t.writeln(f"国家: {nation}")
        t.writeln(f"类型: {display_type}")
        t.writeln()

        alpha_dmg = raw_data.get("alphaDamage", 0)
        dmg = raw_data.get("damage", 0)

        # ── 火箭弹 ────────────────────────────────────────
        if species == "Rocket":
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            t.writeln(f"火箭弹质量: {raw_data.get('bulletMass', 0)} kg")
            t.writeln(f"火箭弹初速: {raw_data.get('bulletSpeed', 0)} m/s")
            if raw_ammo_type == "HE":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingHE', 0):.1f} mm")
                t.writeln(f"基础点火率: {raw_data.get('burnProb', 0) * 100:.1f}%")
            elif raw_ammo_type == "CS":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingCS', 0):.1f} mm")
            elif raw_ammo_type == "AP":
                t.writeln(f"火箭弹硬度: {raw_data.get('bulletKrupp', 0)}")
            seq = raw_data.get("attackSequenceDurations", [])
            if seq:
                t.writeln(f"攻击延迟序列: {seq} s")
            t.writeln(f"爆炸损坏半径: {raw_data.get('explosionRadius', 0) / 3:.1f} m")

        # ── 炸弹 ──────────────────────────────────────────
        elif species == "Bomb":
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            t.writeln(f"炸弹质量: {raw_data.get('bulletMass', 0)} kg")
            t.writeln(f"投弹初速: {raw_data.get('bulletSpeed', 0)} m/s")
            if raw_ammo_type == "HE":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingHE', 0):.1f} mm")
                t.writeln(f"基础点火率: {raw_data.get('burnProb', 0) * 100:.1f}%")
            elif raw_ammo_type == "CS":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingCS', 0):.1f} mm")
            elif raw_ammo_type == "AP":
                t.writeln(f"炸弹硬度: {raw_data.get('bulletKrupp', 0)}")
            t.writeln(f"爆炸损坏半径: {raw_data.get('explosionRadius', 0) / 3:.1f} m")
            if raw_ammo_type in ["AP", "CS"]:
                t.writeln(f"强制跳弹角: {raw_data.get('bulletAlwaysRicochetAt', 0)}°")
                t.writeln(f"概率跳弹角: {raw_data.get('bulletRicochetAt', 0)}°")
                if raw_ammo_type == "AP":
                    t.writeln(f"引信长度: {raw_data.get('bulletDetonator', 0)} s")
                    t.writeln(f"引信触发阈值: {raw_data.get('bulletDetonatorThreshold', 0)} mm")

        # ── 深水炸弹 ──────────────────────────────────────
        elif species == "DepthCharge":
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            buoyancy = raw_data.get("buoyancyToDamageCoeff", {})
            if buoyancy:
                order = ["SURFACE", "PERISCOPE", "SEMI_DEEP_WATER", "DEEP_WATER", "DEEP_WATER_INVUL"]
                for state in order:
                    if state in buoyancy:
                        t.writeln(f"  {NM.BUOYANCY_MAP.get(state, state)}: {buoyancy[state] * 100:.0f}%")
            t.writeln(f"下潜速度: {raw_data.get('speed', 0)} m/s")
            t.writeln(f"爆炸计时: {raw_data.get('timer', 0)} s")
            t.writeln(f"最大自毁深度: {abs(raw_data.get('maxDepth', 0))} m")
            t.writeln(f"对舰/潜溅射半径: {raw_data.get('depthSplashSize', 0)} m")
            t.writeln(f"对鱼雷溅射半径: {raw_data.get('depthSplashSizeToTorpedo', 0)} m")

        # ── 鱼雷 ──────────────────────────────────────────
        elif species == "Torpedo":
            t_type = raw_data.get("torpedoType", 0)
            is_deep = raw_data.get("isDeepWater", False)
            is_burn = raw_data.get("customUIPostfix") == "_subBurn"
            burnProb = raw_data.get("burnProb", 0) * 100

            if t_type == 1:
                dtype = "声呐导向鱼雷"
            elif is_deep:
                dtype = "深水鱼雷"
            elif is_burn:
                dtype = "热能鱼雷"
            else:
                dtype = "鱼雷"

            t.writeln(f"类型: {dtype}")
            t.writeln(f"标伤: {alpha_dmg * 0.33:.0f}")
            t.writeln(f"溅射伤害: {dmg:.0f}")
            if is_burn:
                t.writeln(f"基础点火率: {burnProb:.0f}%")
            if is_deep:
                ignores = [NM.SHIP_CLASS_MAP.get(c, c) for c in raw_data.get("ignoreClasses", [])]
                t.writeln(f"无法攻击目标: {', '.join(ignores)}")
            raw_dist = raw_data.get("maxDist", 0)
            t.writeln(f"航速: {raw_data.get('speed', 0)} kts")
            t.writeln(f"最大射程: {(raw_dist * 30) / 1000:.1f} km")
            t.writeln(f"基础漏水率: {raw_data.get('uwCritical', 0) * 100:.0f}%")
            t.writeln(f"被发现距离: {raw_data.get('visibilityFactor', 0)} km")
            t.writeln(f"鱼雷触发延迟: {raw_data.get('armingTime', 0)} s")
            if t_type == 1:
                sp = raw_data.get("SubmarineTorpedoParams", {})
                if sp:
                    t.writeln(f"最大转向角: {sp.get('maxYaw', [0])[0]}°")
                    t.writeln(f"转向角速度: {sp.get('yawChangeSpeed', [0])[0]}°/s")
                    drop = sp.get("dropTargetAtDistance", {})
                    if drop:
                        for ship_class, dist_list in drop.items():
                            val = dist_list[0] if isinstance(dist_list, list) else dist_list
                            t.writeln(f"  {NM.SHIP_CLASS_MAP.get(ship_class, ship_class)}: {val} m")

        # ── 火炮炮弹 ──────────────────────────────────────
        elif species == "Artillery":
            mass = raw_data.get("bulletMass", 0)
            diameter = raw_data.get("bulletDiametr", 0) * 1000
            speed = raw_data.get("bulletSpeed", 0)
            drag = raw_data.get("bulletAirDrag", 0)
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            t.writeln(f"炮弹类型: {ammo_sub_type}")
            t.writeln(f"炮弹质量: {mass} kg")
            t.writeln(f"炮弹口径: {diameter:.1f} mm")
            t.writeln(f"出膛初速: {speed} m/s")
            t.writeln(f"阻力系数: {drag}")
            if raw_ammo_type == "AP":
                t.writeln(f"弹头硬度: {raw_data.get('bulletKrupp', 0)}")
            if raw_ammo_type == "HE":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingHE', 0):.1f} mm")
                t.writeln(f"基础点火率: {raw_data.get('burnProb', 0) * 100:.1f}%")
                t.writeln(f"爆炸损坏半径: {raw_data.get('explosionRadius', 0) / 3:.1f} m")
            elif raw_ammo_type == "CS":
                t.writeln(f"穿深: {raw_data.get('alphaPiercingCS', 0):.1f} mm")
            if raw_ammo_type in ["AP", "CS"]:
                t.writeln(f"强制跳弹角: {raw_data.get('bulletAlwaysRicochetAt', 0)}°")
                t.writeln(f"概率跳弹角: {raw_data.get('bulletRicochetAt', 0)}°")
                t.writeln(f"弹头转正角: {raw_data.get('bulletCapNormalizeMaxAngle', 0)}°")
                if raw_ammo_type == "AP":
                    t.writeln(f"引信长度: {raw_data.get('bulletDetonator', 0)} s")
                    t.writeln(f"引信触发阈值: {raw_data.get('bulletDetonatorThreshold', 0)} mm")

        # ── 激光 ──────────────────────────────────────────
        elif species == "Laser":
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            t.writeln(f"穿深: {raw_data.get('alphaPiercingHE', 0):.1f} mm")
            t.writeln(f"飞行初速: {raw_data.get('bulletSpeed', 0)} m/s")
            on_hit = raw_data.get("onHit", {})
            heat = on_hit.get("HeatEffect", {})
            if heat:
                t.writeln(f"热量积累值: {heat.get('heat', 0)}")
                t.writeln(f"热效应半径: {heat.get('heatZoneRadius', 0)} m")
                t.writeln(f"影响伤害类型: {', '.join(heat.get('damageTypes', []))}")

        # ── 波浪 ──────────────────────────────────────────
        elif species == "Wave":
            t.writeln(f"标伤: {alpha_dmg:.0f}")
            t.writeln(f"最大伤害比例: {raw_data.get('maxDamagePercent', 0):.1f}%")
            t.writeln(f"最小伤害比例: {raw_data.get('minDamagePercent', 0):.1f}%")
            t.writeln(f"波浪扩散速度: {raw_data.get('waveSpeed', 0)} m/s")
            t.writeln(f"波浪覆盖扇区: {raw_data.get('waveSector', 0)}°")

        t.writeln()

        return t.result(title=final_name, subtitle=f"编号: {proj_index} | {display_type}")
