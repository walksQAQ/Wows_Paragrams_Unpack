"""
PlanePresenter —— 从 plane_basic_info 表组装飞机显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class PlanePresenter(BasePresenter):
    """飞机显示 Presenter"""

    def build(self, plane_id: str) -> dict | None:
        conn = self.conn
        pl = conn.execute(
            "SELECT * FROM plane_basic_info WHERE plane_id=?", (plane_id,)).fetchone()
        if not pl:
            return None

        items = [
            self.make_item(f"  飞机型号: {pl['plane_name_zh'] or plane_id}", "", 0),
        ]
        for col, disp in [
            ("tier", "等级"), ("aircraft_class", "机种"),
            ("cruise_speed", "巡航航速"), ("max_health", "单机生命值"),
            ("restore_time", "整备时间"), ("deck_capacity", "甲板容量"),
            ("squadron_size", "中队规模"), ("attack_size", "攻击组规模"),
            ("attack_count", "攻击组数量"), ("preparation_time", "准备时间"),
            ("aiming_time", "瞄准时间"),
        ]:
            val = pl[col]
            if val is not None:
                u = " knot" if col == "cruise_speed" else "s" if col in (
                    "restore_time", "preparation_time", "aiming_time") else ""
                items.append(self.make_item(f"  {disp}: {val}{u}", "", len(items)))

        # 武器挂载
        arm = pl['armament_name_zh'] or pl['armament_name']
        if arm:
            items.append(self.make_item(f"  武器挂载: {arm}", "", len(items)))

        # 消耗品槽位
        slots = conn.execute(
            "SELECT * FROM plane_ability_slots WHERE plane_id=? ORDER BY slot_index",
            (plane_id,)).fetchall()
        if slots:
            items.append(self.make_item("  消耗品:", "", len(items)))
            for s in slots:
                ability_name = self.resolve_name("consumable", s['ability_id'])
                limit_str = f" x{s['ability_limit']}" if s['ability_limit'] else ""
                items.append(self.make_item(
                    f"    ({s['slot_index']}) {ability_name}{limit_str}", "", len(items)))

        return {
            "title": pl['plane_name_zh'] or plane_id,
            "subtitle": f"ID: {plane_id}",
            "sections": [self.make_section("详情", items)],
        }
