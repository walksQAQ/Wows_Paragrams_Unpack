"""
PlaneAnalyzer —— 飞机/舰载机数据分析器。
"""

from __future__ import annotations

from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class PlaneAnalyzer(BaseAnalyzer):

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        self.plane_name_mapping: dict = {}
        self.ability_name_map: dict = {}
        self.ammo_name_mapping: dict = {}

    def initialize_mapping(self) -> None:
        self.plane_name_mapping = self.load_json_mapping("plane_names.json")
        raw = self.load_json_mapping("consumable_names.json")
        self.ability_name_map = {k.upper(): v for k, v in raw.items()}
        raw_ammo = self.load_json_mapping("ammo_names.json")
        self.ammo_name_mapping = {k.upper(): v for k, v in raw_ammo.items()}
        self._log("PlaneAnalyzer 映射表已同步")

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        idx = raw_data.get("index", "Unknown")
        raw_name = raw_data.get("name", idx)
        display_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)

        typeinfo = raw_data.get("typeinfo", {})
        nation = typeinfo.get("nation", "Unknown")
        species = typeinfo.get("species", "Aircraft")
        species_name = NM.AIRCRAFT_CLASS_MAP.get(species, species)

        level = raw_data.get("level", 0)
        squad_size = raw_data.get("numPlanesInSquadron", 0)
        attack_size = raw_data.get("attackerSize", 0)
        hp = raw_data.get("maxHealth", 0)
        raw_speed = raw_data.get("speedMoveWithBomb", 0)
        knots = round(raw_speed * 5.25 / 15, 1)

        t.writeln("=" * 45)
        t.writeln(f"  飞机型号: {display_name}")
        t.writeln(f"  编号: {idx}")
        t.writeln(f"  等级: {level}")
        t.writeln(f"  国籍: {nation}")
        t.writeln(f"  机种: {species_name}")
        t.writeln("=" * 45)
        t.writeln()

        # 飞行性能
        t.writeln(f"【飞行性能】")
        t.writeln(f"  巡航航速: {knots} kts")
        t.writeln(f"  单机生命值: {hp}")
        t.writeln(f"  全中队血量: {int(hp * squad_size)}")

        hangar = raw_data.get("hangarSettings", {})
        if hangar:
            t.writeln(f"  整备时间: {hangar.get('timeToRestore', 0)}s / 架")
            t.writeln(f"  甲板容量: {hangar.get('maxValue', 0)} 架")

        # 编队与攻击
        t.writeln(f"【编队与攻击】")
        t.writeln(f"  中队编制: {squad_size} 架")
        t.writeln(f"  攻击规模: {attack_size} 架 x {raw_data.get('attackCount', 1)} 轮")
        t.writeln(f"  投弹延迟: {raw_data.get('bombingDropPointTime', 0)}s")
        t.writeln(f"  准备/瞄准时间: {raw_data.get('preparationTime', 0)}s / {raw_data.get('aimingTime', 0)}s")

        # 消耗品
        self._parse_abilities(t, raw_data.get("PlaneAbilities", {}))

        # 弹药
        bomb_id = raw_data.get("bombName", "")
        if bomb_id:
            bomb_name = self.ammo_name_mapping.get(bomb_id.upper(), bomb_id)
            t.writeln(f"  关联弹药: {bomb_name} ({bomb_id})")

        t.writeln()
        t.writeln("=" * 45)

        return t.result(title=display_name, subtitle=f"编号: {idx} | {species_name}")

    def _parse_abilities(self, t: TextCollector, abilities_dict: dict) -> None:
        if not isinstance(abilities_dict, dict) or not abilities_dict:
            return
        t.writeln(f"【机载消耗品】")
        slots = [k for k in abilities_dict if "AbilitySlot" in k]
        for slot_key in sorted(slots, key=lambda x: int(''.join(filter(str.isdigit, x)) or 0)):
            slot_data = abilities_dict[slot_key]
            if not isinstance(slot_data, dict):
                continue
            abils = slot_data.get("abils", [])
            for item in abils:
                if isinstance(item, list) and len(item) > 0:
                    abil_id = item[0]
                    limit = item[1] if len(item) > 1 else "Unknown"
                    name = self.ability_name_map.get(abil_id.upper(), abil_id)
                    slot_num = slot_data.get('slot', 0) + 1
                    t.writeln(f"  插槽 {slot_num}: {name} ({limit})")
