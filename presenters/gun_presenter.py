"""
GunPresenter —— 从 gun_basic_info 表组装火炮显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class GunPresenter(BasePresenter):
    """火炮显示 Presenter"""

    def build(self, gun_id: str) -> dict | None:
        conn = self.conn
        gun = conn.execute(
            "SELECT * FROM gun_basic_info WHERE gun_id=?", (gun_id,)).fetchone()
        if not gun:
            return None

        items = [
            self.make_item(f"  武器名称: {gun['gun_name_zh'] or gun_id}", "", 0),
            self.make_item(f"  编号: {gun['gun_index'] or gun_id}", "", 1),
        ]
        for col, disp, unit in [
            ("weapon_species", "类型", ""), ("num_barrels", "联装数", ""),
            ("caliber", "口径", "mm"), ("reload_time", "装填时间", "s"),
            ("rotation_speed_h", "水平回转速度", ""),
            ("rotation_speed_v", "垂直回转速度", ""),
            ("max_health", "模块血量", ""), ("auto_repair_time", "自动维修时间", "s"),
        ]:
            val = gun[col]
            if val is not None:
                u = f" {unit}" if unit else ""
                items.append(self.make_item(f"  {disp}: {val}{u}", "", len(items)))

        return {
            "title": gun['gun_name_zh'] or gun_id,
            "subtitle": f"ID: {gun_id}",
            "sections": [self.make_section("详情", items)],
        }
