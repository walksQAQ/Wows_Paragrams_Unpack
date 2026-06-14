"""
GunAnalyzer —— 武器/火炮数据分析器。
"""

from __future__ import annotations

from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class GunAnalyzer(BaseAnalyzer):

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        self.gun_name_mapping: dict = {}
        self.ammo_name_mapping: dict = {}

    def initialize_mapping(self) -> None:
        self.gun_name_mapping = self.load_json_mapping("guns_names.json")
        raw = self.load_json_mapping("ammo_names.json")
        self.ammo_name_mapping = {k.upper(): v for k, v in raw.items()}
        self._log("GunAnalyzer 映射表已同步")

    def get_dispersion_formula(self, weapon_data: dict) -> str:
        ir = weapon_data.get('idealRadius')
        mr = weapon_data.get('minRadius')
        id_dist = weapon_data.get('idealDistance')
        if ir is None or mr is None or id_dist is None:
            return "数据缺失"
        slope = (ir - mr) / (id_dist / 1000)
        intercept = mr * 30
        return f"{round(slope, 2)}R + {round(intercept, 2)}"

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        gun_name = raw_data.get("name", "Unknown_Gun")
        gun_id = raw_data.get("id", "N/A")
        gun_index = raw_data.get("index", "N/A")
        display_name = self.gun_name_mapping.get(gun_name.upper(), gun_name)

        t.writeln("=" * 45)
        t.writeln(f"  武器名称: {display_name}")
        t.writeln(f"  编号: {gun_index}")
        t.writeln(f"  ID: {gun_id}")
        t.writeln("=" * 45)
        t.writeln()

        species_raw = raw_data.get("typeinfo", {}).get("species", "Unknown")
        species_display = NM.WEAPON_SPECIES_MAP.get(species_raw, species_raw)
        t.writeln(f"  类型: {species_display}")

        # 通用属性
        num_barrels = raw_data.get("numBarrels", 1)
        t.writeln(f"  联装数: {num_barrels}")
        if "barrelDiameter" in raw_data:
            bd = raw_data["barrelDiameter"] * 1000
            t.writeln(f"  火炮口径: {bd:.1f} mm")
        if "shotDelay" in raw_data:
            t.writeln(f"  装填时间: {raw_data['shotDelay']:.1f} s")
        if "rotationSpeed" in raw_data:
            rs = raw_data["rotationSpeed"]
            if isinstance(rs, list) and len(rs) >= 2:
                t.writeln(f"  水平回转速度: {rs[0]} °/s")
                t.writeln(f"  垂直回转速度: {rs[1]} °/s")

        # 弹药列表
        ammo_list = raw_data.get("ammoList", [])
        if ammo_list:
            t.writeln(f"  可用弹药:")
            for ammo_id in ammo_list:
                aname = self.ammo_name_mapping.get(ammo_id.upper(), ammo_id)
                t.writeln(f"    - {aname} ({ammo_id})")

        # 模块血量
        hl_key = next((k for k in raw_data if k.startswith("HitLocation")), None)
        if hl_key:
            hl = raw_data[hl_key]
            t.writeln(f"  模块血量: {hl.get('maxHP', 0):.0f}")
            t.writeln(f"  自动维修时间: {hl.get('autoRepairTime', 0)} s")

        # 鱼雷管属性
        if species_raw == "Torpedo":
            angles = raw_data.get("torpedoAngles", [])
            if angles:
                t.writeln(f"  鱼雷散布界: {angles}°")
                t.writeln(f"  鱼雷最短射击间隔: {raw_data.get('timeBetweenShots', 0)} s")
            drum = raw_data.get("drumChargeTimeParams", [])
            if any(v != 0 for v in drum[:2]):
                t.writeln(f"  弹鼓基础装填时间: {drum[0]} s")
                t.writeln(f"  序列增量时间: {drum[1]} s")

        # 散布参数
        if "idealRadius" in raw_data:
            t.writeln(f"  默认横向散布公式: {self.get_dispersion_formula(raw_data)}")
            rz = raw_data.get("radiusOnZero", 0)
            rd = raw_data.get("radiusOnDelim", 0)
            rm = raw_data.get("radiusOnMax", 0)
            dl = raw_data.get("delim", 0)
            t.writeln(f"  默认纵向散步系数: {rz} ~ {rd}(R={dl * 100:.0f}%) ~ {rm}")

        t.writeln()
        t.writeln("-" * 45)

        return t.result(title=display_name, subtitle=f"编号: {gun_index}")
