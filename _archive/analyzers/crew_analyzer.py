"""
CrewAnalyzer —— 舰长/特殊技能数据分析器。
"""

from __future__ import annotations

from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class CrewAnalyzer(BaseAnalyzer):

    META_KEYS = {
        "triggerType", "maxTriggerNum", "sortIndex", "damagePercentThreshold",
        "triggerAllowedShips", "triggerAllowedShipTypes", "triggerRibbonsNum",
        "triggerIsSubRibbons", "triggerJoinRibbons", "triggerRibbonsTypes",
    }

    def initialize_mapping(self) -> None:
        self._log("CrewAnalyzer 映射表已同步（无外部映射文件）")

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        t.writeln(f"  舰长名称: {raw_data.get('name', 'Unknown_Crew')}")
        t.writeln(f"  舰长编号: {raw_data.get('index', 'Unknown_Index')}")
        t.writeln(f"  所属国籍: {raw_data.get('typeinfo', {}).get('nation', 'Unknown')}")
        t.writeln()

        # 舰长特性
        pers = raw_data.get("CrewPersonality", {})
        t.writeln(f"【舰长特性】")
        t.writeln(f"  传奇舰长: {'是' if pers.get('isUnique') else '否'}")
        t.writeln(f"  动态舰长: {'是' if pers.get('isAnimated') else '否'}")
        t.writeln(f"  精英舰长: {'是' if pers.get('isElite') else '否'}")
        t.writeln(f"  历史人物: {'是' if pers.get('isPerson') else '否'}")
        t.writeln(f"  可重训: {'是' if pers.get('isRetrainable') else '否'}")
        t.writeln()

        # 特殊技能
        unique_skills = raw_data.get("UniqueSkills", {})
        if not unique_skills:
            return t.result(title=raw_data.get('name', 'Unknown'), subtitle=f"编号: {raw_data.get('index', 'N/A')}")

        t.writeln(f"【特殊技能】")
        for sk_key, sk_val in unique_skills.items():
            trigger_type = sk_val.get("triggerType")
            tt_name = NM.TRIGGER_TYPE_MAP.get(trigger_type, trigger_type) if trigger_type else "无"
            t.writeln(f"  {sk_key}: 激活方式 = {tt_name}")

            if "maxTriggerNum" in sk_val:
                t.writeln(f"    最大激活次数: {sk_val['maxTriggerNum']}")
            if "triggerAchievement" in sk_val:
                ach = NM.ACHIEVEMENT_MAP.get(str(sk_val["triggerAchievement"]), sk_val["triggerAchievement"])
                t.writeln(f"    所需成就: {ach}")
            if "triggerDamageNum" in sk_val:
                raw_dt = sk_val.get("triggerDamageType", "")
                dt = NM.DAMAGE_TYPE_MAP.get(str(raw_dt), raw_dt) if raw_dt else ""
                t.writeln(f"    所需伤害: {sk_val['triggerDamageNum']} {dt}")
            if "damagePercentThreshold" in sk_val:
                try:
                    t.writeln(f"    对敌舰所造成的伤害: {float(sk_val['damagePercentThreshold']) * 100:.0f}%")
                except Exception:
                    pass
            if "triggerRibbonsNum" in sk_val:
                t.writeln(f"    所需勋带数量: {sk_val['triggerRibbonsNum']}")
            if "triggerRibbonsTypes" in sk_val:
                raw = sk_val["triggerRibbonsTypes"]
                ribbons = raw if isinstance(raw, (list, tuple)) else [raw]
                names = [NM.RIBBON_MAP_CREW.get(str(r), str(r)) for r in ribbons]
                t.writeln(f"    所需勋带类型: {', '.join(names)}")

            allowed = sk_val.get("triggerAllowedShips") or sk_val.get("triggerAllowedShipTypes")
            if allowed:
                t.writeln(f"    允许触发的舰种: {', '.join(NM.SHIP_CLASS_MAP.get(s, s) for s in allowed)}")

            # 效果
            for effect_name, effect_body in sk_val.items():
                if effect_name in self.META_KEYS or not isinstance(effect_body, dict):
                    continue
                t.writeln(f"    [{effect_name}]")
                self._render_effect(t, effect_body, 2)

            t.writeln()

        return t.result(title=raw_data.get('name', 'Unknown'), subtitle=f"编号: {raw_data.get('index', 'N/A')}")

    def _render_effect(self, t: TextCollector, effect: dict, indent: int = 2) -> None:
        from models.name_mapping import Mapping as NM
        prefix = "  " * indent

        percent_talent = bool(effect.get("percentTalent", False))
        level_dependent = bool(effect.get("levelDependent", False))

        for key, value in effect.items():
            if key in {"levelDependent", "percentTalent", "uniqueType"}:
                continue
            label = NM.MODIFIER_MAP.get(key, NM.DETAIL_MAP.get(key, key))

            if isinstance(value, dict):
                t.writeln(f"{prefix}{label}:")
                for sk, sv in value.items():
                    if sk in {"uniqueType"}:
                        continue
                    child_label = NM.SHIP_CLASS_MAP.get(sk, NM.MODIFIER_MAP.get(sk, sk))
                    fmt = self._format_value(key, sv, percent_talent, level_dependent)
                    if fmt:
                        t.writeln(f"{prefix}  {child_label}: {fmt}")
            elif isinstance(value, list):
                t.writeln(f"{prefix}{label}:")
                for item in value[:6]:
                    if isinstance(item, dict):
                        self._render_effect(t, item, indent + 1)
                    else:
                        fmt = self._format_value(key, item, percent_talent, level_dependent)
                        if fmt:
                            t.writeln(f"{prefix}  - {fmt}")
            else:
                fmt = self._format_value(key, value, percent_talent, level_dependent)
                if fmt:
                    t.writeln(f"{prefix}{label}: {fmt}")

    def _format_value(self, key: str, value, percent_talent=False, level_dependent=False) -> str | None:
        """格式化数值显示（移植自旧 CrewDataAnalyzer._format_value）"""
        # 特殊处理
        special_map = {
            "visibilityDistCoeff": lambda v: self._pct_range(v),
            "planeVisibilityFactor": lambda v: self._pct_range(v),
            "GMShotDelay": lambda v: self._pct_range(v),
            "GSShotDelay": lambda v: self._pct_range(v),
            "GTShotDelay": lambda v: self._pct_range(v),
            "planeSpawnTime": lambda v: self._pct_range(v),
            "planeSpeed": lambda v: self._pct_range(v),
            "speedCoef": lambda v: self._pct_range(v),
            "GMMaxDist": lambda v: self._pct_range(v),
            "ConsumablesWorkTime": lambda v: self._pct_range(v),
            "GMRotationSpeed": lambda v: self._pct_range(v),
            "SGRudderTime": lambda v: self._pct_range(v),
            "shootShift": lambda v: self._pct_range(v),
            "ConsumableReloadTime": lambda v: self._pct_range(v),
            "GMIdealRadius": lambda v: self._pct_range(v),
            "planeSpreadMultiplier": lambda v: self._pct_range(v),
            "GMAPDamageCoeff": lambda v: self._pct_range(v),
            "AAAuraDamage": lambda v: self._pct_range(v),
            "torpedoReloaderReloadCoeff": lambda v: self._pct_range(v),
            "torpedoSpeedMultiplier": lambda v: self._pct_range(v),
            "additionalConsumables": lambda v: f"+{v}" if v > 0 else None,
            "planeAdditionalConsumables": lambda v: f"+{v}" if v > 0 else None,
            "torpedoReloaderAdditionalConsumables": lambda v: f"+{v}",
            "burnChanceBonus": lambda v: f"{'+' if v > 0 else ''}{v * 100:.2f}%",
            "burnChanceFactorBig": lambda v: f"{'+' if v > 0 else ''}{v * 100:.2f}%",
            "floodChanceFactorTorpedo": lambda v: f"{'+' if v > 1 else ''}{(v - 1) * 100:.2f}%" if v != 1 else None,
            "regenerationHPSpeed": lambda v: f"+{v}" if not percent_talent else f"+{v * 100:.2f}%",
            "workTime": lambda v: f"{v}s" if not level_dependent else "生效时间取决于舰船等级",
        }

        handler = special_map.get(key)
        if handler:
            return handler(value)

        if key in {"levelDependent", "percentTalent"}:
            return None
        return str(value)

    @staticmethod
    def _pct_range(value) -> str | None:
        if value < 1:
            return f"-{(1 - value) * 100:.2f}%"
        elif value > 1:
            return f"+{(value - 1) * 100:.2f}%"
        return None
