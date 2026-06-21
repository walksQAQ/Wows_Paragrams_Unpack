"""
ConsumablePresenter —— 从 consumable_basic_info 表组装消耗品显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class ConsumablePresenter(BasePresenter):
    """消耗品显示 Presenter"""

    def build(self, cid: str) -> dict | None:
        conn = self.conn
        c = conn.execute(
            "SELECT * FROM consumable_basic_info WHERE consumable_id=?",
            (cid,)).fetchone()
        if not c:
            return None

        items = [self.make_item(f"  名称: {c['display_name'] or cid}", "", 0)]
        for col, disp in [
            ("consumable_type", "类型"), ("num_consumables", "数量"),
            ("work_time", "作用时间"), ("preparation_time", "准备时间"),
            ("reload_time", "装填时间"),
        ]:
            val = c[col]
            if val is not None:
                u = "s" if col.endswith("_time") else ""
                items.append(self.make_item(f"  {disp}: {val}{' '+u if u else ''}", "", len(items)))

        # 特殊属性
        if c['is_auto_consumable']:
            items.append(self.make_item("  自动使用: 是", "", len(items)))
        if c['is_interceptor']:
            items.append(self.make_item("  拦截机: 是", "", len(items)))
        if c['regen_hp_speed']:
            items.append(self.make_item(f"  每秒回复: {c['regen_hp_speed']} HP", "", len(items)))
        if c['area_dmg_multiplier']:
            items.append(self.make_item(f"  范围伤害倍率: {c['area_dmg_multiplier']}", "", len(items)))
        if c['bubble_dmg_multiplier']:
            items.append(self.make_item(f"  黑云伤害倍率: {c['bubble_dmg_multiplier']}", "", len(items)))
        if c['fighter_name']:
            items.append(self.make_item(f"  战斗机型号: {c['fighter_name']}", "", len(items)))
        if c['fighter_num']:
            items.append(self.make_item(f"  战斗机数量: {c['fighter_num']}", "", len(items)))

        return {
            "title": c['display_name'] or cid,
            "subtitle": f"ID: {cid}",
            "sections": [self.make_section("详情", items)],
        }
