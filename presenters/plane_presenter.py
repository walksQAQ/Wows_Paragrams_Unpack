"""
PlanePresenter —— 从 plane_basic_info 表组装飞机显示数据。

参照 _archive/analyzers/plane_analyzer.py 的显示格式。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter, NM


class PlanePresenter(BasePresenter):
    """飞机显示 Presenter"""

    def build(self, plane_id: str) -> dict | None:
        conn = self.conn
        pl = conn.execute(
            "SELECT * FROM plane_basic_info WHERE plane_id=?", (plane_id,)).fetchone()
        if not pl:
            return None

        items = []
        o = 0

        # ── 基本信息 ──
        items.append(self.make_item(f"  飞机型号: {pl['plane_name_zh'] or plane_id}", "", o)); o += 1
        if pl['plane_index']:
            items.append(self.make_item(f"  编号: {pl['plane_index']}", "", o)); o += 1
        if pl['tier']:
            items.append(self.make_item(f"  等级: {pl['tier']}", "", o)); o += 1
        if pl['nation_zh']:
            items.append(self.make_item(f"  国籍: {pl['nation_zh']}", "", o)); o += 1
        if pl['aircraft_class']:
            items.append(self.make_item(f"  机种: {pl['aircraft_class']}", "", o)); o += 1

        # ── 飞行性能 ──
        items.append(self.make_item("  【飞行性能】", "", o)); o += 1
        cruise = pl['cruise_speed']
        max_s = pl['max_speed']
        min_s = pl['min_speed']
        if cruise:
            items.append(self.make_item(f"  巡航航速: {cruise}", "", o)); o += 1
        if max_s is not None:
            v = cruise * max_s if cruise else max_s
            items.append(self.make_item(f"  最大航速: {v:.0f}", "", o)); o += 1
        if min_s is not None:
            v = cruise * min_s if cruise else min_s
            items.append(self.make_item(f"  最小航速: {v:.0f}", "", o)); o += 1
        hp = pl['max_health']
        if hp:
            items.append(self.make_item(f"  单机生命值: {hp:.0f}", "", o)); o += 1
        sq_hp = pl['squadron_health']
        if sq_hp:
            items.append(self.make_item(f"  全中队血量: {int(sq_hp)}", "", o)); o += 1
        if pl['restore_time']:
            items.append(self.make_item(f"  整备时间: {pl['restore_time']}s / 架", "", o)); o += 1
        if pl['deck_capacity']:
            items.append(self.make_item(f"  甲板容量: {pl['deck_capacity']} 架", "", o)); o += 1

        # ── 编队与攻击 ──
        items.append(self.make_item("  【编队与攻击】", "", o)); o += 1
        if pl['squadron_size']:
            items.append(self.make_item(f"  中队编制: {pl['squadron_size']} 架", "", o)); o += 1
        asz = pl['attack_size']
        acnt = pl['attack_count']
        if asz and acnt:
            items.append(self.make_item(f"  攻击规模: {asz} 架 x {acnt} 轮", "", o)); o += 1
        elif asz:
            items.append(self.make_item(f"  攻击组规模: {asz} 架", "", o)); o += 1
        if pl['bomb_drop_delay']:
            items.append(self.make_item(f"  投弹延迟: {pl['bomb_drop_delay']}s", "", o)); o += 1
        prep = pl['preparation_time']
        aim = pl['aiming_time']
        if prep and aim:
            items.append(self.make_item(f"  准备/瞄准时间: {prep}s / {aim}s", "", o)); o += 1
        elif prep:
            items.append(self.make_item(f"  准备时间: {prep}s", "", o)); o += 1
        elif aim:
            items.append(self.make_item(f"  瞄准时间: {aim}s", "", o)); o += 1

        # ── 武器挂载 ──
        arm = pl['armament_name_zh'] or pl['armament_name']
        if arm:
            items.append(self.make_item(f"  武器挂载: {arm}", "", o)); o += 1

        # ── 消耗品槽位 ──
        slots = conn.execute(
            "SELECT * FROM plane_ability_slots WHERE plane_id=? ORDER BY slot_index",
            (plane_id,)).fetchall()
        if slots:
            items.append(self.make_item("  【机载消耗品】", "", o)); o += 1
            for s in slots:
                ability_name = self.resolve_name("consumable", s['ability_id'])
                limit_str = f" x{s['ability_limit']}" if s['ability_limit'] else ""
                items.append(self.make_item(
                    f"  插槽 {s['slot_index']}: {ability_name}{limit_str}", "", o)); o += 1

        return {
            "title": pl['plane_name_zh'] or plane_id,
            "subtitle": f"ID: {plane_id}",
            "sections": [self.make_section("详情", items)],
        }
