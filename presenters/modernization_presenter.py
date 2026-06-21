"""
ModernizationPresenter —— 从 modernization 表组装升级品显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class ModernizationPresenter(BasePresenter):
    """升级品显示 Presenter"""

    def build(self, mod_id: str) -> dict | None:
        conn = self.conn
        m = conn.execute(
            "SELECT * FROM modernization_basic_info WHERE mod_id=?", (mod_id,)).fetchone()
        if not m:
            return None

        items = [self.make_item(f"  名称: {m['mod_name_zh'] or mod_id}", "", 0)]
        for col, disp in [("cost_cr", "价格"), ("slot", "槽位")]:
            val = m[col]
            if val is not None:
                items.append(self.make_item(f"  {disp}: {val}", "", len(items)))

        # 加成效果
        mods = conn.execute(
            "SELECT * FROM modernization_modifiers WHERE mod_id=?", (mod_id,)).fetchall()
        if mods:
            items.append(self.make_item("  加成效果:", "", len(items)))
            for md in mods:
                items.append(self.make_item(
                    f"    {md['modifier_name_zh'] or md['modifier_key']}: "
                    f"{md['formatted_value'] or md['modifier_value']}",
                    "", len(items)))

        return {
            "title": m['mod_name_zh'] or mod_id,
            "subtitle": f"ID: {mod_id}",
            "sections": [self.make_section("详情", items)],
        }
