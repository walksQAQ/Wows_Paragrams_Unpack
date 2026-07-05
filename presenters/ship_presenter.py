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

        ship_name = self._resolve_name_by_id(basic['name_mapping_id']) or ship_id
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

    def _resolve_name_by_id(self, mapping_id):
        if not mapping_id:
            return None
        r = self.conn.execute("SELECT lang_zh FROM name_mappings WHERE id=?", (mapping_id,)).fetchone()
        return r[0] if r else None

    def _ensure_vc(self, vc):
        return vc or self._ensure_version("")

    @staticmethod
    def _config_group_letter(config_group: str) -> str:
        """从 config_group (如 'AB1', 'A') 提取首字母"""
        return config_group[0] if config_group else "?"

    # ── 消耗品 ─────────────────────────────────────────────

    def _append_consumables(self, conn, vc, ship_id, sections):
        slots = conn.execute(
            "SELECT * FROM ship_consumable_slots WHERE version_code=? AND ship_id=? ORDER BY slot_index, item_index",
            (vc, ship_id)).fetchall()
        if not slots:
            return
        items = []
        for s in slots:
            items.append(self.make_item(f"  第 {s['slot_index']} 槽位:", "", len(items)))
            cname = self._resolve_name_by_id(s['display_name_id']) or s['consumable_id'] or ""
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
        dname = self._resolve_name_by_id(rage['display_name_id']) or "战斗指令"
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
                    all_lines.extend(data.get(letter, []))
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
            lines.append(f"  - {g['module_key']} x{g['count']}")
            lines.append(f"    联装数: {g['num_barrels']:.0f}")
            if g['reload_time']: lines.append(f"    装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"    最大射程: {g['max_range']:.1f} km")
            if g['sigma']: lines.append(f"    Sigma: {g['sigma']}")
            if g['rotation_speed_h'] is not None:
                lines.append(f"    回转速度: H{g['rotation_speed_h']:.1f}°/s V{g['rotation_speed_v']:.1f}°/s")
            # 弹药
            for swp in conn.execute(
                "SELECT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='artillery'",
                (vc, ship_id, g['module_key'])).fetchall():
                acn = ammo_map.get(swp["ammo_id"].upper(), swp["ammo_id"])
                lines.append(f"    可用弹药: {acn}")
        if lines:
            result[letter] = lines

    def _build_atba(self, conn, vc, ship_id, letter, result):
        lines = []
        ammo_map = self.get_name_map("ammo")
        for g in conn.execute(
            "SELECT * FROM ship_module_atba WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_key",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"  - {g['module_key']} x{g['count']}")
            if g['reload_time']: lines.append(f"    装填时间: {g['reload_time']}s")
            if g['max_range']: lines.append(f"    基础射程: {g['max_range']:.1f} km")
            for swp in conn.execute(
                "SELECT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='atba'",
                (vc, ship_id, g['module_key'])).fetchall():
                acn = ammo_map.get(swp["ammo_id"].upper(), swp["ammo_id"])
                lines.append(f"    可用弹药: {acn}")
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
            for swp in conn.execute(
                "SELECT ammo_id FROM ship_weapon_projectiles "
                "WHERE version_code=? AND ship_id=? AND module_id=? AND slot_type='torpedo'",
                (vc, ship_id, t['module_key'])).fetchall():
                aname = ammo_map.get(swp["ammo_id"].upper(), swp["ammo_id"])
                lines.append(f"    鱼雷: {aname}")
        if lines:
            result[letter] = lines

    def _build_aa(self, conn, vc, ship_id, letter, result):
        lines = []
        for a in conn.execute(
            "SELECT * FROM ship_module_aa WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            if a['aura_name']:
                dtype = "黑云" if a['aura_type']=='bubble' else "持续伤害"
                lines.append(f"    - {a['aura_name']} ({dtype}) DPS:{a['aura_dps']:.0f}")
            if a['aa_gun_name']:
                lines.append(f"    - 防空炮: {a['aa_gun_name']} x{a['aa_gun_count']}")
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
        for p in conn.execute(
            "SELECT * FROM ship_module_aircraft WHERE version_code=? AND ship_id=? AND config_group LIKE ? ORDER BY module_variant",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"    - {p['plane_name']} ({p['armament_name'] or 'N/A'})")
        if lines:
            result[letter] = lines

    def _build_air_support(self, conn, vc, ship_id, letter, result):
        lines = []
        for s in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE version_code=? AND ship_id=? AND config_group LIKE ?",
            (vc, ship_id, f"{letter}%")).fetchall():
            lines.append(f"    - {s['plane_name']}: {s['charges']}次 {s['reload_time']}s装填")
        if lines:
            result[letter] = lines

    def _build_sub_section_info(self, conn, vc, ship_id, sections):
        """构建模块字母→子分类映射信息"""
        sub_info = {}
        for section in sections:
            label = section.get("label", "")
            for r in conn.execute(
                "SELECT DISTINCT config_group FROM ship_module_relations "
                "WHERE version_code=? AND ship_id=? AND config_group NOT LIKE '%special%'",
                (vc, ship_id)).fetchall():
                cg = r[0]
                letter = self._config_group_letter(cg)
                mod_label = f"{letter} 模块"
                if mod_label not in sub_info:
                    sub_info[mod_label] = {"sub_labels": [], "source_keys": {}}
                if label not in sub_info[mod_label]["sub_labels"]:
                    sub_info[mod_label]["sub_labels"].append(label)
                    sub_info[mod_label]["source_keys"][label] = cg
        return sub_info
