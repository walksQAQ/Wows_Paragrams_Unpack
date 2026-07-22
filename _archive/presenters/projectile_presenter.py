"""
ProjectilePresenter —— 从 projectile_basic_info 表组装弹药/投射物显示数据。

参照 _archive/analyzers/projectile_analyzer.py 的显示逻辑，
按 species（Artillery/Bomb/Rocket/Torpedo/DepthCharge/Laser/Wave）分类型显示。
"""

from __future__ import annotations

import json

from presenters.base_presenter import BasePresenter, NM


class ProjectilePresenter(BasePresenter):
    """弹药/投射物显示 Presenter"""

    def build(self, proj_id: str, version_code: str = "") -> dict | None:
        conn = self.conn
        vc = self._ensure_version(version_code)
        p = conn.execute(
            "SELECT * FROM projectile_basic_info WHERE version_code=? AND projectile_id=?",
            (vc, proj_id)).fetchone()
        if not p:
            return None

        species = (p['species'] or '').strip()
        ammo_type = (p['ammo_type'] or '').upper()
        display_type = NM.PROJECTILE_TYPE_MAP.get(species, species)

        items = [
            self.make_item(f"  弹药ID: {proj_id}", "", 0),
            self.make_item(f"  编号: {p['projectile_index'] or proj_id}", "", 1),
            self.make_item(f"  类型: {display_type} / {ammo_type}", "", 2),
        ]

        extra = {}
        try:
            extra = json.loads(p['extra_json'] or '{}')
        except (json.JSONDecodeError, TypeError):
            pass

        # ── 标伤（各类型计算方式不同）────────────────────
        if species == "Torpedo":
            items.append(self.make_item(f"  标伤: {((p['alpha_damage'] or 0) * 0.33):.0f}", "", len(items)))
        else:
            items.append(self.make_item(f"  标伤: {p['alpha_damage'] or 0:.0f}", "", len(items)))

        # ── 火箭弹 & 炸弹（共通属性多）──────────────────
        if species in ("Rocket", "Bomb"):
            if p['bullet_mass']:
                display_mass = "火箭弹质量" if species == "Rocket" else "炸弹质量"
                items.append(self.make_item(f"  {display_mass}: {p['bullet_mass']:.0f} kg", "", len(items)))
            if p['bullet_speed']:
                display_speed = "火箭弹初速" if species == "Rocket" else "投弹初速"
                items.append(self.make_item(f"  {display_speed}: {p['bullet_speed']:.0f} m/s", "", len(items)))
            if ammo_type == "HE":
                if p['alpha_piercing_he']:
                    items.append(self.make_item(f"  穿深: {p['alpha_piercing_he']:.1f} mm", "", len(items)))
                if p['burn_prob']:
                    items.append(self.make_item(f"  基础点火率: {p['burn_prob']*100:.1f}%", "", len(items)))
            elif ammo_type == "CS":
                if p['alpha_piercing_cs']:
                    items.append(self.make_item(f"  穿深: {p['alpha_piercing_cs']:.1f} mm", "", len(items)))
            elif ammo_type == "AP":
                if p['bullet_krupp']:
                    items.append(self.make_item(f"  {'火箭弹硬度' if species=='Rocket' else '炸弹硬度'}: {p['bullet_krupp']:.0f}", "", len(items)))
            if p['explosion_radius']:
                items.append(self.make_item(f"  爆炸损坏半径: {p['explosion_radius']/3:.1f} m", "", len(items)))
            if species == "Rocket":
                seq = extra.get("attackSequenceDurations") or p.get('attack_sequence_durations') or ''
                if seq:
                    try:
                        seq_list = json.loads(seq) if isinstance(seq, str) else seq
                        items.append(self.make_item(f"  攻击延迟序列: {seq_list} s", "", len(items)))
                    except Exception:
                        pass
            if species == "Bomb" and ammo_type in ("AP", "CS"):
                if p['bullet_always_ricochet_at']:
                    items.append(self.make_item(f"  强制跳弹角: {p['bullet_always_ricochet_at']:.0f}°", "", len(items)))
                if p['bullet_ricochet_at']:
                    items.append(self.make_item(f"  概率跳弹角: {p['bullet_ricochet_at']:.0f}°", "", len(items)))
                if ammo_type == "AP":
                    if p['bullet_detonator']:
                        items.append(self.make_item(f"  引信长度: {p['bullet_detonator']:.0f} s", "", len(items)))
                    if p['bullet_detonator_threshold']:
                        items.append(self.make_item(f"  引信触发阈值: {p['bullet_detonator_threshold']:.0f} mm", "", len(items)))

        # ── 火炮炮弹 ────────────────────────────────────
        elif species == "Artillery":
            if p['bullet_mass']:
                items.append(self.make_item(f"  炮弹质量: {p['bullet_mass']:.0f} kg", "", len(items)))
            if p['bullet_diameter']:
                items.append(self.make_item(f"  炮弹口径: {p['bullet_diameter']*1000:.2f} mm", "", len(items)))
            if p['bullet_speed']:
                items.append(self.make_item(f"  出膛初速: {p['bullet_speed']:.0f} m/s", "", len(items)))
            if p['bullet_air_drag']:
                items.append(self.make_item(f"  阻力系数: {p['bullet_air_drag']}", "", len(items)))
            if ammo_type == "AP":
                if p['bullet_krupp']:
                    items.append(self.make_item(f"  弹头硬度: {p['bullet_krupp']:.0f}", "", len(items)))
            if ammo_type == "HE":
                if p['alpha_piercing_he']:
                    items.append(self.make_item(f"  穿深: {p['alpha_piercing_he']:.1f} mm", "", len(items)))
                if p['burn_prob']:
                    items.append(self.make_item(f"  基础点火率: {p['burn_prob']*100:.1f}%", "", len(items)))
                if p['explosion_radius']:
                    items.append(self.make_item(f"  爆炸损坏半径: {p['explosion_radius']/3:.1f} m", "", len(items)))
            elif ammo_type == "CS":
                if p['alpha_piercing_cs']:
                    items.append(self.make_item(f"  穿深: {p['alpha_piercing_cs']:.1f} mm", "", len(items)))
            if ammo_type in ("AP", "CS"):
                if p['bullet_always_ricochet_at']:
                    items.append(self.make_item(f"  强制跳弹角: {p['bullet_always_ricochet_at']:.0f}°", "", len(items)))
                if p['bullet_ricochet_at']:
                    items.append(self.make_item(f"  概率跳弹角: {p['bullet_ricochet_at']:.0f}°", "", len(items)))
                if p['bullet_cap_normalize_max']:
                    items.append(self.make_item(f"  弹头转正角: {p['bullet_cap_normalize_max']:.0f}°", "", len(items)))
                if ammo_type == "AP":
                    if p['bullet_detonator']:
                        items.append(self.make_item(f"  引信长度: {p['bullet_detonator']:.0f} s", "", len(items)))
                    if p['bullet_detonator_threshold']:
                        items.append(self.make_item(f"  引信触发阈值: {p['bullet_detonator_threshold']:.0f} mm", "", len(items)))

        # ── 鱼雷 ────────────────────────────────────────
        elif species == "Torpedo":
            t_type = p['torpedo_type']
            is_deep = p['is_deep_water']
            postfix = (p['custom_ui_postfix'] or '').strip()
            is_burn = postfix == "_subBurn"
            if t_type == 1:
                dtype = "声呐导向鱼雷"
            elif is_deep:
                dtype = "深水鱼雷"
            elif is_burn:
                dtype = "热能鱼雷"
            else:
                dtype = "鱼雷"
            items.append(self.make_item(f"  类型: {dtype}", "", len(items)))
            if p['damage']:
                items.append(self.make_item(f"  溅射伤害: {p['damage']:.0f}", "", len(items)))
            if is_burn and p['burn_prob']:
                items.append(self.make_item(f"  基础点火率: {p['burn_prob']*100:.0f}%", "", len(items)))
            if is_deep:
                ignores = extra.get("ignoreClasses", [])
                if ignores:
                    cls_str = ', '.join(NM.SHIP_CLASS_MAP.get(c, c) for c in ignores)
                    items.append(self.make_item(f"  无法攻击目标: {cls_str}", "", len(items)))
            raw_dist = p['torpedo_max_dist'] or 0
            if raw_dist:
                items.append(self.make_item(f"  最大射程: {raw_dist*30/1000:.1f} km", "", len(items)))
            if p['torpedo_speed']:
                items.append(self.make_item(f"  航速: {p['torpedo_speed']:.0f} kts", "", len(items)))
            if p['torpedo_uw_critical']:
                items.append(self.make_item(f"  基础漏水率: {p['torpedo_uw_critical']*100:.0f}%", "", len(items)))
            if p['torpedo_visibility']:
                items.append(self.make_item(f"  被发现距离: {p['torpedo_visibility']:.1f} km", "", len(items)))
            if p['torpedo_arming_time']:
                items.append(self.make_item(f"  鱼雷触发延迟: {p['torpedo_arming_time']:.0f} s", "", len(items)))
            if t_type == 1:
                stp = extra.get("submarineTorpedoParams", {})
                if stp:
                    max_yaw = stp.get("maxYaw", [0])[0] if isinstance(stp.get("maxYaw"), list) else stp.get("maxYaw", 0)
                    yaw_speed = stp.get("yawChangeSpeed", [0])[0] if isinstance(stp.get("yawChangeSpeed"), list) else stp.get("yawChangeSpeed", 0)
                    items.append(self.make_item(f"  最大转向角: {max_yaw}°", "", len(items)))
                    items.append(self.make_item(f"  转向角速度: {yaw_speed}°/s", "", len(items)))
                    drop = stp.get("dropTargetAtDistance", {})
                    if drop:
                        for ship_class, dist_list in drop.items():
                            val = dist_list[0] if isinstance(dist_list, list) else dist_list
                            items.append(self.make_item(f"    {NM.SHIP_CLASS_MAP.get(ship_class, ship_class)}: {val} m", "", len(items)))

        # ── 深水炸弹 ────────────────────────────────────
        elif species == "DepthCharge":
            if p['bullet_speed']:
                items.append(self.make_item(f"  下潜速度: {p['bullet_speed']:.0f} m/s", "", len(items)))
            if p['dc_timer']:
                items.append(self.make_item(f"  爆炸计时: {p['dc_timer']:.0f} s", "", len(items)))
            if p['dc_max_depth']:
                items.append(self.make_item(f"  最大自毁深度: {abs(p['dc_max_depth']):.0f} m", "", len(items)))
            if p['depth_splash_size']:
                items.append(self.make_item(f"  对舰/潜溅射半径: {p['depth_splash_size']:.0f} m", "", len(items)))
            if p['depth_splash_size_to_torpedo']:
                items.append(self.make_item(f"  对鱼雷溅射半径: {p['depth_splash_size_to_torpedo']:.0f} m", "", len(items)))
            buoyancy = extra.get("buoyancyToDamageCoeff", {})
            if buoyancy:
                order = ["SURFACE", "PERISCOPE", "SEMI_DEEP_WATER", "DEEP_WATER", "DEEP_WATER_INVUL"]
                for state in order:
                    if state in buoyancy:
                        items.append(self.make_item(
                            f"  {NM.BUOYANCY_MAP.get(state, state)}: {buoyancy[state]*100:.0f}%", "", len(items)))

        # ── 激光 ────────────────────────────────────────
        elif species == "Laser":
            if p['alpha_piercing_he']:
                items.append(self.make_item(f"  穿深: {p['alpha_piercing_he']:.1f} mm", "", len(items)))
            if p['bullet_speed']:
                items.append(self.make_item(f"  飞行初速: {p['bullet_speed']:.0f} m/s", "", len(items)))
            if p['laser_heat']:
                items.append(self.make_item(f"  热量积累值: {p['laser_heat']:.0f}", "", len(items)))
            if p['laser_heat_radius']:
                items.append(self.make_item(f"  热效应半径: {p['laser_heat_radius']:.0f} m", "", len(items)))
            if p['laser_damage_types']:
                dtypes = json.loads(p['laser_damage_types']) if isinstance(p['laser_damage_types'], str) else p['laser_damage_types']
                if dtypes:
                    items.append(self.make_item(f"  影响伤害类型: {', '.join(dtypes)}", "", len(items)))

        # ── 波浪 ────────────────────────────────────────
        elif species == "Wave":
            if p['wave_max_damage_pct']:
                items.append(self.make_item(f"  最大伤害比例: {p['wave_max_damage_pct']:.1f}%", "", len(items)))
            if p['wave_min_damage_pct']:
                items.append(self.make_item(f"  最小伤害比例: {p['wave_min_damage_pct']:.1f}%", "", len(items)))
            if p['wave_speed']:
                items.append(self.make_item(f"  波浪扩散速度: {p['wave_speed']:.0f} m/s", "", len(items)))
            if p['wave_sector']:
                items.append(self.make_item(f"  波浪覆盖扇区: {p['wave_sector']:.0f}°", "", len(items)))

        return {
            "title": p['ammo_name_zh'] or proj_id,
            "subtitle": f"ID: {proj_id} | {display_type}",
            "sections": [self.make_section("详情", items)],
        }
