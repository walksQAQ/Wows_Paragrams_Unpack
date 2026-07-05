"""
ShipPresenter —— 从结构化数据库表组装舰船显示数据（新架构）。
"""

from __future__ import annotations

import json
import re
from collections import Counter

from presenters.base_presenter import BasePresenter, NM


class ShipPresenter(BasePresenter):
    """将舰船数据库记录组装为显示结构"""

    def build(self, ship_id: str, version_code: str = "") -> dict | None:
        try:
            return self._do_build(ship_id, version_code)
        except Exception as e:
            import traceback
            from app.signals import bus
            traceback.print_exc()
            bus.log_message.emit(f"⚠️ [ShipPresenter] {ship_id} 构建失败: {e}")
            return None

    def _do_build(self, ship_id: str, version_code: str = "") -> dict | None:
        sections: list[dict] = []
        conn = self.conn
        vc = self._ensure_version(version_code)

        # ── 1. 基础属性 ────────────────────────────────────
        basic = conn.execute(
            "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?", (vc, ship_id)).fetchone()
        if not basic:
            return None

        ship_name = self.resolve_name_by_id(basic['name_mapping_id'], 'ship', ship_id) or ship_id
        items = [
            self.make_item(f"  舰船名称: {ship_name}", "", 0),
            self.make_item(f"  编号: {basic['ship_index'] or ship_id.split('_')[0]}", "", 1),
        ]
        for k, label in [("shiptype", "舰种"), ("tier", "等级"), ("group_status_key", "状态")]:
            if basic[k]:
                items.append(self.make_item(f"  {label}: {basic[k]}", "", len(items)))

        # parent_ship / origin_ship 原始 entity_id 展示
        for k, label in [("parent_ship_id", "原型舰船"), ("origin_ship_id", "原型舰船")]:
            if basic[k]:
                items.append(self.make_item(f"  {label}: {basic[k]}", "", len(items)))
        sections.append(self.make_section("基础属性", items))

        # ── 2. 消耗品数据 ─────────────────────────────────
        self._append_consumables(conn, vc, ship_id, sections)

        # ── 3. 战斗指令 ───────────────────────────────────
        self._append_rage_mode(conn, vc, ship_id, sections)

        # ── 4. 各类型模块数据 ────────────────────────────
        self._append_modules(conn, vc, ship_id, sections)

        # ── 5. 构建子 section 信息 ───────────────────────
        sub_info = self._build_sub_section_info(conn, vc, ship_id, sections)

        return {
            "title": ship_name,
            "subtitle": f"ID: {ship_id}",
            "sections": sections,
            "extra": {"sub_sections": sub_info} if sub_info else {},
        }

    # ── 辅助 ───────────────────────────────────────────────

    @staticmethod
    def _config_group_letter(config_group: str) -> str:
        """从 config_group (如 'AB1', 'A') 提取首字母"""
        return config_group[0] if config_group else "?"

    def _append_consumables(self, conn, vc, ship_id, sections):
        slots = conn.execute(
            "SELECT * FROM ship_consumable_slots WHERE version_code=? AND ship_id=? ORDER BY slot_index, item_index",
            (vc, ship_id)).fetchall()
        if not slots:
            return
        items = []
        last_slot = None
        for s in slots:
            if s['slot_index'] != last_slot:
                if last_slot is not None:
                    items.append(self.make_item(f"      {'─' * 20}", "", len(items)))
                items.append(self.make_item(f"  第 {s['slot_index']} 槽位:", "", len(items)))
                last_slot = s['slot_index']
            cname = self.resolve_name_by_id(s['display_name_id'], 'consumable', s['consumable_id']) or s['consumable_id'] or ""
            items.append(self.make_item(f"    ({s['item_index']}) {cname}", "", len(items)))
            ct = s['consumable_type'] or ""
            num_raw = s['num_consumables']
            if num_raw and num_raw not in ('0', 0):
                items.append(self.make_item(f"      数量: {'无限' if str(num_raw)=='-1' else str(num_raw)}", "", len(items)))
            if ct:
                items.append(self.make_item(f"      类型: {ct}", "", len(items)))
            if s['is_auto_consumable']:
                items.append(self.make_item(f"      自动使用: 是", "", len(items)))
            for k, label in [("preparation_time", "准备时间"), ("work_time", "作用时间"), ("reload_time", "冷却时间")]:
                val = s[k]
                if val and float(val) > 0:
                    items.append(self.make_item(f"      {label}: {val}s", "", len(items)))
        if last_slot is not None:
            items.append(self.make_item(f"      {'─' * 20}", "", len(items)))
        sections.append(self.make_section("消耗品数据", items))

    # ── 战斗指令 ───────────────────────────────────────────

    def _append_rage_mode(self, conn, vc, ship_id, sections):
        rage = conn.execute(
            "SELECT * FROM ship_rage_mode WHERE version_code=? AND ship_id=?", (vc, ship_id)).fetchone()
        if not rage:
            return
        items = []
        o = 0
        dname = self.resolve_name_by_id(rage['display_name_id'], 'rage_mode', '') or "战斗指令"
        items.append(self.make_item(f"  === {dname} ===", "", o)); o += 1
        items.append(self.make_item(f"    持续时间: {rage['boost_duration']}s", "", o)); o += 1
        max_ac = rage['max_activation_count']
        items.append(self.make_item(f"    最大激活次数: {'无限' if max_ac=='-1' else f'{max_ac} 次'}", "", o)); o += 1
        items.append(self.make_item(f"    自动激活: {'是' if rage['is_auto_usage'] else '否'}", "", o)); o += 1

        if rage['decrement_delay']:
            items.append(self.make_item(f"    衰减倒计时: {rage['decrement_delay']}s", "", o)); o += 1
            items.append(self.make_item(f"    衰减周期: {rage['decrement_period']}s", "", o)); o += 1
            items.append(self.make_item(f"    衰减数值: {rage['decrement_count']}%", "", o)); o += 1

        triggers = json.loads(rage['triggers_json'] or '[]')
        if triggers:
            for trig_obj in triggers:
                for tkey, tdata in trig_obj.items():
                    act = tdata.get("Activator", {})
                    if act:
                        atype = act.get("type", "Unknown")
                        items.append(self.make_item(f"    激活: {atype}", "", o)); o += 1
                        for ak, av in act.items():
                            if ak == "type": continue
                            label = NM.DETAIL_MAP.get(ak, ak)
                            items.append(self.make_item(f"      - {label}: {av}", "", o)); o += 1
        sections.append(self.make_section("战斗指令", items))

    # ── 模块 ───────────────────────────────────────────────

    def _append_modules(self, conn, vc, ship_id, sections):
        # 获取所有配置组前缀字母
        letters = set()
        for tbl in ["ship_module_hulls", "ship_module_artillery", "ship_module_atba",
                      "ship_module_torpedoes", "ship_module_aa", "ship_module_depth_charge",
                      "ship_module_aircraft", "ship_module_air_support", "ship_module_engine"]:
            for r in conn.execute(
                f"SELECT DISTINCT config_group FROM {tbl} WHERE version_code=? AND ship_id=?",
                (vc, ship_id)).fetchall():
                letters.add(self._config_group_letter(r[0]))
        if not letters:
            return
        letters = sorted(letters)

        # 为每个字母收集各模块数据
        hull_data, arty_data, atba_data, torp_data = {}, {}, {}, {}
        aa_data, dc_data, plane_data, asup_data = {}, {}, {}, {}

        for letter in letters:
            self._build_hull(conn, vc, ship_id, letter, hull_data)
            self._build_artillery(conn, vc, ship_id, letter, arty_data)
            self._build_atba(conn, vc, ship_id, letter, atba_data)
            self._build_torpedoes(conn, vc, ship_id, letter, torp_data)
            self._build_aa(conn, vc, ship_id, letter, aa_data)
            self._build_depth_charge(conn, vc, ship_id, letter, dc_data)
            self._build_aircraft(conn, vc, ship_id, letter, plane_data)
            self._build_air_support(conn, vc, ship_id, letter, asup_data)

        for label, data in [("船体", hull_data), ("主炮", arty_data), ("副炮", atba_data),
                             ("鱼雷", torp_data), ("防空", aa_data), ("深水炸弹", dc_data),
                             ("舰载机", plane_data), ("空袭", asup_data)]:
            if data:
                all_lines = []
                for letter in letters:
                    letter_lines = data.get(letter, [])
                    if letter_lines:
                        if len(letters) > 1:
                            all_lines.append(f"──── {letter} 配置 ────")
                        all_lines.extend(letter_lines)
                if all_lines:
                    sections.append(self.make_section(label, [self.make_item("", "\n".join(all_lines), 0)]))

    # ── 模块构建子方法 ─────────────────────────────────────

    def _build_hull(self, conn, vc, ship_id, letter, result):
        lines = []
        for h in conn.execute(
            "SELECT * FROM ship_module_hulls WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            for col, label in [
                ("health", "基础血量"), ("max_speed", "最大航速(kts)"),
                ("turning_radius", "转弯半径(m)"), ("rudder_time", "转舵时间(s)"),
                ("conceal_sea", "水面隐蔽(km)"), ("conceal_air", "空中隐蔽(km)"),
                ("has_citadel", "是否有核心区"), ("engine_power", "引擎马力(HP)"),
            ]:
                val = h[col]
                if val is not None:
                    if isinstance(val, float):
                        val = round(val, 2)
                    elif col in ("has_citadel",):
                        val = "是" if val else "否"
                    lines.append(f"    - {label}: {val}")
            # 潜艇扩展数据
            ext = conn.execute(
                "SELECT * FROM ship_module_hulls_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                (vc, ship_id, h['config_group'], h['module_key'])).fetchone()
            if ext:
                for col, label in [("battery_capacity", "电池容量"), ("battery_regen", "电力恢复")]:
                    if ext[col]:
                        lines.append(f"    - {label}: {ext[col]}")
                for col, label in [("hydrophone_radius", "水听器半径(km)"), ("hydrophone_update_freq", "更新周期")]:
                    if ext[col]:
                        lines.append(f"    - {label}: {ext[col]}")
                # 深度状态
                for ds in conn.execute(
                    "SELECT * FROM ship_sub_depth_states WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                    (vc, ship_id, h['config_group'], h['module_key'])).fetchall():
                    lines.append(f"    - 深度[{ds['state_name']}]: 航速×{ds['underwater_max_speed']}")
        if lines:
            result[letter] = lines

    def _build_artillery(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for g in conn.execute(
            "SELECT * FROM ship_module_artillery WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"火炮名称: {g['module_key']} x{g['count']}")
            if g['num_barrels']: lines.append(f"联装数: {g['num_barrels']:.0f}")
            if g['reload_time']: lines.append(f"装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"基础射程: {g['max_range']:.1f} km")
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                lines.append(f"横向散步公式: {slope:.1f}R + {intercept:.0f}")
            # 纵向散步
            if g['radius_zero'] is not None and g['radius_max'] is not None:
                r0, rdelim, rmax, delim = g['radius_zero'], g['radius_delim'], g['radius_max'], g['delim']
                pct = f"{delim*100:.0f}%" if delim else "?"
                lines.append(f"纵向散步系数: {r0} ~ {rdelim}(R={pct}) ~ {rmax}")
            if g['sigma']: lines.append(f"Sigma: {g['sigma']}")
            # 弹药（含详细属性）
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='artillery'",
                (vc, ship_id, g['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                acn = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                    "be.bullet_speed, be.explosion_radius, be.burn_prob, "
                    "be.bullet_mass, be.bullet_diameter, be.bullet_air_drag, "
                    "be.bullet_always_ricochet_at, be.bullet_ricochet_at, "
                    "be.bullet_detonator, be.bullet_detonator_threshold, be.bullet_cap_normalize_max "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    at = (p['ammo_type'] or "").upper()
                    lines.append(f"可用炮弹: {acn}")
                    if p['alpha_damage']: lines.append(f"      标伤: {p['alpha_damage']:.0f}")
                    lines.append(f"      弹种: {p['ammo_type'] or '?'}")
                    lines.append(f"      炮弹详细属性:")
                    if p['explosion_radius']: lines.append(f"              炮弹爆炸半径: {p['explosion_radius']:.1f} m")
                    if p['bullet_diameter']: lines.append(f"              炮弹口径: {p['bullet_diameter']*1000:.0f} mm")
                    if p['bullet_speed']: lines.append(f"              炮弹初速: {p['bullet_speed']:.0f} m/s")
                    if p['bullet_air_drag']: lines.append(f"              空阻系数: {p['bullet_air_drag']}")
                    if p['bullet_mass']: lines.append(f"              炮弹重量: {p['bullet_mass']:.1f} kg")
                    if at == 'HE':
                        if p['burn_prob'] is not None: lines.append(f"              起火率: {p['burn_prob']*100:.1f}%")
                        if p['bullet_krupp']: lines.append(f"              HE穿深: {p['bullet_krupp']:.0f} mm")
                    elif at == 'SAP':
                        if p['bullet_krupp']: lines.append(f"              SAP穿深: {p['bullet_krupp']:.0f} mm")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                    elif at == 'AP':
                        if p['bullet_krupp']: lines.append(f"              弹头硬度: {p['bullet_krupp']:.0f}")
                        if p['bullet_detonator'] is not None: lines.append(f"              引信触发阈值: {p['bullet_detonator']:.0f} mm")
                        if p['bullet_detonator_threshold']: lines.append(f"              引信长度: {p['bullet_detonator_threshold']:.1f} cal")
                        if p['bullet_cap_normalize_max']: lines.append(f"              炮弹转正角: {p['bullet_cap_normalize_max']:.1f}°")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                else:
                    lines.append(f"可用炮弹: {acn}")
        if lines:
            result[letter] = lines

    def _build_atba(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for g in conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"火炮名称: {g['module_key']} x{g['count']}")
            if g['num_barrels']: lines.append(f"联装数: {g['num_barrels']:.0f}")
            if g['reload_time']: lines.append(f"装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"基础射程: {g['max_range']:.1f} km")
            if g['sigma']: lines.append(f"Sigma: {g['sigma']}")
            # 散步公式
            ir, mr, id_dist = g['ideal_radius'], g['min_radius'], g['ideal_distance']
            if ir and mr and id_dist:
                slope = (ir - mr) / (id_dist / 1000) if id_dist else 0
                intercept = mr * 30
                lines.append(f"横向散步公式: {slope:.1f}R + {intercept:.0f}")
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='atba'",
                (vc, ship_id, g['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                acn = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                    "be.bullet_speed, be.explosion_radius, be.burn_prob, "
                    "be.bullet_mass, be.bullet_diameter, be.bullet_air_drag, "
                    "be.bullet_always_ricochet_at, be.bullet_ricochet_at, "
                    "be.bullet_detonator, be.bullet_detonator_threshold, be.bullet_cap_normalize_max "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    at = (p['ammo_type'] or "").upper()
                    lines.append(f"可用炮弹: {acn}")
                    if p['alpha_damage']: lines.append(f"      标伤: {p['alpha_damage']:.0f}")
                    lines.append(f"      弹种: {p['ammo_type'] or '?'}")
                    lines.append(f"      炮弹详细属性:")
                    if p['explosion_radius']: lines.append(f"              炮弹爆炸半径: {p['explosion_radius']:.1f} m")
                    if p['bullet_diameter']: lines.append(f"              炮弹口径: {p['bullet_diameter']*1000:.0f} mm")
                    if p['bullet_speed']: lines.append(f"              炮弹初速: {p['bullet_speed']:.0f} m/s")
                    if p['bullet_air_drag']: lines.append(f"              空阻系数: {p['bullet_air_drag']}")
                    if p['bullet_mass']: lines.append(f"              炮弹重量: {p['bullet_mass']:.1f} kg")
                    if at == 'HE':
                        if p['burn_prob'] is not None: lines.append(f"              起火率: {p['burn_prob']*100:.1f}%")
                        if p['bullet_krupp']: lines.append(f"              HE穿深: {p['bullet_krupp']:.0f} mm")
                    elif at == 'SAP':
                        if p['bullet_krupp']: lines.append(f"              SAP穿深: {p['bullet_krupp']:.0f} mm")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                    elif at == 'AP':
                        if p['bullet_krupp']: lines.append(f"              弹头硬度: {p['bullet_krupp']:.0f}")
                        if p['bullet_detonator'] is not None: lines.append(f"              引信触发阈值: {p['bullet_detonator']:.0f} mm")
                        if p['bullet_detonator_threshold']: lines.append(f"              引信长度: {p['bullet_detonator_threshold']:.1f} cal")
                        if p['bullet_cap_normalize_max']: lines.append(f"              炮弹转正角: {p['bullet_cap_normalize_max']:.1f}°")
                        rc1 = p['bullet_ricochet_at']
                        rc2 = p['bullet_always_ricochet_at']
                        if rc1 or rc2:
                            lines.append(f"              跳弹角度: {rc1:.0f}°/{rc2:.0f}°")
                else:
                    lines.append(f"可用炮弹: {acn}")
        if lines:
            result[letter] = lines

    def _build_torpedoes(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for t in conn.execute(
            "SELECT * FROM ship_module_torpedoes WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"  - {t['module_key']} x{t['count']}")
            if t['reload_time']: lines.append(f"    装填时间: {t['reload_time']}s")
            seen = set()
            for swp in conn.execute(
                "SELECT DISTINCT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='torpedo'",
                (vc, ship_id, t['module_key'])).fetchall():
                aid = swp["ammo_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                aname = ammo_map.get(aid.upper(), aid)
                p = conn.execute(
                    "SELECT pb.species, te.alpha_damage, te.damage, te.torpedo_speed, "
                    "te.torpedo_max_dist, te.torpedo_visibility, te.torpedo_arming_time, "
                    "te.is_deep_water, te.flood_generation "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_torpedo_ext te ON te.version_code=pb.version_code AND te.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, aid)).fetchone()
                if p:
                    dw = " (深水)" if p['is_deep_water'] else ""
                    lines.append(f"    ── {aname}{dw} ──")
                    if p['damage']: lines.append(f"      标伤: {p['damage']:.0f}")
                    if p['torpedo_speed']: lines.append(f"      航速: {p['torpedo_speed']:.0f} kts")
                    dist = p['torpedo_max_dist']
                    if dist: lines.append(f"      射程: {dist:.1f} km")
                    if p['torpedo_visibility']: lines.append(f"      被发现距离: {p['torpedo_visibility']:.2f} km")
                    if p['torpedo_arming_time']: lines.append(f"      武装时间: {p['torpedo_arming_time']:.1f} s")
                    if p['flood_generation']: lines.append(f"      进水: 是")
                else:
                    lines.append(f"    {aname}")
        if lines:
            result[letter] = lines

    def _build_aa(self, conn, vc, ship_id, letter, result):
        lines = []
        auras = {"Far": None, "Medium": None, "Near": None}
        bubble_count = 0
        bubble_dmg = 0
        guns = []
        seen_guns = set()
        for a in conn.execute(
            "SELECT * FROM ship_module_aa WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            name = a['aura_name'] or ""
            if a['aura_type'] == 'bubble':
                # 使用 DISTINCT 方式避免重复行导致计数翻倍
                if a['bubble_damage']:
                    bubble_dmg = max(bubble_dmg, a['bubble_damage'])
                    bubble_count = 1  # 有黑云数据就算1组
            elif a['aura_type'] == 'continuous':
                for key in ("Far", "Medium", "Near"):
                    if key in name:
                        # 取最大 DPS（避免重复行覆盖为同一值）
                        cur_dps = auras[key]
                        new_dps = a['aura_dps']
                        if cur_dps is None or (new_dps is not None and new_dps > cur_dps):
                            auras[key] = new_dps
                        break
            if a['aa_gun_name'] and a['aa_gun_name'] not in seen_guns:
                seen_guns.add(a['aa_gun_name'])
                gname = self.resolve_name('gun', a['aa_gun_name']) or a['aa_gun_name']
                guns.append(f"{gname} x{a['aa_gun_count']}")
        # 对 auras 去重后从 DB 重新读取汇总的黑云
        bubble_rows = conn.execute(
            "SELECT DISTINCT bubble_damage FROM ship_module_aa "
            "WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND aura_type='bubble'",
            (vc, ship_id, f"{letter}%")).fetchall()
        if bubble_rows:
            bubble_count = len(bubble_rows)
            bubble_dmg = max(r['bubble_damage'] or 0 for r in bubble_rows)
        if any(v is not None for v in auras.values()):
            labels = {"Far": "远程", "Medium": "中程", "Near": "近程"}
            for key in ("Far", "Medium", "Near"):
                if auras[key] is not None:
                    lines.append(f"    {labels[key]}防空炮秒伤: {auras[key]:.0f}")
        if bubble_count:
            lines.append(f"    黑云数量: {bubble_count}")
            if bubble_dmg:
                lines.append(f"    黑云标伤: {bubble_dmg:.0f}")
        if guns:
            for g in guns:
                lines.append(f"    防空炮: {g}")
        if lines:
            result[letter] = lines

    def _build_depth_charge(self, conn, vc, ship_id, letter, result):
        lines = []
        for d in conn.execute(
            "SELECT * FROM ship_module_depth_charge WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"    - {d['gun_name']} x{d['count']}")
        if lines:
            result[letter] = lines

    def _build_aircraft(self, conn, vc, ship_id, letter, result):
        lines = []
        # 按机种分组
        type_groups = {}
        for p in conn.execute(
            "SELECT * FROM ship_module_aircraft WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY plane_type, module_variant",
            (vc, ship_id, f"{letter}%")).fetchall():
            pt = p['plane_type'] or '其他'
            type_groups.setdefault(pt, []).append(p)

        TYPE_LABEL = {
            "Fighter": "战斗机", "DiveBomber": "俯冲轰炸机",
            "TorpedoBomber": "鱼雷轰炸机", "SkipBomber": "跳弹轰炸机",
        }
        for ptype in ("Fighter", "DiveBomber", "TorpedoBomber", "SkipBomber", "其他"):
            planes = type_groups.get(ptype, [])
            if not planes:
                continue
            label = TYPE_LABEL.get(ptype, ptype)
            lines.append(f"  [{label}]")
            for p in planes:
                pn = p['plane_name']
                arm = p['armament_name'] or "N/A"
                lines.append(f"    - {pn}")
                # 从 projectile_basic_info + 对应扩增表查询飞机弹药详情
                if arm and arm != "N/A":
                    ammo = conn.execute(
                        "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                        "be.bullet_speed, be.explosion_radius, be.burn_prob "
                        "FROM projectile_basic_info pb "
                        "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                        "WHERE pb.version_code=? AND pb.projectile_id=?",
                        (vc, arm)).fetchone()
                    if ammo:
                        lines.append(f"      ── 弹药: {ammo['ammo_type'] or '?'} ──")
                        if ammo['alpha_damage']: lines.append(f"        标伤: {ammo['alpha_damage']:.0f}")
                        if ammo['bullet_krupp']: lines.append(f"        穿深: {ammo['bullet_krupp']:.0f}")
                        if ammo['bullet_speed']: lines.append(f"        弹速: {ammo['bullet_speed']:.0f} m/s")
                        if ammo['explosion_radius']: lines.append(f"        爆炸半径: {ammo['explosion_radius']:.1f} m")
                        if ammo['burn_prob'] is not None: lines.append(f"        起火概率: {ammo['burn_prob']*100:.1f}%")
                    else:
                        # 尝试按 torpedo 查
                        torp = conn.execute(
                            "SELECT te.alpha_damage, te.damage, te.torpedo_speed, te.torpedo_max_dist, "
                            "te.torpedo_visibility, te.torpedo_arming_time, te.flood_generation "
                            "FROM projectile_basic_info pb "
                            "LEFT JOIN projectile_torpedo_ext te ON te.version_code=pb.version_code AND te.projectile_id=pb.projectile_id "
                            "WHERE pb.version_code=? AND pb.projectile_id=?",
                            (vc, arm)).fetchone()
                        if torp and (torp['damage'] is not None or torp['torpedo_speed'] is not None):
                            lines.append(f"      ── 弹药: 鱼雷 ──")
                            if torp['damage'] is not None: lines.append(f"        标伤: {torp['damage']:.0f}")
                            if torp['torpedo_speed'] is not None: lines.append(f"        航速: {torp['torpedo_speed']:.0f} kts")
                            if torp['torpedo_max_dist']: lines.append(f"        射程: {torp['torpedo_max_dist']:.1f} km")
                            if torp['torpedo_visibility']: lines.append(f"        被发现距离: {torp['torpedo_visibility']:.2f} km")
                            if torp['torpedo_arming_time']: lines.append(f"        武装时间: {torp['torpedo_arming_time']:.1f} s")
                            if torp['flood_generation']: lines.append(f"        进水: 是")
                # 从 ship_module_aircraft 查中队规模
                count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM ship_module_aircraft WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND plane_name=?",
                    (vc, ship_id, f"{letter}%", pn)).fetchone()
                if count and count['cnt'] > 1:
                    lines.append(f"      中队: {count['cnt']} 架")
        if lines:
            result[letter] = lines

    def _build_air_support(self, conn, vc, ship_id, letter, result):
        lines = []
        for s in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            arm = s['armament_name'] or ""
            lines.append(f"    - {s['plane_name']}: {s['charges']}次 {s['reload_time']}s装填")
            if arm:
                # 查询弹药详情
                ammo = conn.execute(
                    "SELECT pb.species, pb.ammo_type, be.alpha_damage, be.bullet_krupp, "
                    "be.bullet_speed, be.explosion_radius, be.burn_prob "
                    "FROM projectile_basic_info pb "
                    "LEFT JOIN projectile_bullet_ext be ON be.version_code=pb.version_code AND be.projectile_id=pb.projectile_id "
                    "WHERE pb.version_code=? AND pb.projectile_id=?",
                    (vc, arm)).fetchone()
                if ammo:
                    lines.append(f"      ── 弹药: {ammo['ammo_type'] or '?'} ──")
                    if ammo['alpha_damage']: lines.append(f"        标伤: {ammo['alpha_damage']:.0f}")
                    if ammo['bullet_krupp']: lines.append(f"        穿深: {ammo['bullet_krupp']:.0f}")
                    if ammo['bullet_speed']: lines.append(f"        弹速: {ammo['bullet_speed']:.0f} m/s")
                    if ammo['explosion_radius']: lines.append(f"        爆炸半径: {ammo['explosion_radius']:.1f} m")
                    if ammo['burn_prob'] is not None: lines.append(f"        起火概率: {ammo['burn_prob']*100:.1f}%")
                else:
                    torp = conn.execute(
                        "SELECT te.damage, te.torpedo_speed "
                        "FROM projectile_basic_info pb "
                        "LEFT JOIN projectile_torpedo_ext te ON te.version_code=pb.version_code AND te.projectile_id=pb.projectile_id "
                        "WHERE pb.version_code=? AND pb.projectile_id=?",
                        (vc, arm)).fetchone()
                    if torp and (torp['damage'] is not None or torp['torpedo_speed'] is not None):
                        parts = []
                        if torp['damage'] is not None: parts.append(f"标伤{torp['damage']:.0f}")
                        if torp['torpedo_speed'] is not None: parts.append(f"航速{torp['torpedo_speed']:.0f}kts")
                        lines.append(f"      ── 弹药 ──")
                        lines.append(f"        {' '.join(parts)}")
        if lines:
            result[letter] = lines

    def _build_sub_section_info(self, conn, vc, ship_id, sections):
        """构建子分类映射：模块类型(船体/主炮) → {A/B/C 配置 → 内容}"""
        from collections import defaultdict
        # 先收集每封信的 module_id 列表
        letter_modules: dict[str, list[str]] = defaultdict(list)
        for r in conn.execute(
            "SELECT DISTINCT config_group, module_id FROM ship_module_relations "
            "WHERE version_code=? AND ship_id=? AND config_group NOT LIKE '%special%'",
            (vc, ship_id)).fetchall():
            cg = r["config_group"]
            letter = self._config_group_letter(cg)
            if letter not in letter_modules:
                letter_modules[letter] = []
        letters = sorted(letter_modules.keys())
        if len(letters) <= 1:
            return {}

        # 为每个 section label 提取该 section 下按 letter 拆分的内容
        sub_info: dict[str, dict] = {}
        for section in sections:
            label = section.get("label", "")
            # 检查该 section 是否为模块型（在 _append_modules 中添加的带 letter 分隔的 section）
            items = section.get("items", [])
            all_text = []
            for item in sorted(items, key=lambda x: x.get("order", 0)):
                n = item.get("name", "")
                v = item.get("value", "")
                all_text.append(v or n or "")
            full_text = "\n".join(all_text)
            # 按 letter 分割内容（查找 ──── X 配置 ──── 标记）
            letter_contents: dict[str, list[str]] = {}
            current_letter = None
            for line in full_text.split("\n"):
                m_letter = None
                for lt in letters:
                    if f"──── {lt} 配置 ────" in line:
                        m_letter = lt
                        break
                if m_letter is not None:
                    current_letter = m_letter
                    letter_contents.setdefault(current_letter, [])
                elif current_letter is not None:
                    letter_contents.setdefault(current_letter, []).append(line)
            if letter_contents and len(letter_contents) > 1:
                sub_labels = sorted(letter_contents.keys())
                sub_info[label] = {
                    "sub_labels": [f"{l} 配置" for l in sub_labels],
                    "sub_contents": {f"{l} 配置": letter_contents[l] for l in sub_labels},
                }
        return sub_info
