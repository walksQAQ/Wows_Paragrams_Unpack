"""
ModernizationAnalyzer —— 升级品/插件数据分析器。
"""

from __future__ import annotations

from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class ModernizationAnalyzer(BaseAnalyzer):

    NO_PERCENTAGE_KEYS = {
        "planeExtraHangarSize", "AAAuraDamageBonus", "additionalConsumables",
        "planeAdditionalConsumables", "AAExtraBubbles",
        "smokeGeneratorAdditionalConsumables", "asNumPacksBonus",
        "speedBoostersAdditionalConsumables",
    }
    FACTOR_KEYS = {"AABubbleDamageBonus"}
    SECOND_KEYS = {"crashCrewWorkTimeBonus", "torpedoBomberAimingTime", "fighterAimingTime"}
    KILOMETER_KEYS = {"visionXRayMineDist", "visionXRayTorpedoDist"}
    SP_PERCENT_KEYS = {
        "engineBackwardForsageMaxSpeed", "engineBackwardForsagePower",
        "engineForwardForsageMaxSpeed", "engineForwardForsagePower",
        "hydrophoneWaveSpeedCoeff", "regeneratedHPPartCoef", "boostCoeffForsage",
    }

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        self.name_mapping: dict = {}
        self.ship_name_mapping: dict = {}

    def initialize_mapping(self) -> None:
        self.name_mapping = self.load_json_mapping("modernization_names.json")
        self.ship_name_mapping = self.load_json_mapping("ship_names.json")
        self._log("ModernizationAnalyzer 映射表已同步")

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        mod_index = raw_data.get("index", "Unknown")
        raw_name = raw_data.get("name", mod_index)
        mod_id = raw_data.get("id", "N/A")
        display_name = self.name_mapping.get(raw_name.upper(), raw_name)

        cost = raw_data.get("costCR", 0)
        slot = raw_data.get("slot", 0)
        slot_str = f"第 {slot + 1} 槽位" if slot != -1 else "已禁用升级品"

        t.writeln(f"  升级品名称: {display_name}")
        t.writeln(f"  编号: {mod_index}")
        t.writeln(f"  ID: {mod_id}")
        t.writeln(f"  价格: {cost:,} 银币")
        t.writeln(f"  安装槽位: {slot_str}")
        t.writeln()

        # 属性加成
        modifiers = raw_data.get("modifiers", {})
        if modifiers:
            t.writeln(f"【属性加成】")
            for key, value in modifiers.items():
                label = NM.MODIFIER_MAP.get(key, key)
                if isinstance(value, dict):
                    t.writeln(f"  {label}:")
                    for ship_type, factor in value.items():
                        short_name = NM.SHIP_CLASS_MAP.get(ship_type, ship_type)
                        if key in self.NO_PERCENTAGE_KEYS:
                            t.writeln(f"    {short_name}: {factor}")
                        else:
                            pct = round((factor - 1.0) * 100, 3)
                            sign = "+" if pct > 0 else ""
                            t.writeln(f"    {short_name}: {sign}{pct:g}%")
                elif isinstance(value, (float, int)):
                    if key in self.NO_PERCENTAGE_KEYS:
                        t.writeln(f"  {label}: {'+' if value > 0 else ''}{value}")
                    elif key in self.FACTOR_KEYS:
                        t.writeln(f"  {label}: {'+' if value > 0 else ''}{round(value * 7, 0):.0f}")
                    elif key in self.SECOND_KEYS:
                        t.writeln(f"  {label}: {'+' if value > 0 else ''}{value}s")
                    elif key in self.KILOMETER_KEYS:
                        t.writeln(f"  {label}: {value / 1000}km")
                    elif key in self.SP_PERCENT_KEYS:
                        pct = round(value * 100, 1)
                        if pct == int(pct):
                            pct = int(pct)
                        sign = "+" if pct > 0 else ""
                        t.writeln(f"  {label}: {sign}{pct}%")
                    else:
                        pct = round((value - 1.0) * 100, 3)
                        sign = "+" if pct > 0 else ""
                        t.writeln(f"  {label}: {sign}{pct:g}%")
                else:
                    t.writeln(f"  {label}: {value}")

        # 使用限制
        restrictions = [
            ("禁用舰船", self._ship_names(raw_data.get("excludes", []))),
            ("可用舰船", self._ship_names(raw_data.get("ships", []))),
            ("可用分类", [NM.SHIP_GROUP_MAP.get(g, g) for g in raw_data.get("group", [])]),
            ("可用国籍", [NM.NATION_MAP.get(n, n) for n in raw_data.get("nation", [])]),
            ("可用舰种", [NM.SHIP_CLASS_MAP.get(s, s) for s in raw_data.get("shiptype", [])]),
            ("可用等级", raw_data.get("shiplevel", [])),
        ]
        has_restriction = any(len(v) > 0 for _, v in restrictions)
        if has_restriction:
            t.writeln(f"【使用限制】")
            for label, items in restrictions:
                if items:
                    t.writeln(f"  {label}: {', '.join(map(str, items))}")

        t.writeln()
        t.writeln("-" * 45)

        return t.result(title=display_name, subtitle=f"编号: {mod_index}")

    def _ship_names(self, items: list) -> list[str]:
        if not items:
            return []
        result = []
        for raw_id in items:
            clean = str(raw_id).split('_')[0].upper()
            name = self.ship_name_mapping.get(clean) or self.ship_name_mapping.get(f"IDS_{clean}") or raw_id
            result.append(name)
        return result
