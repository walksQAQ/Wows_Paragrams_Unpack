"""
ProjectilePresenter —— 从 projectile_basic_info 表组装弹药/投射物显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class ProjectilePresenter(BasePresenter):
    """弹药/投射物显示 Presenter"""

    def build(self, proj_id: str) -> dict | None:
        conn = self.conn
        p = conn.execute(
            "SELECT * FROM projectile_basic_info WHERE projectile_id=?",
            (proj_id,)).fetchone()
        if not p:
            return None

        items = [
            self.make_item(f"  弹药名称: {p['ammo_name_zh'] or proj_id}", "", 0),
            self.make_item(f"  编号: {p['projectile_index'] or proj_id}", "", 1),
            self.make_item(f"  类型: {p['species'] or ''} / {p['ammo_type'] or ''}", "", 2),
            self.make_item(f"  标伤: {p['alpha_damage']}", "", 3),
        ]

        # 炮弹/炸弹属性
        for col, disp, unit in [
            ("bullet_mass", "弹重", "kg"), ("bullet_speed", "弹速", "m/s"),
            ("bullet_krupp", "穿甲系数", ""), ("alpha_piercing_he", "HE穿深", "mm"),
            ("burn_prob", "起火率", ""), ("explosion_radius", "爆炸半径", "m"),
            ("bullet_always_ricochet_at", "绝对跳弹角", "°"),
            ("bullet_ricochet_at", "跳弹角", "°"),
            ("bullet_detonator", "引信阈值", "mm"),
            ("bullet_detonator_threshold", "引信触发", "mm"),
            ("bullet_air_drag", "空气阻力", ""),
            ("bullet_diameter", "弹径", "mm"),
            ("bullet_cap_normalize_max", "转正角", "°"),
        ]:
            val = p[col]
            if val is not None:
                u = f" {unit}" if unit else ""
                if col == "burn_prob":
                    items.append(self.make_item(f"  {disp}: {val*100:.1f}%", "", len(items)))
                else:
                    items.append(self.make_item(f"  {disp}: {val}{u}", "", len(items)))

        # 鱼雷属性
        torp_type = p['torpedo_type']
        if torp_type:
            items.append(self.make_item(f"  鱼雷类型: {torp_type}", "", len(items)))
            items.append(self.make_item(
                f"  深水鱼雷: {'是' if p['is_deep_water'] else '否'}", "", len(items)))
            for col, disp, unit in [
                ("torpedo_max_dist", "最大航程", "km"),
                ("torpedo_speed", "航速", "knot"),
                ("torpedo_visibility", "被侦察范围", "km"),
                ("torpedo_arming_time", "引信解除时间", "s"),
                ("torpedo_uw_critical", "上浮/下潜临界", "m"),
            ]:
                val = p[col]
                if val is not None:
                    u = f" {unit}" if unit else ""
                    items.append(self.make_item(f"  {disp}: {val}{u}", "", len(items)))

        return {
            "title": p['ammo_name_zh'] or proj_id,
            "subtitle": f"ID: {proj_id}",
            "sections": [self.make_section("详情", items)],
        }
