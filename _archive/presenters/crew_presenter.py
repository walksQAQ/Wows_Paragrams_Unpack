"""
CrewPresenter —— 从 crew 表组装舰长显示数据。

支持多 section 展示：基本信息 + 每个特殊天赋独立一页。
天赋效果渲染逻辑移植自 _archive/analyzers/crew_analyzer.py。
"""

from __future__ import annotations

import json

from presenters.base_presenter import BasePresenter
from models.name_mapping import Mapping as NM

# 天赋 key → 显示名映射
SKILL_LABEL_MAP: dict[str, str] = {
    "UniqueSkillTriggerAchievement1": "成就触发",
    "UniqueSkillTriggerAchievement2": "成就触发Ⅱ",
    "UniqueSkillTriggerDamage1": "受击触发",
    "UniqueSkillTriggerDeadAllies1": "友军阵亡",
    "UniqueSkillTriggerEnemyVehiclesDead1": "击沉触发",
    "UniqueSkillTriggerHealth1": "血量触发",
    "UniqueSkillTriggerRageMode1": "指令触发",
    "UniqueSkillTriggerRibbons1": "勋带触发",
    "UniqueSkillTriggerRibbons2": "勋带触发Ⅱ",
    "UniqueSkillTriggerRibbons3": "勋带触发Ⅲ",
    "UniqueSkillTriggerRibbons4": "勋带触发Ⅳ",
}


