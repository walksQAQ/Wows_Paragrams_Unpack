"""
ShipPresenter —— 从结构化数据库表组装舰船显示数据。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from presenters.base_presenter import BasePresenter, NM


class ShipPresenter(BasePresenter):
    """将舰船数据库记录组装为显示结构"""

    def build(self, ship_id: str) -> dict | None:
        """主入口：返回完整的舰船显示结构"""
        try:
            return self._do_build(ship_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ShipPresenter] {ship_id} 构建失败: {e}")
            return None

    def _do_build(self, ship_id: str) -> dict | None:
        sections: list[dict] = []
        sub_section_info: dict[str, dict] = {}
        conn = self.conn

        # ══════════════════════════════════════════════════
        # 1. 基础属性
        # ══════════════════════════════════════════════════
        basic = conn.execute(
            "SELECT * FROM ship_basic_info WHERE ship_id=?", (ship_id,)).fetchone()
        if not basic:
            return None

        items = [
            self.make_item(f"  舰船名称: {basic['ship_name_zh'] or ship_id}", "", 0),
            self.make_item(f"  编号: {basic['ship_index'] or ship_id.split('_')[0]}", "", 1),
            self.make_item(f"  shipid: {basic['ship_id_num'] or ship_id.split('_')[0]}", "", 2),
        ]
        for k, v in [("nation_zh", "国家"), ("shiptype_zh", "舰种"),
                      ("tier_display", "等级"), ("group_status", "状态"),
                      ("parent_ship_name", "原型舰船"), ("origin_ship_name", "原型舰船")]:
            val = basic[k]
            if val:
                items.append(self.make_item(f"  {v}: {val}", "", len(items)))
        sections.append(self.make_section("基础属性", items))

        # ══════════════════════════════════════════════════
        # 2. 消耗品数据
        # ══════════════════════════════════════════════════
        slots = conn.execute(
            "SELECT * FROM ship_consumable_slots WHERE ship_id=? ORDER BY slot_index, item_index",
            (ship_id,)).fetchall()
        if slots:
            items = []
            for s in slots:
                items.append(self.make_item(f"  第 {s['slot_index']} 槽位:", "", len(items)))
                items.append(self.make_item(
                    f"    ({s['item_index']}) {s['display_name'] or ''}", "", len(items)))
                # 数量：-1 为无限
                num_raw = s['num_consumables']
                if num_raw is not None and num_raw not in ('', '0', 0, 0.0):
                    num_display = "无限" if str(num_raw) == '-1' else str(num_raw)
                    items.append(self.make_item(f"      数量: {num_display}", "", len(items)))
                for k, v in [("preparation_time", "准备时间"),
                              ("work_time", "作用时间"), ("reload_time", "装填时间")]:
                    val = s[k]
                    if val and float(val) > 0:
                        items.append(self.make_item(
                            f"      {v}: {val}s", "", len(items)))
            sections.append(self.make_section("消耗品数据", items))

        # ══════════════════════════════════════════════════
        # 3. 战斗指令
        # ══════════════════════════════════════════════════
        rage = conn.execute(
            "SELECT * FROM ship_rage_mode WHERE ship_id=?", (ship_id,)).fetchone()
        if rage:
            items = []
            o = 0
            items.append(self.make_item(f"  === {rage['display_name']} ===", "", o)); o += 1
            items.append(self.make_item(f"  [基础属性]", "", o)); o += 1
            items.append(self.make_item(f"    持续时间: {rage['boost_duration']}s", "", o)); o += 1
            max_ac = rage['max_activation_count']
            items.append(self.make_item(
                f"    最大激活次数: {'无限' if max_ac=='-1' else f'{max_ac} 次'}", "", o)); o += 1
            items.append(self.make_item(
                f"    自动激活: {'是' if rage['is_auto_usage'] else '否'}", "", o)); o += 1
            items.append(self.make_item(
                f"    常驻生效: {'是' if rage['is_modifier_works_always'] else '否'}", "", o)); o += 1

            # 衰减逻辑
            delay = rage['decrement_delay'] or 0
            if delay > 0:
                items.append(self.make_item(f"  [衰减逻辑]", "", o)); o += 1
                items.append(self.make_item(f"    衰减倒计时: {delay}s", "", o)); o += 1
                items.append(self.make_item(f"    衰减周期: {rage['decrement_period']}s", "", o)); o += 1
                items.append(self.make_item(f"    衰减数值: {rage['decrement_count']}%", "", o)); o += 1

            # 触发器
            triggers = json.loads(rage['triggers_json'] or '[]')
            if triggers:
                TRIGGER_LABELS = {
                    "GameLogicTriggerOnActivation": "触发效果",
                    "GameLogicTriggerProgress": "进度积累",
                    "GameLogicTrigger": "进度积累",
                }
                for trig_obj in triggers:
                    for tkey, tdata in trig_obj.items():
                        tlabel = TRIGGER_LABELS.get(tkey, tkey)
                        items.append(self.make_item(f"  [{tlabel}]", "", o)); o += 1
                        act = tdata.get("Activator", {})
                        if act:
                            atype = act.get("type", "Unknown")
                            items.append(self.make_item(f"    激活: {atype}", "", o)); o += 1
                            for k, v in act.items():
                                if k == "type": continue
                                if k == "subRibbons" and isinstance(v, list):
                                    names = [NM.RIBBON_MAP.get(str(rid), f"未知勋带({rid})") for rid in v]
                                    items.append(self.make_item(
                                        f"    - 所需勋带: {', '.join(names)}", "", o)); o += 1
                                elif k == "requiredCount":
                                    items.append(self.make_item(f"    - 所需次数: {v}", "", o)); o += 1
                                elif k == "separateTracking":
                                    items.append(self.make_item(f"    - 独立追踪: {'是' if v else '否'}", "", o)); o += 1
                                elif k == "stateName":
                                    items.append(self.make_item(f"    - 状态: {v}", "", o)); o += 1
                                else:
                                    label = NM.DETAIL_MAP.get(k, k)
                                    unit = "m" if k == "radius" else ""
                                    items.append(self.make_item(
                                        f"    - {label}: {v}{' '+unit if unit else ''}", "", o)); o += 1

                        # Actions
                        actions_found = {k: v for k, v in tdata.items()
                                         if k.startswith("Action") and isinstance(v, dict)}
                        if actions_found:
                            for ak, aln in actions_found.items():
                                atype = aln.get("type", "Unknown")
                                items.append(self.make_item(f"    动作: {atype}", "", o)); o += 1
                                for k, v in aln.items():
                                    if k == "type": continue
                                    label = NM.DETAIL_MAP.get(k, k)
                                    unit = "s" if k in ("reduceTime","workTime") else ""
                                    items.append(self.make_item(
                                        f"    - {label}: {v}{' '+unit if unit else ''}", "", o)); o += 1

            # 加成效果
            mods = json.loads(rage['modifiers_json'] or '{}')
            if mods:
                items.append(self.make_item(f"  [加成效果]", "", o)); o += 1
                for mk, mv in mods.items():
                    label = NM.MODIFIER_MAP.get(mk, mk)
                    if isinstance(mv, dict):
                        for sk, sv in mv.items():
                            scn = NM.SHIP_CLASS_MAP.get(sk, sk)
                            pct = (float(sv) - 1.0) * 100
                            items.append(self.make_item(
                                f"    - [{scn}] {label}: {pct:+.0f}%", "", o)); o += 1
                    elif mk == "healthRegen":
                        items.append(self.make_item(
                            f"    - {label}: 每秒回复 {mv:.0f} HP", "", o)); o += 1
                    elif isinstance(mv, (int, float)):
                        if abs(mv) > 10.0:
                            items.append(self.make_item(f"    - {label}: +{mv:.0f}", "", o)); o += 1
                        else:
                            items.append(self.make_item(
                                f"    - {label}: {round((mv-1.0)*100):+.0f}%", "", o)); o += 1
                    else:
                        items.append(self.make_item(f"    - {label}: {mv}", "", o)); o += 1

            sections.append(self.make_section("战斗指令", items))

        # ══════════════════════════════════════════════════
        # 4. 各类型模块分离
        # ══════════════════════════════════════════════════
        ammo_map = self.get_name_map("ammo")
        module_letters = [r["module_letter"] for r in conn.execute(
            "SELECT DISTINCT module_letter FROM ship_module_mapping "
            "WHERE ship_id=? ORDER BY module_letter", (ship_id,)).fetchall()]

        if module_letters:
            hull_c = {}
            arty_c = {}
            atba_c = {}
            torp_c = {}
            aa_c = {}
            dc_c = {}
            plane_c = {}
            asup_c = {}

            for letter in module_letters:
                self._build_hull(ship_id, letter, hull_c)
                self._build_artillery(ship_id, letter, arty_c, ammo_map)
                self._build_atba(ship_id, letter, atba_c, ammo_map)
                self._build_torpedoes(ship_id, letter, torp_c)
                self._build_aa(ship_id, letter, aa_c)
                self._build_depth_charge(ship_id, letter, dc_c)
                self._build_aircraft(ship_id, letter, plane_c)
                self._build_air_support(ship_id, letter, asup_c)

            type_configs = [
                ("船体", hull_c), ("主炮", arty_c), ("副炮", atba_c),
                ("鱼雷", torp_c), ("防空", aa_c), ("深水炸弹", dc_c),
                ("舰载机", plane_c), ("空袭", asup_c),
            ]
            ship_sections = list(sections)
            for type_label, content_dict in type_configs:
                if content_dict:
                    subs = sorted(content_dict.keys())
                    sub_section_info[type_label] = {
                        "sub_labels": subs,
                        "sub_contents": content_dict,
                    }
                    ship_sections.append({
                        "label": type_label, "items": [],
                        "extra": sub_section_info[type_label],
                    })
        else:
            ship_sections = list(sections)

        return {
            "title": basic['ship_name_zh'] if basic else ship_id,
            "subtitle": f"ID: {ship_id}",
            "sections": ship_sections,
            "extra": {"sub_sections": sub_section_info},
        }

    # ── 内部构建方法 ──────────────────────────────────────

    def _build_hull(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        for h in conn.execute(
            "SELECT * FROM ship_module_hulls WHERE ship_id=? AND module_letter=? ORDER BY hull_key",
            (ship_id, letter)).fetchall():
            for col, disp in [
                ("health", "基础血量"), ("max_speed", "最大航速"),
                ("turning_radius", "转弯半径"), ("rudder_time", "转舵时间"),
                ("conceal_sea", "水面隐蔽"), ("conceal_air", "空中隐蔽"),
                ("has_citadel", "是否有核心区"), ("hull_regen_part", "船体回复率"),
                ("engine_power", "引擎马力"),
            ]:
                val = h[col]
                if val is not None:
                    if col == "rudder_time":
                        lines.append(f"    - {disp}: {val:.2f} s")
                    elif col == "hull_regen_part":
                        lines.append(f"    - {disp}: {val*100:.0f}%")
                    elif col == "conceal_sea":
                        lines.append(f"    - {disp}: {val:.2f} km")
                        min_s = val * 0.9 * 0.97
                        lines.append(f"    - 最小水面隐蔽: {min_s:.2f} km")
                    elif col == "conceal_air":
                        lines.append(f"    - {disp}: {val:.2f} km")
                        min_a = val * 0.9 * 0.97
                        lines.append(f"    - 最小空中隐蔽: {min_a:.2f} km")
                    elif col == "has_citadel":
                        lines.append(f"    - {disp}: {'是' if val else '否'}")
                    else:
                        u = "kts" if col == "max_speed" else "m" if col == "turning_radius" else "HP" if col == "engine_power" else ""
                        lines.append(f"    - {disp}: {val}{' '+u if u else ''}")
        if lines:
            result[letter] = lines

    def _build_artillery(self, ship_id: str, letter: str, result: dict,
                          ammo_map: dict) -> None:
        conn = self.conn
        lines = []
        for g in conn.execute(
            "SELECT * FROM ship_module_artillery WHERE ship_id=? AND module_letter=? ORDER BY gun_name",
            (ship_id, letter)).fetchall():
            lines.append(f"  - {g['gun_name']} x{g['count']}")
            lines.append(f"    联装数: {g['num_barrels']:.0f}")
            lines.append(f"    装填时间: {g['reload_time']}s")
            if g['max_range']:
                lines.append(f"    最大射程: {g['max_range']:.1f} km")
            if g['dispersion_formula']:
                lines.append(f"    横向散布公式: {g['dispersion_formula']}")
            # 弹鼓/弹夹数据（完全参照旧 ship_analyzer.py 格式）
            drum_shots = g['drum_shots_count'] if g['drum_shots_count'] is not None else 0
            if drum_shots > 0:
                is_chargeable = bool(g['drum_is_chargeable'])
                n_rounds = float(drum_shots)
                shot_delay = g['drum_shot_delay'] or 0
                full_reload = g['drum_full_reload_time'] or 0
                if is_chargeable:
                    header_name = "弹鼓炮"
                    details = [f"连发数量: {n_rounds:.0f}", f"连发间隔: {shot_delay}s"]
                    mode_type = g['drum_charge_mode'] or 0
                    t_min = g['drum_charge_time_min'] or 0
                    t_max = g['drum_charge_time_max'] or 0
                    if mode_type == 1:
                        details.append(f"第 1 轮装填时间: {t_min}s")
                        details.append(f"第 2 ~ {n_rounds:.0f} 轮装填时间: {t_max}s")
                    elif mode_type == 2:
                        details.append(f"第 1 ~ {n_rounds - 1:.0f} 轮装填时间: {t_min}s")
                        details.append(f"第 {n_rounds:.0f} 轮(末轮)装填时间: {t_max}s")
                else:
                    is_switchable = bool(g['drum_is_switchable'])
                    switch_prefix = "可切换" if is_switchable else "强制"
                    header_name = f"{switch_prefix}连发射击-弹夹炮"
                    details = [
                        f"长装填时间: {full_reload}s",
                        f"连发间隔: {shot_delay}s",
                        f"连发轮数: {n_rounds:.0f}"
                    ]
                lines.append(f"  特殊射击模式: {header_name}")
                for d in details:
                    lines.append(f"    - {d}")
            for a in conn.execute(
                "SELECT ra.ammo_id, pbi.* FROM rel_ship_weapon_ammo ra "
                "LEFT JOIN projectile_basic_info pbi ON pbi.projectile_id = ra.ammo_id "
                "JOIN ship_module_artillery sma ON sma.id = ra.weapon_ref_id "
                "WHERE ra.weapon_type='artillery' AND sma.ship_id=? AND sma.module_letter=? AND sma.gun_name=?",
                (ship_id, letter, g['gun_name'])).fetchall():
                acn = ammo_map.get(a["ammo_id"].upper(), a["ammo_id"])
                lines.append(f"    可用弹药: {acn}")
                lines.extend(self._format_projectile_lines(a, ammo_map))
        if lines:
            result[letter] = lines

    def _build_atba(self, ship_id: str, letter: str, result: dict,
                     ammo_map: dict) -> None:
        conn = self.conn
        lines = []
        for g in conn.execute(
            "SELECT * FROM ship_module_atba WHERE ship_id=? AND module_letter=? ORDER BY gun_name",
            (ship_id, letter)).fetchall():
            lines.append(f"  - {g['gun_name']} x{g['count']}")
            lines.append(f"    联装数: {g['num_barrels']:.0f}")
            lines.append(f"    装填时间: {g['reload_time']}s")
            if g['max_range']:
                lines.append(f"    最大射程: {g['max_range']:.1f} km")
            for a in conn.execute(
                "SELECT ra.ammo_id, pbi.* FROM rel_ship_weapon_ammo ra "
                "LEFT JOIN projectile_basic_info pbi ON pbi.projectile_id = ra.ammo_id "
                "JOIN ship_module_atba sma ON sma.id = ra.weapon_ref_id "
                "WHERE ra.weapon_type='atba' AND sma.ship_id=? AND sma.module_letter=? AND sma.gun_name=?",
                (ship_id, letter, g['gun_name'])).fetchall():
                acn = ammo_map.get(a["ammo_id"].upper(), a["ammo_id"])
                lines.append(f"    可用弹药: {acn}")
                lines.extend(self._format_projectile_lines(a, ammo_map))
        if lines:
            result[letter] = lines

    def _build_torpedoes(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        ammo_map = self.get_name_map("ammo")
        for t in conn.execute(
            "SELECT * FROM ship_module_torpedoes WHERE ship_id=? AND module_letter=? ORDER BY launcher_name",
            (ship_id, letter)).fetchall():
            lines.append(f"  - {t['launcher_name']} x{t['count']}")
            lines.append(f"    联装数: {t['num_barrels']:.0f}")
            lines.append(f"    装填时间: {t['reload_time']}s")
            for a in conn.execute(
                "SELECT ra.ammo_id, pbi.* FROM rel_ship_weapon_ammo ra "
                "LEFT JOIN projectile_basic_info pbi ON pbi.projectile_id = ra.ammo_id "
                "JOIN ship_module_torpedoes smt ON smt.id = ra.weapon_ref_id "
                "WHERE ra.weapon_type='torpedo' AND smt.ship_id=? AND smt.module_letter=? AND smt.launcher_name=?",
                (ship_id, letter, t['launcher_name'])).fetchall():
                aname = ammo_map.get(a["ammo_id"].upper(), a["ammo_id"])
                lines.append(f"    鱼雷: {aname}")
                lines.extend(self._format_projectile_lines(a, ammo_map))
        if lines:
            result[letter] = lines

    def _build_aa(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        aa_list = conn.execute(
            "SELECT * FROM ship_module_aa WHERE ship_id=? AND module_letter=?",
            (ship_id, letter)).fetchall()
        aa_auras = [a for a in aa_list if a['aura_name']]
        aa_guns = [a for a in aa_list if a['aa_gun_name']]
        if aa_auras:
            lines.append("  防空光环:")
            # 去重：按 (aura_name, aura_type, aura_dps, bubble_damage) 分组
            aura_groups = {}
            for a in aa_auras:
                key = (a['aura_name'], a['aura_type'], a['aura_dps'], a['bubble_damage'])
                aura_groups[key] = aura_groups.get(key, 0) + (a['aa_gun_count'] or 1)
            for (name, atype, dps, bdmg), cnt in aura_groups.items():
                label = f"{'黑云' if atype=='bubble' else '持续伤害'}"
                entry = f"    - {name} ({label})"
                if cnt > 1:
                    entry += f" x{cnt}"
                lines.append(entry)
                if atype == 'bubble':
                    lines.append(f"      黑云单颗伤害: {bdmg:.1f}")
                else:
                    lines.append(f"      面板秒伤: {dps:.0f}")
        if aa_guns:
            lines.append("  防空炮:")
            # 去重：按 aa_gun_name 分组
            gun_groups = {}
            for g in aa_guns:
                gun_groups[g['aa_gun_name']] = gun_groups.get(g['aa_gun_name'], 0) + (g['aa_gun_count'] or 1)
            for name, cnt in gun_groups.items():
                lines.append(f"    - {name} x{cnt}")
        if lines:
            result[letter] = lines

    def _build_depth_charge(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        dcs = conn.execute(
            "SELECT * FROM ship_module_depth_charge WHERE ship_id=? AND module_letter=?",
            (ship_id, letter)).fetchall()
        if dcs:
            c = Counter(d['gun_name'] for d in dcs)
            lines.append("  深水炸弹:")
            for n, cnt in c.items():
                lines.append(f"    - {n} x{cnt}")
        if lines:
            result[letter] = lines

    def _build_aircraft(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        # 按 module_variant 收集飞机
        by_variant: dict[str, list[dict]] = {}
        for p in conn.execute(
            "SELECT * FROM ship_module_aircraft WHERE ship_id=? AND module_letter=? "
            "ORDER BY module_variant, plane_name",
            (ship_id, letter)).fetchall():
            vk = p['module_variant'] or ''
            by_variant.setdefault(vk, []).append(p)
        if not by_variant:
            return

        # 按 aircraft_class + module_variant 分组，每个变体作为独立 sub_label
        class_order = ["攻击机", "鱼雷轰炸机", "俯冲轰炸机",
                       "弹跳轰炸机", "水雷轰炸机", "侦察机", "其他飞机"]
        variant_labels: dict[str, str] = {}   # sub_label → display name
        variant_lines: dict[str, list[str]] = {}  # sub_label → lines

        for vk in sorted(by_variant.keys(), key=lambda x: (len(x), x)):
            for p in by_variant[vk]:
                pinfo = conn.execute(
                    "SELECT * FROM plane_basic_info WHERE plane_id=?",
                    (self.resolve_plane_id(p['plane_name']),)).fetchone()
                cls_name = (pinfo['aircraft_class'] or "其他飞机") if pinfo else "其他飞机"
                sub_label = f"{cls_name}【{letter}{vk}】" if vk else f"{cls_name}"
                if sub_label not in variant_lines:
                    variant_lines[sub_label] = []
                pl = variant_lines[sub_label]
                pname = self.resolve_plane(p['plane_name'])
                pl.append(f"    - {pname}")
                pinfo = conn.execute(
                    "SELECT * FROM plane_basic_info WHERE plane_id=?",
                    (self.resolve_plane_id(p['plane_name']),)).fetchone()
                if pinfo:
                    cruise = pinfo['cruise_speed']
                    max_s = pinfo['max_speed']
                    min_s = pinfo['min_speed']
                    if cruise: pl.append(f"      巡航速度: {cruise} knot")
                    if max_s is not None:
                        v = cruise * max_s if cruise else max_s
                        pl.append(f"      最大速度: {v:.0f} knot")
                    if min_s is not None:
                        v = cruise * min_s if cruise else min_s
                        pl.append(f"      最小速度: {v:.0f} knot")
                    if pinfo['max_health']: pl.append(f"      生命值: {pinfo['max_health']:.0f}")
                    if pinfo['squadron_size']: pl.append(f"      中队规模: {pinfo['squadron_size']}架")
                    if pinfo['attack_size']: pl.append(f"      攻击编组规模: {pinfo['attack_size']}架")
                    if pinfo['attack_count']: pl.append(f"      飞机载弹数量: {pinfo['attack_count']}")
                    if pinfo['restore_time']: pl.append(f"      整备时间: {pinfo['restore_time']}s")
                    if pinfo['preparation_time']: pl.append(f"      准备时间: {pinfo['preparation_time']}s")
                    if pinfo['aiming_time']: pl.append(f"      瞄准时间: {pinfo['aiming_time']}s")
                # 弹药信息
                armament_ids = (p['armament_name'] or (pinfo and pinfo['armament_name']) or "").split(",")
                armament_names_zh = []
                if pinfo and pinfo['armament_name_zh']:
                    armament_names_zh = pinfo['armament_name_zh'].split(",")
                for i, aid in enumerate(armament_ids):
                    aid = aid.strip()
                    if not aid:
                        continue
                    proj = conn.execute(
                        "SELECT * FROM projectile_basic_info WHERE projectile_id=?",
                        (aid,)).fetchone()
                    if proj:
                        aname = self.resolve_name("ammo", aid) or proj['ammo_name_zh'] or aid
                        pl.append(f"      弹药: {aname}")
                        ammo_map = self.get_name_map("ammo")
                        pl.extend(f"        {l}" for l in self._format_projectile_lines(proj, ammo_map))
                    else:
                        aname = (armament_names_zh[i] if i < len(armament_names_zh) else
                                 self.resolve_name("ammo", aid) or aid)
                        pl.append(f"      弹药: {aname}")
                # 机载消耗品
                for ab in conn.execute(
                    "SELECT * FROM plane_ability_slots WHERE plane_id=? ORDER BY slot_index",
                    (self.resolve_plane_id(p['plane_name']),)).fetchall():
                    ab_name = self.resolve_name("consumable", ab['ability_id'])
                    pl.append(f"      消耗品: {ab_name}")
                    cinfo = conn.execute(
                        "SELECT extra_json FROM consumable_basic_info WHERE consumable_id=?",
                        (ab['ability_id'],)).fetchone()
                    if cinfo and cinfo['extra_json']:
                        try:
                            extra = json.loads(cinfo['extra_json'])
                            config_key = ab['ability_limit'] or 'Default'
                            slot_cfgs = extra.get('_slot_configs', {})
                            cfg = slot_cfgs.get(config_key) or slot_cfgs.get('Default', {})
                            ct = cfg.get('consumableType', '')
                            if ct:
                                pl.extend(self._format_ability_details(cfg, ct))
                        except (json.JSONDecodeError, TypeError):
                            pass

        # 按 class 顺序写入 result，每个 sub_label 是一个独立标签页
        seen = set()
        for sub_label in sorted(variant_lines.keys(),
                                 key=lambda x: (class_order.index(x.split("【")[0]) if x.split("【")[0] in class_order else 999, x)):
            if sub_label not in seen:
                seen.add(sub_label)
                result[sub_label] = variant_lines[sub_label]

    def _build_air_support(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        ammo_map = self.get_name_map("ammo")
        for a in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE ship_id=? AND module_letter=?",
            (ship_id, letter)).fetchall():
            pname = self.resolve_plane(a['plane_name'])
            lines.append(f"  {pname}")
            if a['charges']: lines.append(f"    次数: {a['charges']}")
            if a['reload_time']: lines.append(f"    装填: {a['reload_time']}s")
            if a['armament_name']:
                aname = ammo_map.get(a['armament_name'].upper(), a['armament_name'])
                lines.append(f"    弹药: {aname}")
                proj = conn.execute(
                    "SELECT * FROM projectile_basic_info WHERE projectile_id=?",
                    (a['armament_name'],)).fetchone()
                if proj:
                    lines.extend(self._format_projectile_lines(proj, ammo_map))
        if lines:
            result[letter] = lines

    # ── 弹药通用格式化（按 species 分类型显示）────────────

    @staticmethod
    def _format_projectile_lines(proj, ammo_map: dict) -> list[str]:
        """根据弹种 species 返回格式化弹药详情行列表"""
        import json
        lines = []
        species = (proj['species'] or '').strip()
        ammo_type = (proj['ammo_type'] or '').upper()
        damage = proj['alpha_damage']
        extra = {}
        try:
            extra = json.loads(proj['extra_json'] or '{}')
        except (json.JSONDecodeError, TypeError):
            pass

        if species == "Torpedo":
            lines.append(f"      标伤: {(damage or 0) * 0.33:.0f}")
        elif damage:
            lines.append(f"      标伤: {damage:.0f}")

        # ── Artillery（火炮炮弹）────────────────────────
        if species == "Artillery":
            if proj['bullet_mass']: lines.append(f"      弹重: {proj['bullet_mass']:.0f} kg")
            if proj['bullet_diameter']: lines.append(f"      口径: {proj['bullet_diameter']*1000:.2f} mm")
            if proj['bullet_speed']: lines.append(f"      初速: {proj['bullet_speed']:.0f} m/s")
            if proj['bullet_air_drag']: lines.append(f"      阻力: {proj['bullet_air_drag']}")
            if ammo_type == "AP" and proj['bullet_krupp']:
                lines.append(f"      弹头硬度: {proj['bullet_krupp']:.0f}")
            if ammo_type == "HE":
                if proj['alpha_piercing_he']: lines.append(f"      HE穿深: {proj['alpha_piercing_he']:.1f} mm")
                if proj['burn_prob']: lines.append(f"      起火率: {proj['burn_prob']*100:.1f}%")
                if proj['explosion_radius']: lines.append(f"      爆炸半径: {proj['explosion_radius']/3:.1f} m")
            elif ammo_type == "CS":
                if proj['alpha_piercing_cs']: lines.append(f"      穿深: {proj['alpha_piercing_cs']:.1f} mm")
            if ammo_type in ("AP", "CS"):
                if proj['bullet_always_ricochet_at']: lines.append(f"      强制跳弹角: {proj['bullet_always_ricochet_at']:.0f}°")
                if proj['bullet_ricochet_at']: lines.append(f"      概率跳弹角: {proj['bullet_ricochet_at']:.0f}°")
                if proj['bullet_cap_normalize_max']: lines.append(f"      转正角: {proj['bullet_cap_normalize_max']:.0f}°")
                if ammo_type == "AP":
                    if proj['bullet_detonator']: lines.append(f"      引信: {proj['bullet_detonator']:.0f} s")
                    if proj['bullet_detonator_threshold']: lines.append(f"      引信阈值: {proj['bullet_detonator_threshold']:.0f} mm")

        # ── Bomb（炸弹）────────────────────────────────
        elif species == "Bomb":
            if proj['bullet_mass']: lines.append(f"      弹重: {proj['bullet_mass']:.0f} kg")
            if proj['bullet_speed']: lines.append(f"      投弹速: {proj['bullet_speed']:.0f} m/s")
            if ammo_type == "HE":
                if proj['alpha_piercing_he']: lines.append(f"      HE穿深: {proj['alpha_piercing_he']:.1f} mm")
                if proj['burn_prob']: lines.append(f"      起火率: {proj['burn_prob']*100:.1f}%")
            elif ammo_type == "CS":
                if proj['alpha_piercing_cs']: lines.append(f"      穿深: {proj['alpha_piercing_cs']:.1f} mm")
            elif ammo_type == "AP":
                if proj['bullet_krupp']: lines.append(f"      硬度: {proj['bullet_krupp']:.0f}")
            if proj['explosion_radius']: lines.append(f"      爆炸半径: {proj['explosion_radius']/3:.1f} m")
            if ammo_type in ("AP", "CS"):
                if proj['bullet_always_ricochet_at']: lines.append(f"      强制跳弹角: {proj['bullet_always_ricochet_at']:.0f}°")
                if proj['bullet_ricochet_at']: lines.append(f"      概率跳弹角: {proj['bullet_ricochet_at']:.0f}°")
                if ammo_type == "AP":
                    if proj['bullet_detonator']: lines.append(f"      引信: {proj['bullet_detonator']:.0f} s")
                    if proj['bullet_detonator_threshold']: lines.append(f"      引信阈值: {proj['bullet_detonator_threshold']:.0f} mm")

        # ── Rocket（火箭弹）────────────────────────────
        elif species == "Rocket":
            if proj['bullet_mass']: lines.append(f"      弹重: {proj['bullet_mass']:.0f} kg")
            if proj['bullet_speed']: lines.append(f"      初速: {proj['bullet_speed']:.0f} m/s")
            if ammo_type == "HE":
                if proj['alpha_piercing_he']: lines.append(f"      HE穿深: {proj['alpha_piercing_he']:.1f} mm")
                if proj['burn_prob']: lines.append(f"      起火率: {proj['burn_prob']*100:.1f}%")
            elif ammo_type == "CS":
                if proj['alpha_piercing_cs']: lines.append(f"      穿深: {proj['alpha_piercing_cs']:.1f} mm")
            elif ammo_type == "AP":
                if proj['bullet_krupp']: lines.append(f"      硬度: {proj['bullet_krupp']:.0f}")
            if proj['explosion_radius']: lines.append(f"      爆炸半径: {proj['explosion_radius']/3:.1f} m")

        # ── Torpedo（鱼雷）─────────────────────────────
        elif species == "Torpedo":
            t_type = proj['torpedo_type']
            postfix = (proj['custom_ui_postfix'] or '').strip()
            if t_type == 1: dtype = "声导"
            elif proj['is_deep_water']: dtype = "深水"
            elif postfix == "_subBurn": dtype = "热能"
            else: dtype = "鱼雷"
            if proj['torpedo_speed']: lines.append(f"      航速: {proj['torpedo_speed']:.0f} kts")
            max_dist = proj['torpedo_max_dist']
            if max_dist: lines.append(f"      射程: {max_dist*30/1000:.1f} km")
            if proj['torpedo_visibility']: lines.append(f"      发现: {proj['torpedo_visibility']:.1f} km")
            if proj['torpedo_arming_time']: lines.append(f"      引信: {proj['torpedo_arming_time']:.0f}s")
            if proj['torpedo_uw_critical']: lines.append(f"      漏水: {proj['torpedo_uw_critical']*100:.0f}%")
            if t_type == 1:
                stp = extra.get("submarineTorpedoParams", {})
                if stp:
                    my = stp.get("maxYaw", [0])[0] if isinstance(stp.get("maxYaw"), list) else stp.get("maxYaw", 0)
                    ys = stp.get("yawChangeSpeed", [0])[0] if isinstance(stp.get("yawChangeSpeed"), list) else stp.get("yawChangeSpeed", 0)
                    lines.append(f"      转向: {my}° / {ys}°/s")

        # ── DepthCharge（深水炸弹）──────────────────────
        elif species == "DepthCharge":
            if proj['bullet_speed']: lines.append(f"      下潜: {proj['bullet_speed']:.0f} m/s")
            if proj['dc_timer']: lines.append(f"      延迟: {proj['dc_timer']:.0f}s")
            if proj['dc_max_depth']: lines.append(f"      深度: {abs(proj['dc_max_depth']):.0f} m")

        # ── Laser（激光）───────────────────────────────
        elif species == "Laser":
            if proj['bullet_speed']: lines.append(f"      速度: {proj['bullet_speed']:.0f} m/s")
            if proj['laser_heat']: lines.append(f"      热量: {proj['laser_heat']}")
            if proj['laser_heat_radius']: lines.append(f"      热半径: {proj['laser_heat_radius']} m")

        # ── Wave（波浪）────────────────────────────────
        elif species == "Wave":
            if proj['wave_speed']: lines.append(f"      波速: {proj['wave_speed']:.0f} m/s")
            if proj['wave_sector']: lines.append(f"      扇区: {proj['wave_sector']}°")

        return lines

    @staticmethod
    def _format_ability_details(cfg: dict, ct: str) -> list[str]:
        """根据消耗品类型返回格式化详情行列表"""
        from models.name_mapping import Mapping as NM
        lines = []
        num = cfg.get('numConsumables', 0)
        num_str = "无限" if num == -1 else str(num)
        lines.append(f"        数量: {num_str}")
        work = cfg.get('workTime', 0)
        prep = cfg.get('preparationTime', 0)
        reload_t = cfg.get('reloadTime', 0)
        if prep: lines.append(f"        准备时间: {prep}s")
        if work: lines.append(f"        作用时间: {work}s")
        if reload_t: lines.append(f"        装填时间: {reload_t}s")

        if ct == "fighter" or ct == "callFighters":
            fn = cfg.get('fightersName', '')
            if fn:
                lines.append(f"        机型: {fn}")
            fn2 = cfg.get('fighterNum', 0)
            if fn2:
                lines.append(f"        数量: {fn2} 架")
            dog = cfg.get('dogFightTime', 0)
            fly = cfg.get('flyAwayTime', 0)
            if dog or fly:
                lines.append(f"        狗斗:{dog}s / 离开:{fly}s")
            rk = cfg.get('distanceToKill', 0)
            if rk:
                lines.append(f"        巡逻半径: {rk/10:.1f}km")

        elif ct == "scout":
            dc = (cfg.get('artilleryDistCoeff') or 1) - 1
            lines.append(f"        主炮射程: {dc*100:+.0f}%")

        elif ct == "smokeGenerator":
            r = cfg.get('radius', 0)
            h = cfg.get('height', 0)
            lines.append(f"        烟雾半径: {r*3:.0f}m | 高度: {h}m")
            sp = cfg.get('speedLimit', 0)
            lt = cfg.get('lifeTime', 0)
            if sp or lt:
                lines.append(f"        限速: {sp}kts | 扩散: {lt}s")

        elif ct == "speedBoosters":
            bc = (cfg.get('boostCoeff') or 1) - 1
            lines.append(f"        最高航速: {bc*100:+.0f}%")
            fe = (cfg.get('forwardEngineForsag') or 1) - 1
            be = (cfg.get('backwardEngineForsag') or 1) - 1
            lines.append(f"        推力: 前进{fe*100:+.0f}% / 后退{be*100:+.0f}%")

        elif ct == "sonar":
            ds = (cfg.get('distShip') or 0) * 0.03
            dt = (cfg.get('distTorpedo') or 0) * 0.03
            lines.append(f"        舰船探测: {ds:.2f} km")
            lines.append(f"        鱼雷探测: {dt:.2f} km")

        elif ct == "regenerateHealth":
            rate = cfg.get('regenerationRate', 0)
            if rate:
                lines.append(f"        每秒回复: {rate*100:.1f}%")

        elif ct == "depthCharges":
            r = cfg.get('radius', 0) * 0.003
            lines.append(f"        半径: {r:.2f}km")

        elif ct == "hydrophone":
            zt = cfg.get('zoneLifeTime', 0)
            hu = cfg.get('hydrophoneUpdateFrequency', 0)
            wr = (cfg.get('hydrophoneWaveRadius') or 0) * 0.001
            if zt or hu:
                lines.append(f"        虚影:{zt}s / 刷新:{hu}s")
            if wr:
                lines.append(f"        视野: {wr:.2f}km")

        elif ct == "submarineLocator":
            ds = (cfg.get('distShip') or 0) * 0.03
            lines.append(f"        舰船探测: {ds:.2f} km")

        elif ct == "airDefenseDisp":
            ad = (cfg.get('areaDamageMultiplier') or 1) - 1
            bd = (cfg.get('bubbleDamageMultiplier') or 1) - 1
            lines.append(f"        区域秒伤: {ad*100:+.0f}%")
            lines.append(f"        黑云伤害: {bd*100:+.0f}%")

        elif ct == "planeSmokeGenerator":
            ad = cfg.get('activationDelay', 0)
            r = cfg.get('radius', 0) * 3
            if ad:
                lines.append(f"        延迟: {ad}s")
            if r:
                lines.append(f"        烟雾半径: {r:.0f}m")

        elif ct == "vampireDamage":
            coeff = (cfg.get('modifiers') or {}).get('damageGMHealCoeff', 0) * 100
            lines.append(f"        伤害转化: {coeff:.1f}%")

        elif ct == "massHeal":
            hp = (cfg.get('ownHealPart') or 0) * 100
            lines.append(f"        回复: {hp:.1f}%/s")
            radius = (cfg.get('workRadius') or 0) * 3 / 100
            lines.append(f"        半径: {radius:.2f}km")

        elif ct == "supportBuoy":
            lines.append(f"        区域: {cfg.get('battleDropVisualName', '未知')}")
            lines.append(f"        布置: {cfg.get('battleDropActivationTime', 0)}s")
            lines.append(f"        持续: {cfg.get('zoneLifetime', 0)}s")

        return lines
