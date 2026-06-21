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
            self.make_item(f"  编号: {basic['ship_index'] or ship_id}", "", 1),
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
                for k, v in [("num_consumables", "数量"), ("preparation_time", "准备时间"),
                              ("work_time", "作用时间"), ("reload_time", "装填时间")]:
                    val = s[k]
                    if val:
                        items.append(self.make_item(
                            f"      {v}: {val}{'s' if k.endswith('_time') else ''}", "", len(items)))
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
            for a in conn.execute(
                "SELECT ra.ammo_id, pbi.alpha_damage, pbi.bullet_speed, pbi.bullet_krupp, "
                "pbi.alpha_piercing_he, pbi.burn_prob, pbi.ammo_type, pbi.explosion_radius "
                "FROM rel_ship_weapon_ammo ra "
                "LEFT JOIN projectile_basic_info pbi ON pbi.projectile_id = ra.ammo_id "
                "JOIN ship_module_artillery sma ON sma.id = ra.weapon_ref_id "
                "WHERE ra.weapon_type='artillery' AND sma.ship_id=? AND sma.module_letter=? AND sma.gun_name=?",
                (ship_id, letter, g['gun_name'])).fetchall():
                acn = ammo_map.get(a["ammo_id"].upper(), a["ammo_id"])
                lines.append(f"    可用弹药: {acn} ({a['ammo_type'] or ''})")
                if a["alpha_damage"]:
                    lines.append(f"      标伤: {a['alpha_damage']:.0f}")
                if a["bullet_speed"]:
                    lines.append(f"      弹速: {a['bullet_speed']:.0f} m/s")
                if a["bullet_krupp"]:
                    lines.append(f"      穿甲系数: {a['bullet_krupp']:.0f}")
                if a["alpha_piercing_he"]:
                    lines.append(f"      HE穿深: {a['alpha_piercing_he']:.0f} mm")
                if a["explosion_radius"]:
                    lines.append(f"      爆炸半径: {a['explosion_radius']:.1f} m")
                at = (a['ammo_type'] or '').upper()
                if a["burn_prob"] and at in ('HE', 'HE_IGNORE'):
                    lines.append(f"      起火率: {a['burn_prob']*100:.1f}%")
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
                "SELECT ra.ammo_id, pbi.alpha_damage, pbi.bullet_speed, pbi.bullet_krupp, "
                "pbi.alpha_piercing_he, pbi.burn_prob, pbi.ammo_type, pbi.explosion_radius "
                "FROM rel_ship_weapon_ammo ra "
                "LEFT JOIN projectile_basic_info pbi ON pbi.projectile_id = ra.ammo_id "
                "JOIN ship_module_atba sma ON sma.id = ra.weapon_ref_id "
                "WHERE ra.weapon_type='atba' AND sma.ship_id=? AND sma.module_letter=? AND sma.gun_name=?",
                (ship_id, letter, g['gun_name'])).fetchall():
                acn = ammo_map.get(a["ammo_id"].upper(), a["ammo_id"])
                lines.append(f"    可用弹药: {acn} ({a['ammo_type'] or ''})")
                if a["alpha_damage"]:
                    lines.append(f"      标伤: {a['alpha_damage']:.0f}")
                if a["bullet_speed"]:
                    lines.append(f"      弹速: {a['bullet_speed']:.0f} m/s")
                at = (a['ammo_type'] or '').upper()
                if a["burn_prob"] and at in ('HE', 'HE_IGNORE'):
                    lines.append(f"      起火率: {a['burn_prob']*100:.1f}%")
        if lines:
            result[letter] = lines

    def _build_torpedoes(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        for t in conn.execute(
            "SELECT * FROM ship_module_torpedoes WHERE ship_id=? AND module_letter=? ORDER BY launcher_name",
            (ship_id, letter)).fetchall():
            lines.append(f"  - {t['launcher_name']} x{t['count']}")
            lines.append(f"    联装数: {t['num_barrels']:.0f}")
            lines.append(f"    装填时间: {t['reload_time']}s")
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
            for a in aa_auras:
                lines.append(
                    f"    - {a['aura_name']} ({'黑云' if a['aura_type']=='bubble' else '持续伤害'})")
                if a['aura_dps']:
                    lines.append(f"      面板秒伤: {a['aura_dps']:.0f}")
        if aa_guns:
            c = Counter(a['aa_gun_name'] for a in aa_guns)
            lines.append("  防空炮:")
            for n, cnt in c.items():
                lines.append(f"    - {n} x{cnt}")
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

        # 先按 aircraft_class 分组, 再按 variant 分组
        # class_order → 各类显示顺序
        from collections import OrderedDict
        class_order = ["战斗机", "鱼雷轰炸机", "俯冲轰炸机",
                       "弹跳轰炸机", "水雷轰炸机", "侦察机", "其他飞机"]
        class_data: dict[str, dict[str, list[dict]]] = {}  # class → variant → [planes]

        for vk, grp in by_variant.items():
            for p in grp:
                pinfo = conn.execute(
                    "SELECT * FROM plane_basic_info WHERE plane_id=?",
                    (self.resolve_plane_id(p['plane_name']),)).fetchone()
                cls_name = (pinfo['aircraft_class'] or "其他飞机") if pinfo else "其他飞机"
                if cls_name not in class_data:
                    class_data[cls_name] = {}
                class_data[cls_name].setdefault(vk, []).append(p)

        # 构建子标签页面
        for cls_name in sorted(class_data.keys(),
                                key=lambda c: class_order.index(c) if c in class_order else 999):
            variants = class_data[cls_name]
            if cls_name not in result:
                result[cls_name] = []
            pl = result[cls_name]
            pl.append(f"  [{cls_name}]")
            for vk in sorted(variants.keys(), key=lambda x: (len(x), x)):
                pl.append(f"    --- {letter}{vk} ---")
                for p in variants[vk]:
                    pname = self.resolve_plane(p['plane_name'])
                    pl.append(f"    - {pname}")
                    pinfo = conn.execute(
                        "SELECT * FROM plane_basic_info WHERE plane_id=?",
                        (self.resolve_plane_id(p['plane_name']),)).fetchone()
                    if pinfo:
                        if pinfo['cruise_speed']: pl.append(f"      巡航速度: {pinfo['cruise_speed']} knot")
                        if pinfo['max_health']: pl.append(f"      生命值: {pinfo['max_health']:.0f}")
                        if pinfo['squadron_size']: pl.append(f"      中队规模: {pinfo['squadron_size']}")
                        if pinfo['attack_size']: pl.append(f"      攻击组规模: {pinfo['attack_size']}")
                        if pinfo['attack_count']: pl.append(f"      攻击组数量: {pinfo['attack_count']}")
                        if pinfo['restore_time']: pl.append(f"      整备时间: {pinfo['restore_time']}s")
                        if pinfo['preparation_time']: pl.append(f"      准备时间: {pinfo['preparation_time']}s")
                        if pinfo['aiming_time']: pl.append(f"      瞄准时间: {pinfo['aiming_time']}s")

    def _build_air_support(self, ship_id: str, letter: str, result: dict) -> None:
        conn = self.conn
        lines = []
        for a in conn.execute(
            "SELECT * FROM ship_module_air_support WHERE ship_id=? AND module_letter=?",
            (ship_id, letter)).fetchall():
            lines.append(f"  {a['plane_name']}")
            if a['charges']: lines.append(f"    次数: {a['charges']}")
            if a['reload_time']: lines.append(f"    装填: {a['reload_time']}s")
        if lines:
            result[letter] = lines