class CrewPresenter(BasePresenter):
    """舰长显示 Presenter"""

    def build(self, crew_id: str, version_code: str = "") -> dict | None:
        conn = self.conn
        vc = self._ensure_version(version_code)
        cr = conn.execute(
            "SELECT * FROM crew_basic_info WHERE version_code=? AND crew_id=?", (vc, crew_id)).fetchone()
        if not cr:
            return None

        sections = []

        # ── 基本信息 section ──
        # 通过 name_mappings 查询舰长名，无映射则用 person_name
        crew_name = (self.resolve_name_by_id(cr['display_name_id'], 'crew', crew_id)
                     or cr['person_name'] or crew_id)
        info_items = [self.make_item(f"  舰长名称: {crew_name}", "", 0)]
        if cr['nation']:
            info_items.append(self.make_item(f"  所属国籍: {cr['nation']}", "", len(info_items)))
        for col, disp in [
            ("is_unique", "传奇舰长"), ("is_elite", "精英舰长"),
            ("is_person", "独特舰长"), ("is_animated", "动态立绘"),
            ("is_retrainable", "可重新训练"),
        ]:
            if cr[col]:
                info_items.append(self.make_item(f"  {disp}: 是", "", len(info_items)))
        sections.append(self.make_section("基本信息", info_items))

        # ── 特殊天赋 section（每个天赋独立一页）──
        skills = conn.execute(
            "SELECT * FROM crew_unique_skills WHERE version_code=? AND crew_id=? ORDER BY skill_key",
            (vc, crew_id)).fetchall()

        for sk in skills:
            skill_items = []
            sk_key = sk['skill_key']
            skill_items.append(self.make_item(f"  {sk_key}", "", len(skill_items)))

            # 触发类型
            ttype = sk['trigger_type']
            if ttype:
                ttype_zh = NM.TRIGGER_TYPE_MAP.get(ttype, ttype)
                skill_items.append(self.make_item(f"  触发方式: {ttype_zh}", "", len(skill_items)))

            if sk['max_trigger_num']:
                skill_items.append(self.make_item(f"  最大触发次数: {sk['max_trigger_num']}", "", len(skill_items)))

            ach = sk['trigger_achievement']
            if ach:
                skill_items.append(self.make_item(f"  触发成就: {ach}", "", len(skill_items)))

            dmg_num = sk['trigger_damage_num']
            dmg_type = sk['trigger_damage_type']
            if dmg_num:
                dmg_type_zh = NM.DAMAGE_TYPE_MAP.get(str(dmg_type), str(dmg_type) if dmg_type else "")
                label = f"  触发伤害: {dmg_num}"
                if dmg_type_zh:
                    label += f" ({dmg_type_zh})"
                skill_items.append(self.make_item(label, "", len(skill_items)))

            if sk['damage_percent_threshold']:
                pct = sk['damage_percent_threshold']
                skill_items.append(self.make_item(f"  血量阈值: {pct * 100:.0f}%", "", len(skill_items)))

            ribbon_num = sk['trigger_ribbons_num']
            if ribbon_num:
                skill_items.append(self.make_item(f"  需勋带数: {ribbon_num}", "", len(skill_items)))

            rib_types = sk['trigger_ribbon_types']
            if rib_types and rib_types != "[]":
                try:
                    types_list = json.loads(rib_types)
                    names = [NM.RIBBON_MAP_CREW.get(str(t), str(t)) for t in types_list]
                    skill_items.append(self.make_item(f"  勋带类型: {', '.join(names)}", "", len(skill_items)))
                except Exception:
                    skill_items.append(self.make_item(f"  勋带类型: {rib_types}", "", len(skill_items)))

            ships = sk['trigger_allowed_ships']
            if ships and ships != "[]":
                ship_list = ships.strip("[]").replace("'", "").split(", ")
                ship_names = [NM.SHIP_CLASS_MAP.get(s, s) for s in ship_list if s]
                ship_str = ", ".join(ship_names)
                if ship_str:
                    skill_items.append(self.make_item(f"  适用舰船: {ship_str}", "", len(skill_items)))

            # ── 天赋效果（从 effects_json 读取）──
            effects_json = sk['effects_json'] or '{}'
            try:
                effects = json.loads(effects_json)
            except (json.JSONDecodeError, TypeError):
                effects = {}
            if effects:
                skill_items.append(self.make_item("  [效果]", "", len(skill_items)))
                self._render_effects(skill_items, effects)

            label = SKILL_LABEL_MAP.get(sk_key, sk_key)
            sections.append(self.make_section(label, skill_items))

        return {
            "title": crew_name,
            "subtitle": f"ID: {crew_id}",
            "sections": sections,
        }

    # ── 效果渲染（移植自 archived crew_analyzer.py）──

    def _render_effects(self, items: list[dict], effects: dict, indent: int = 2) -> None:
        """递归渲染效果数据"""
        percent_talent = bool(effects.get("percentTalent", False))
        level_dependent = bool(effects.get("levelDependent", False))
        prefix = "  " * indent
        for key, value in effects.items():
            if key in {"levelDependent", "percentTalent", "uniqueType"}:
                continue
            label = NM.MODIFIER_MAP.get(key, NM.DETAIL_MAP.get(key, key))

            if isinstance(value, dict):
                items.append(self.make_item(f"{prefix}{label}:", "", len(items)))
                # 从嵌套 dict 中提取 levelDependent / percentTalent（覆盖外层默认值）
                sub_ld = bool(value.get("levelDependent", level_dependent))
                sub_pt = bool(value.get("percentTalent", percent_talent))
                for sk, sv in value.items():
                    if sk in {"uniqueType", "levelDependent", "percentTalent"}:
                        continue
                    # 子值仍是 dict 时递归渲染
                    if isinstance(sv, dict):
                        child_label = NM.MODIFIER_MAP.get(sk, NM.DETAIL_MAP.get(sk, sk))
                        items.append(self.make_item(f"{prefix}  {child_label}:", "", len(items)))
                        for sub_k, sub_v in sv.items():
                            sub_label = NM.SHIP_CLASS_MAP.get(sub_k, NM.MODIFIER_MAP.get(sub_k, sub_k))
                            fmt = self._format_value(sk, sub_v, sub_pt, sub_ld)
                            if fmt:
                                items.append(self.make_item(f"{prefix}    {sub_label}: {fmt}", "", len(items)))
                    else:
                        child_label = NM.SHIP_CLASS_MAP.get(sk, NM.MODIFIER_MAP.get(sk, sk))
                        fmt = self._format_value(sk, sv, sub_pt, sub_ld)
                        if fmt:
                            items.append(self.make_item(f"{prefix}  {child_label}: {fmt}", "", len(items)))
            elif isinstance(value, list):
                items.append(self.make_item(f"{prefix}{label}:", "", len(items)))
                for item in value[:6]:
                    if isinstance(item, dict):
                        self._render_effects(items, item, indent + 1)
                    else:
                        fmt = self._format_value(key, item, percent_talent, level_dependent)
                        if fmt:
                            items.append(self.make_item(f"{prefix}  - {fmt}", "", len(items)))
            else:
                fmt = self._format_value(key, value, percent_talent, level_dependent)
                if fmt:
                    items.append(self.make_item(f"{prefix}{label}: {fmt}", "", len(items)))

    def _format_value(self, key: str, value, percent_talent=False, level_dependent=False) -> str | None:
        """格式化数值显示（移植自 archived CrewAnalyzer._format_value）"""
        # 特殊处理映射表
        special_map = {
            "visibilityDistCoeff": self._pct_range,
            "planeVisibilityFactor": self._pct_range,
            "GMShotDelay": self._pct_range,
            "GSShotDelay": self._pct_range,
            "GTShotDelay": self._pct_range,
            "planeSpawnTime": self._pct_range,
            "planeSpeed": self._pct_range,
            "speedCoef": self._pct_range,
            "GMMaxDist": self._pct_range,
            "ConsumablesWorkTime": self._pct_range,
            "GMRotationSpeed": self._pct_range,
            "SGRudderTime": self._pct_range,
            "shootShift": self._pct_range,
            "ConsumableReloadTime": self._pct_range,
            "GMIdealRadius": self._pct_range,
            "planeSpreadMultiplier": self._pct_range,
            "GMAPDamageCoeff": self._pct_range,
            "AAAuraDamage": self._pct_range,
            "torpedoReloaderReloadCoeff": self._pct_range,
            "torpedoSpeedMultiplier": self._pct_range,
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
            result = handler(value)
            # 跳过零值结果（0 / 0.00% / +0.00%）
            if result is None:
                return None
            if isinstance(result, str):
                stripped = result.replace("+", "").replace("-", "").strip()
                if stripped in ("0", "0.00%", "0.0"):
                    return None
            return result

        if key in {"levelDependent", "percentTalent"}:
            return None
        return str(value)

    @staticmethod
    def _pct_range(value) -> str | None:
        """百分比范围显示"""
        if value is None:
            return None
        if value < 1:
            return f"-{(1 - value) * 100:.2f}%"
        elif value > 1:
            return f"+{(value - 1) * 100:.2f}%"
        return None

