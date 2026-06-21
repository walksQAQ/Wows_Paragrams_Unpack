"""
CrewPresenter —— 从 crew 表组装舰长显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class CrewPresenter(BasePresenter):
    """舰长显示 Presenter"""

    def build(self, crew_id: str) -> dict | None:
        conn = self.conn
        cr = conn.execute(
            "SELECT * FROM crew_basic_info WHERE crew_id=?", (crew_id,)).fetchone()
        if not cr:
            return None

        items = [self.make_item(f"  舰长名称: {cr['crew_name'] or crew_id}", "", 0)]
        if cr['nation_zh']:
            items.append(self.make_item(f"  所属国籍: {cr['nation_zh']}", "", len(items)))
        for col, disp in [
            ("is_unique", "传奇舰长"), ("is_elite", "精英舰长"),
            ("is_person", "历史人物"), ("is_animated", "动态立绘"),
            ("is_retrainable", "可重新训练"),
        ]:
            val = cr[col]
            if val:
                items.append(self.make_item(f"  {disp}: 是", "", len(items)))

        # 特殊技能
        skills = conn.execute(
            "SELECT * FROM crew_unique_skills WHERE crew_id=?", (crew_id,)).fetchall()
        if skills:
            items.append(self.make_item("  [特殊技能]", "", len(items)))
            for sk in skills:
                items.append(self.make_item(f"    {sk['skill_key']}", "", len(items)))
                if sk['trigger_type']:
                    items.append(self.make_item(f"      触发类型: {sk['trigger_type']}", "", len(items)))
                if sk['max_trigger_num']:
                    items.append(self.make_item(f"      最大触发: {sk['max_trigger_num']}", "", len(items)))

        return {
            "title": cr['crew_name'] or crew_id,
            "subtitle": f"ID: {crew_id}",
            "sections": [self.make_section("详情", items)],
        }
