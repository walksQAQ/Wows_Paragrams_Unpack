"""
CrewPresenter —— 从 crew 表组装舰长显示数据。

支持多 section 展示：基本信息 + 每个特殊天赋独立一页。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter
from models.name_mapping import Mapping as NM


class CrewPresenter(BasePresenter):
    """舰长显示 Presenter"""

    def build(self, crew_id: str) -> dict | None:
        conn = self.conn
        cr = conn.execute(
            "SELECT * FROM crew_basic_info WHERE crew_id=?", (crew_id,)).fetchone()
        if not cr:
            return None

        sections = []

        # ── 基本信息 section ──
        info_items = [self.make_item(f"  舰长名称: {cr['crew_name'] or crew_id}", "", 0)]
        if cr['nation_zh']:
            info_items.append(self.make_item(f"  所属国籍: {cr['nation_zh']}", "", len(info_items)))
        for col, disp in [
            ("is_unique", "传奇舰长"), ("is_elite", "精英舰长"),
            ("is_person", "历史人物"), ("is_animated", "动态立绘"),
            ("is_retrainable", "可重新训练"),
        ]:
            if cr[col]:
                info_items.append(self.make_item(f"  {disp}: 是", "", len(info_items)))
        sections.append(self.make_section("基本信息", info_items))

        # ── 特殊天赋 section（每个天赋独立一页）──
        skills = conn.execute(
            "SELECT * FROM crew_unique_skills WHERE crew_id=? ORDER BY skill_key",
            (crew_id,)).fetchall()

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

            # 成就触发
            ach = sk['trigger_achievement']
            if ach:
                ach_zh = NM.ACHIEVEMENT_MAP.get(ach, ach)
                skill_items.append(self.make_item(f"  触发成就: {ach_zh}", "", len(skill_items)))

            # 伤害触发
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

            # 勋带触发
            ribbon_num = sk['trigger_ribbons_num']
            if ribbon_num:
                skill_items.append(self.make_item(f"  需勋带数: {ribbon_num}", "", len(skill_items)))

            rib_types = sk['trigger_ribbon_types']
            if rib_types and rib_types != "[]":
                try:
                    import json
                    types_list = json.loads(rib_types)
                    names = [NM.RIBBON_MAP_CREW.get(str(t), str(t)) for t in types_list]
                    skill_items.append(self.make_item(f"  勋带类型: {', '.join(names)}", "", len(skill_items)))
                except Exception:
                    skill_items.append(self.make_item(f"  勋带类型: {rib_types}", "", len(skill_items)))

            # 可用舰船
            ships = sk['trigger_allowed_ships']
            if ships and ships != "[]":
                ship_list = ships.strip("[]").replace("'", "").split(", ")
                ship_str = ", ".join(s for s in ship_list if s)
                if ship_str:
                    skill_items.append(self.make_item(f"  适用舰船: {ship_str}", "", len(skill_items)))

            label = f"天赋: {sk_key}"
            sections.append(self.make_section(label, skill_items))

        return {
            "title": cr['crew_name'] or crew_id,
            "subtitle": f"ID: {crew_id}",
            "sections": sections,
        }
