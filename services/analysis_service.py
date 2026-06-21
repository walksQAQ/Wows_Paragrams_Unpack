"""
预分析服务 —— 将原始 JSON 数据深度解析后写入结构化数据库表。

用法:
    svc = AnalysisService()
    svc.precompute_all(db, progress_callback=...)

无需 analyzers 包，直接从 split JSON 读取数据并通过 AnalysisStore 写入。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Callable, Optional

from services.database_service import DatabaseManager
from utils.path_utils import get_split_dir
from app.signals import bus


# ── 分析结果 → 数据库写入器 ─────────────────────────────

class AnalysisStore:
    """将原始 JSON 数据深度解析后写入结构化数据库表"""

    # 舰船模块匹配模式 (与 ship_analyzer 同步)
    PATTERNS = {
        "Hull": re.compile(r'([A-Z]+\d*)_Hull'),
        "Artillery": re.compile(r'([A-Z]+\d*)_Artillery'),
        "ATBA": re.compile(r'([A-Z]+\d*)_ATBA'),
        "Torpedoes": re.compile(r'([A-Z]+\d*)_Torpedoes'),
        "DiveBomber": re.compile(r'([A-Z]+\d*)_DiveBomber'),
        "Fighter": re.compile(r'([A-Z]+\d*)_Fighter'),
        "SkipBomber": re.compile(r'([A-Z]+\d*)_SkipBomber'),
        "TorpedoBomber": re.compile(r'([A-Z]+\d*)_TorpedoBomber'),
        "AirSupport": re.compile(r'([A-Z]+\d*)_AirSupport'),
        "AirDefense": re.compile(r'([A-Z]+\d*)_AirDefense'),
        "DepthChargeGuns": re.compile(r"([A-Z]+\d*)_DepthChargeGuns"),
        "AirArmament": re.compile(r'([A-Z]+\d*)_AirArmament'),
        "FlightControl": re.compile(r'([A-Z]+\d*)_FlightControl'),
    }
    HP_PATTERNS = {
        "Artillery": re.compile(r'HP_[A-Z]GM_\d+'),
        "ATBA": re.compile(r'HP_([A-Z]GS)_\d+'),
        "AirDefense": re.compile(r'(HP_[A-Z]GA_\d+|HP_[A-Z]GM_\d+_HP_[A-Z]GA_\d+|Aura_\d+|(Far|Medium|Near)\d*(_Bubbles)?)'),
        "Torpedoes": re.compile(r'HP_[A-Z]GT_\d+'),
        "DepthChargeGuns": re.compile(r"HP_[A-Z]GB_\d+"),
    }

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.conn = db._conn

    def store_ship(self, ship_id: str, raw_data: dict, result) -> None:
        """将舰船完整数据写入所有 ship_* 结构化表"""
        conn = self.conn

        # ── 基础属性 ──
        self._write_basic_info(ship_id, raw_data, result)

        # ── 消耗品 ──
        self._write_consumables(ship_id, raw_data)

        # ── 战斗指令 ──
        self._write_rage_mode(ship_id, raw_data)

        # ── 模块数据 (船体/武器/飞机) ──
        sub_sections = self._detect_sub_sections(raw_data)
        self._write_modules(ship_id, raw_data)

        # ── 模块字母汇总（含 source_key：原始 JSON key 如 A_Artillery）──
        for label, sinfo in sub_sections.items():
            m = re.match(r'^([A-Z])\s*模块$', label)
            if m:
                for order, sub in enumerate(sinfo.get("sub_labels", [])):
                    sk = sinfo.get("source_keys", {}).get(sub, "")
                    conn.execute(
                        "INSERT OR REPLACE INTO ship_module_mapping "
                        "(ship_id, module_letter, sub_category, source_key, display_order) VALUES (?,?,?,?,?)",
                        (ship_id, m.group(1), sub, sk, order))
        conn.commit()

    @staticmethod
    def _detect_sub_sections(raw_data: dict) -> dict[str, dict]:
        """从原始 JSON 中检测存在的模块字母及其子类别，构建 sub_sections 结构。
        
        返回 { "A 模块": {"sub_labels": ["船体","主炮",...], "source_keys": {"船体": "A_Hull"}}, ... }
        """
        sub_sections: dict[str, dict] = {}
        # 英文分类 → 中文名 + 原始 JSON key
        CAT_ZH_MAP = {
            "Hull": ("船体", "{letter}_Hull"),
            "Artillery": ("主炮", "{letter}_Artillery"),
            "ATBA": ("副炮", "{letter}_ATBA"),
            "Torpedoes": ("鱼雷", "{letter}_Torpedoes"),
            "DiveBomber": ("舰载机", "{letter}_DiveBomber"),
            "Fighter": ("舰载机", "{letter}_Fighter"),
            "SkipBomber": ("舰载机", "{letter}_SkipBomber"),
            "TorpedoBomber": ("舰载机", "{letter}_TorpedoBomber"),
            "AirSupport": ("空袭", "{letter}_AirSupport"),
            "AirDefense": ("防空", "{letter}_AirDefense"),
            "DepthChargeGuns": ("深水炸弹", "{letter}_DepthChargeGuns"),
            "AirArmament": ("舰载机", "{letter}_AirArmament"),
            "FlightControl": ("舰载机", "{letter}_FlightControl"),
        }
        has_pure_b = any(k.startswith("B_") for k in raw_data if isinstance(raw_data.get(k), dict))

        for mod_key in raw_data:
            if not isinstance(raw_data[mod_key], dict):
                continue
            for cat, pattern in AnalysisStore.PATTERNS.items():
                m = pattern.match(mod_key)
                if m:
                    prefix = "".join(re.findall(r'[A-Z]+', m.group(1)))
                    if prefix == "AB":
                        letters = ["A", "B"] if has_pure_b else ["A"]
                    else:
                        letters = list(prefix)

                    cat_zh, key_template = CAT_ZH_MAP.get(cat, (cat, ""))

                    for letter in letters:
                        label = f"{letter} 模块"
                        if label not in sub_sections:
                            sub_sections[label] = {"sub_labels": [], "source_keys": {}}
                        if cat_zh not in sub_sections[label]["sub_labels"]:
                            sub_sections[label]["sub_labels"].append(cat_zh)
                            if key_template:
                                sub_sections[label]["source_keys"][cat_zh] = key_template.format(letter=letter)
                    break

        return sub_sections

    # ── 基础信息 ──────────────────────────────────────────

    def _write_basic_info(self, ship_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        from models.name_mapping import Mapping as NM
        ti = raw_data.get("typeinfo", {}) or {}
        raw_species = ti.get("species", "")
        raw_level = raw_data.get("level", 0)
        if isinstance(raw_level, dict):
            raw_level = 0
        # 解析 section 中的名称
        ship_name_zh = result.title or ""
        ship_index = raw_data.get("index", "") or ""
        # 兼容旧格式：从 entity_id 提取下划线前的部分
        if not ship_index and "_" in ship_id:
            ship_index = ship_id.split("_", 1)[0]

        # 原型舰船名称
        raw_parent = str(raw_data.get("parentShip", "") or "").strip()
        raw_origin = str(raw_data.get("originShipName", "") or "").strip()
        parent_name = ""
        origin_name = ""
        if raw_parent or raw_origin:
            try:
                mappings = self.db.get_all_name_mappings("ship") if self.db.exists else {}
            except Exception:
                mappings = {}
            if raw_parent:
                pkey = raw_parent.replace("IDS_", "").upper().split("_")[0]
                parent_name = mappings.get(pkey, raw_parent)
            if raw_origin:
                okey = raw_origin.replace("IDS_", "").upper().split("_")[0]
                origin_name = mappings.get(okey, raw_origin)

        conn.execute("""INSERT OR REPLACE INTO ship_basic_info
            (ship_id, ship_name_zh, ship_index, ship_id_num,
             nation_zh, shiptype_zh, tier_display, group_status,
             parent_ship_name, origin_ship_name)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (ship_id, ship_name_zh, ship_index,
             int(raw_data.get("id", 0) or 0),
             NM.NATION_MAP.get(str(ti.get("nation", "")), str(ti.get("nation", ""))),
             NM.SHIP_CLASS_MAP.get(raw_species, raw_species),
             str(raw_level),
             NM.SHIP_GROUP_MAP.get(str(raw_data.get("group", "")), str(raw_data.get("group", ""))),
             parent_name or None, origin_name or None))

    # ── 消耗品（参照 archived ship_analyzer.py 逻辑）────

    def _load_ability_config(self, file_key: str, config_key: str) -> dict:
        """从 consumable_basic_info.extra_json 中加载指定 config_key 的子配置"""
        import json
        row = self.conn.execute(
            "SELECT extra_json FROM consumable_basic_info WHERE consumable_id=?",
            (file_key,)).fetchone()
        if not row:
            return {}
        try:
            extra = json.loads(row['extra_json'] or '{}')
            slot_configs = extra.get('_slot_configs', {})
            # 先精确匹配 config_key，再回退 Default
            return slot_configs.get(config_key) or slot_configs.get("Default", {})
        except (json.JSONDecodeError, TypeError):
            return {}

    def _write_consumables(self, ship_id: str, raw_data: dict) -> None:
        conn = self.conn
        abilities = raw_data.get("ShipAbilities", {})
        # 缓存消耗品显示名
        name_map = self.db.get_all_name_mappings("consumable") if self.db.exists else {}
        for slot_key in sorted(abilities.keys()):
            slot_data = abilities[slot_key]
            slot_idx = 1
            m = re.search(r'\d+', slot_key)
            if m:
                slot_idx = int(m.group()) + 1
            abils = slot_data.get("abils", [])
            for i, abil_pair in enumerate(abils):
                if not (isinstance(abil_pair, list) and len(abil_pair) >= 2):
                    continue
                file_key = str(abil_pair[0]).strip()
                # abil_pair[1] 是配置文件中的 key（如 "Default"），参照 archived ship_analyzer
                config_key = str(abil_pair[1]).strip()
                cfg = self._load_ability_config(file_key, config_key)
                if not cfg:
                    # 保底：写入一条只有 ID 的记录
                    conn.execute("""INSERT OR REPLACE INTO ship_consumable_slots
                        (ship_id, slot_index, item_index, display_name, type,
                         num_consumables, preparation_time, work_time, reload_time,
                         is_auto_consumable)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (ship_id, slot_idx, i + 1, name_map.get(file_key.upper(), file_key),
                         None, '0', 0, 0, 0, 0))
                    continue

                display_name = name_map.get(file_key.upper(), file_key)
                num_raw = cfg.get("numConsumables", 0)
                if num_raw == -1:
                    num_str = '-1'
                elif isinstance(num_raw, float):
                    num_str = str(int(num_raw)) if num_raw == int(num_raw) else str(num_raw)
                else:
                    num_str = str(num_raw)
                conn.execute("""INSERT OR REPLACE INTO ship_consumable_slots
                    (ship_id, slot_index, item_index, display_name, type,
                     num_consumables, preparation_time, work_time, reload_time,
                     is_auto_consumable)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (ship_id, slot_idx, i + 1, display_name,
                     cfg.get("consumableType"),
                     num_str,
                     cfg.get("preparationTime", 0),
                     cfg.get("workTime", 0),
                     cfg.get("reloadTime", 0),
                     1 if cfg.get("isAutoConsumable") else 0))

    # ── 战斗指令 ──────────────────────────────────────────

    def _write_rage_mode(self, ship_id: str, raw_data: dict) -> None:
        import json
        conn = self.conn
        rage = raw_data.get("A_Specials", {}).get("RageMode", {})
        if not rage:
            return

        # 本地化显示名称
        raw_name = str(rage.get("rageModeName", ""))
        base_msgid = f"IDS_DOCK_RAGE_MODE_TITLE_{raw_name.upper()}" if raw_name else ""
        rage_map = self.db.get_all_name_mappings("rage_mode")
        display_name = rage_map.get(base_msgid, raw_name)

        # 收集所有 trigger 对象
        triggers = []
        for key in sorted(rage.keys()):
            if "Trigger" in key and isinstance(rage[key], dict):
                triggers.append({key: rage[key]})

        conn.execute("""INSERT OR REPLACE INTO ship_rage_mode
            (ship_id, display_name, boost_duration, max_activation_count,
             is_auto_usage, is_modifier_works_always,
             decrement_delay, decrement_period, decrement_count,
             description_ids, modifiers_json, triggers_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ship_id,
             display_name,
             rage.get("boostDuration", 0),
             str(rage.get("maxActivationCount", 0)),
             1 if rage.get("isAutoUsage") else 0,
             1 if rage.get("isModifierWorksAlways") else 0,
             rage.get("decrementDelay", 0),
             rage.get("decrementPeriod", 0),
             rage.get("decrementCount", 0),
             str(rage.get("descriptionIDS", "")),
             json.dumps(rage.get("modifiers", {}), ensure_ascii=False),
             json.dumps(triggers, ensure_ascii=False)))

    # ── 模块数据（核心）───────────────────────────────────

    def _write_modules(self, ship_id: str, raw_data: dict) -> None:
        """解析原始 JSON 中的模块数据并写入各结构化表"""
        conn = self.conn
        has_pure_b = any(k.startswith("B_") for k in raw_data if isinstance(raw_data.get(k), dict))
        combined_stats: dict[str, dict] = {}  # letter → {cat: [...]}
        drum_configs: dict[str, dict] = {}

        for mod_key, module_data in raw_data.items():
            if not isinstance(module_data, dict):
                continue
            target_letters = []
            current_cat = None

            for cat, pattern in self.PATTERNS.items():
                m = pattern.match(mod_key)
                if m:
                    prefix = "".join(re.findall(r'[A-Z]+', m.group(1)))
                    if prefix == "AB":
                        target_letters = ["A", "B"] if has_pure_b else ["A"]
                    else:
                        target_letters = list(prefix)
                    current_cat = cat
                    break

            if not target_letters:
                continue

            for lt in target_letters:
                if lt not in combined_stats:
                    combined_stats[lt] = {}

            # 提取舰载机，保留 module_variant（如 A1/A2 中的 "1"/"2"）
            if current_cat in ("DiveBomber", "TorpedoBomber", "Fighter", "SkipBomber"):
                m2 = re.match(r'([A-Z]+)(\d*)', m.group(1)) if m else None
                variant = m2.group(2) if m2 and m2.group(2) else ""
                planes = module_data.get("planes", [])
                for pl in planes:
                    if isinstance(pl, dict):
                        pname = pl.get("name", "")
                        arm = pl.get("armamentName", "")
                    elif isinstance(pl, str):
                        pname = pl
                        arm = module_data.get("armamentName", "")
                    else:
                        continue
                    for lt in target_letters:
                        combined_stats[lt].setdefault("aircraft", []).append({
                            "plane_name": pname,
                            "armament_name": arm,
                            "module_variant": variant,
                        })
                continue

            # 提取空袭
            if current_cat == "AirSupport":
                for lt in target_letters:
                    combined_stats[lt].setdefault("air_support", [])
                def _extract_as(d, lt, cs):
                    for k, v in d.items():
                        if isinstance(v, dict) and "Armament" in k:
                            plane_id = v.get("planeName", "")
                            armament = self._find_plane_armament(plane_id)
                            cs.setdefault("air_support", []).append({
                                "plane_name": plane_id,
                                "charges": v.get("chargesNum", 0),
                                "reload_time": v.get("reloadTime", 0),
                                "work_time": v.get("workTime", 0),
                                "max_range": v.get("maxDist", 0) / 1000 if v.get("maxDist") else None,
                                "min_range": v.get("minDist", 0) / 1000 if v.get("minDist") else None,
                                "armament_name": armament,
                            })
                for lt in target_letters:
                    cs = combined_stats[lt]
                    _extract_as(module_data, lt, cs)
                continue

            # 提取空 Armament / FlightControl
            if current_cat == "AirArmament":
                for lt in target_letters:
                    combined_stats[lt]["hangar"] = module_data
                continue
            if current_cat == "FlightControl":
                for lt in target_letters:
                    combined_stats[lt]["flight_control"] = module_data
                continue

            # 武器模块提取
            if current_cat in ("Artillery", "ATBA", "AirDefense", "Torpedoes", "DepthChargeGuns"):
                for sk, sv in module_data.items():
                    if not isinstance(sv, dict):
                        continue
                    # 光环
                    if any(kw in sk for kw in ("Aura", "Far", "Medium", "Near")):
                        for lt in target_letters:
                            cs = combined_stats[lt]
                            is_bubble = "_Bubbles" in sk
                            area_dmg = sv.get("areaDamage", 0)
                            area_period = sv.get("areaDamagePeriod", 1)
                            dps = area_dmg / area_period if area_period else 0
                            bub_dmg = sv.get("bubbleDamage", 0) * 2 / area_period if (is_bubble and area_period) else 0
                            cs.setdefault("aa", []).append({
                                "aura_name": sv.get("name", sk),
                                "aura_type": "bubble" if is_bubble else "continuous",
                                "aura_dps": round(dps, 1),
                                "bubble_damage": round(bub_dmg, 1),
                                "aa_gun_name": None, "aa_gun_count": None,
                            })
                        continue

                    # HP 模块
                    hp_cats = [current_cat]
                    if current_cat in ("Artillery", "ATBA"):
                        hp_cats.append("AirDefense")
                    for hp_cat in hp_cats:
                        hp_pat = self.HP_PATTERNS.get(hp_cat)
                        if not hp_pat or not hp_pat.match(sk):
                            continue
                        gun_name = sv.get("name", sk)
                        barrels = sv.get("numBarrels", 0)
                        reload_t = sv.get("shotDelay", 0)
                        caliber = sv.get("caliber", 0)
                        for lt in target_letters:
                            cs = combined_stats[lt]
                            if hp_cat == "Artillery":
                                ideal_r = sv.get("idealRadius", 0)
                                min_r = sv.get("minRadius", 0)
                                ideal_d = sv.get("idealDistance", 0)
                                cs.setdefault("artillery", []).append({
                                    "gun_name": gun_name, "count": 1, "num_barrels": barrels,
                                    "reload_time": reload_t, "caliber": caliber,
                                    "ideal_radius": ideal_r, "min_radius": min_r,
                                    "ideal_distance": ideal_d,
                                    "radius_zero": sv.get("radiusOnZero", 0),
                                    "radius_delim": sv.get("radiusOnDelim", 0),
                                    "radius_max": sv.get("radiusOnMax", 0),
                                    "delim": sv.get("delim", 0),
                                    "ammo_list": sv.get("ammoList", []),
                                })
                            elif hp_cat == "ATBA":
                                ideal_r = sv.get("idealRadius", 0)
                                min_r = sv.get("minRadius", 0)
                                ideal_d = sv.get("idealDistance", 0)
                                cs.setdefault("atba", []).append({
                                    "gun_name": gun_name, "count": 1, "num_barrels": barrels,
                                    "reload_time": reload_t, "caliber": caliber,
                                    "ideal_radius": ideal_r, "min_radius": min_r,
                                    "ideal_distance": ideal_d,
                                    "radius_zero": sv.get("radiusOnZero", 0),
                                    "radius_delim": sv.get("radiusOnDelim", 0),
                                    "radius_max": sv.get("radiusOnMax", 0),
                                    "delim": sv.get("delim", 0),
                                    "ammo_list": sv.get("ammoList", []),
                                })
                            elif hp_cat == "Torpedoes":
                                cs.setdefault("torpedoes", []).append({
                                    "launcher_name": gun_name, "count": 1,
                                    "num_barrels": barrels, "reload_time": reload_t,
                                    "ammo_list": sv.get("ammoList", []),
                                })
                            elif hp_cat == "AirDefense":
                                if not re.match(r'^(Medium|Near|Far)\d*_?', gun_name):
                                    cs.setdefault("aa", []).append({
                                        "aa_gun_name": gun_name, "aa_gun_count": 1,
                                        "aura_name": None, "aura_type": None,
                                        "aura_dps": None, "bubble_damage": None,
                                    })
                            elif hp_cat == "DepthChargeGuns":
                                cs.setdefault("depth_charge", []).append({
                                    "gun_name": gun_name, "count": 1,
                                })
                        break

            # 弹鼓/弹夹 (Artillery 特有)
            if current_cat == "Artillery":
                switch_conf = module_data.get("SwitchableModeArtilleryModule")
                drum_conf = module_data.get("DrumArtilleryModule")
                conf = switch_conf or drum_conf
                if conf:
                    mode_name = "连发射击模式" if switch_conf else "弹鼓炮"
                    for lt in target_letters:
                        drum_configs[lt] = {"name": mode_name, "conf": conf}

        # ── 写入船体数据 ──
        raw_species = raw_data.get("typeinfo", {}).get("species", "")
        self._write_hulls(ship_id, raw_data)

        # ── 补充飞机数据：扫描顶层中未被模块匹配的飞机实体 ──
        self._scan_plane_entities(raw_data, combined_stats)

        # ── 写入武器/模块数据 ──
        for letter in sorted(combined_stats.keys()):
            cs = combined_stats[letter]
            self._write_hull_for_letter(ship_id, letter, raw_data, raw_species)
            self._write_guns(conn, ship_id, letter, cs.get("artillery", []),
                             "ship_module_artillery", drum_configs.get(letter))
            self._write_guns(conn, ship_id, letter, cs.get("atba", []),
                             "ship_module_atba")
            self._write_torpedoes(conn, ship_id, letter, cs.get("torpedoes", []))
            self._write_aa(conn, ship_id, letter, cs.get("aa", []))
            self._write_simple_guns(conn, ship_id, letter, "ship_module_depth_charge",
                                    cs.get("depth_charge", []))
            self._write_aircraft(conn, ship_id, letter, cs.get("aircraft", []))
            self._write_hangar(conn, ship_id, letter, cs.get("hangar"),
                               cs.get("flight_control"))
            self._write_air_support(conn, ship_id, letter, cs.get("air_support", []))

    # ── 扫描飞机实体 ──

    def _scan_plane_entities(self, raw_data: dict,
                              combined_stats: dict[str, dict]) -> None:
        """扫描原始 JSON 顶层中未被模块匹配的飞机实体，
           写入对应字母的 combined_stats['aircraft']。"""
        import re
        # 飞机实体 ID 通常以 P + 国家代码开头，后面跟编号和型号名
        plane_key_pattern = re.compile(
            r'^(PAU|PABA|PASA|PAUB|PAUD|PAUI|PAMA|PAJA|PAFR|PAGE|PAIT|PAPN|PAPL|PAEU|PANE|PASP)\d')
        # 也可通过 name_mappings 表判断
        mappings = self.db.get_all_name_mappings("plane") if self.db.exists else {}

        for key, val in raw_data.items():
            if not isinstance(val, dict):
                continue
            # 已在模块匹配中的键跳过
            if any(p.match(key) for p in self.PATTERNS.values()):
                continue
            # 有 planes 字段，或匹配飞机 ID 模式
            if "planes" in val or plane_key_pattern.match(key) or key in mappings:
                # 从数据库 plane_basic_info 获取弹药名（Aircraft 已在 Ship 前处理）
                armament = ""
                row = self.conn.execute(
                    "SELECT armament_name FROM plane_basic_info WHERE plane_id=?",
                    (key,)).fetchone()
                if row and row[0]:
                    armament = row[0]
                # 分配字母：检查是否有 A_ / B_ 前缀
                letter = "A"
                if key.startswith("A_") or key.startswith("B_"):
                    letter = key[0]
                for lt in [letter]:
                    cs = combined_stats.setdefault(lt, {})
                    cs.setdefault("aircraft", []).append({
                        "plane_name": key,
                        "armament_name": armament,
                    })

    # ── 船体写入 ──

    def _write_hulls(self, ship_id: str, raw_data: dict) -> None:
        """写入 ship_module_hulls 表"""
        conn = self.conn
        for mod_key, mod_data in raw_data.items():
            if not isinstance(mod_data, dict):
                continue
            m = self.PATTERNS["Hull"].match(mod_key)
            if not m and mod_key != "Hull_A":
                continue
            letter = mod_key.split("_")[0] if "_" in mod_key else mod_key
            has_cit = 1 if mod_data.get("Cit") else 0
            hull = mod_data.get("Hull", {})
            cit = mod_data.get("Cit", {})
            sub = mod_data.get("SubmarineBattery", {})
            hydro = mod_data.get("Hydrophone", {})

            conn.execute("""INSERT OR REPLACE INTO ship_module_hulls
                (ship_id, module_letter, hull_key, health, max_speed,
                 turning_radius, rudder_time, conceal_sea, conceal_air,
                 has_citadel, hull_regen_part, citadel_regen_part, engine_power,
                 has_battery, battery_capacity, battery_regen,
                 has_hydrophone, hydrophone_radius, hydrophone_update_freq,
                 buoyancy_rudder_time, max_buoyancy_speed)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ship_id, letter, mod_key,
                 mod_data.get("health"), mod_data.get("maxSpeed"),
                 mod_data.get("turningRadius"),
                 (mod_data.get("rudderTime", 0) or 0) * 0.77,
                 mod_data.get("visibilityFactor"),
                 mod_data.get("visibilityFactorByPlane"),
                 has_cit,
                 hull.get("regeneratedHPPart"), cit.get("regeneratedHPPart"),
                 mod_data.get("enginePower"),
                 1 if sub else 0, sub.get("capacity"), sub.get("regenRate"),
                 1 if hydro else 0,
                 (hydro.get("waveRadius") or 0) / 1000,
                 hydro.get("updateFrequency"),
                 mod_data.get("buoyancyRudderTime", 0) * 0.77,
                 mod_data.get("maxBuoyancySpeed")))

    def _write_hull_for_letter(self, ship_id: str, letter: str,
                                raw_data: dict, raw_species: str) -> None:
        """为 ship_module_hulls 表补水深状态数据到 ship_sub_depth_states"""
        conn = self.conn
        for mod_key, mod_data in raw_data.items():
            if not isinstance(mod_data, dict):
                continue
            m = self.PATTERNS["Hull"].match(mod_key)
            if not m and mod_key != "Hull_A":
                continue
            lt = mod_key.split("_")[0] if "_" in mod_key else mod_key
            if lt != letter:
                continue
            hull_id = conn.execute(
                "SELECT id FROM ship_module_hulls WHERE ship_id=? AND hull_key=?",
                (ship_id, mod_key)).fetchone()
            if not hull_id:
                continue
            buoyancy = mod_data.get("buoyancyStates", {})
            for state, values in buoyancy.items():
                if not isinstance(values, (list, tuple)) or len(values) < 2:
                    continue
                # values[0] = depth_range [min, max], values[1] = speed_multiplier
                speed = values[1] if len(values) >= 2 else 1.0
                if isinstance(speed, (list, dict)):
                    speed = 1.0
                conn.execute("""INSERT OR REPLACE INTO ship_sub_depth_states
                    (hull_ref_id, state_name, underwater_max_speed)
                    VALUES (?,?,?)""",
                    (hull_id[0], state, float(speed)))

    # ── 武器写入 ──

    def _write_guns(self, conn, ship_id: str, letter: str,
                    items: list[dict], table: str,
                    drum_info: dict | None = None):
        """写入主炮/副炮表并分组去重"""
        # 聚合: 相同配置的炮塔合并计数
        groups: dict[tuple, list[dict]] = {}
        for item in items:
            key = (item.get("gun_name"), item.get("num_barrels"),
                   item.get("reload_time"), item.get("ideal_radius", 0),
                   item.get("min_radius", 0), item.get("ideal_distance", 0),
                   tuple(sorted(item.get("ammo_list", []))))
            groups.setdefault(key, []).append(item)

        for (gun_name, barrels, reload_t, ir, mr, id_dist, ammo_tuple), group in groups.items():
            count = len(group)
            ref = group[0]
            formula = self._dispersion_formula(ir, mr, id_dist)
            max_range = None  # 系统射程由原始 JSON 获取
            conn.execute(f"""INSERT OR REPLACE INTO {table}
                (ship_id, module_letter, gun_name, count, num_barrels,
                 reload_time, sigma, dispersion_formula,
                 radius_zero, radius_delim, radius_max, delim)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ship_id, letter, gun_name, count, barrels or 0,
                 reload_t or 0, None, formula,
                 ref.get("radius_zero", 0), ref.get("radius_delim", 0),
                 ref.get("radius_max", 0), ref.get("delim", 0)))

            # 弹药关联 → rel_ship_weapon_ammo
            ammo_ids = set()
            for g_item in group:
                for a in (g_item.get("ammo_list", []) or []):
                    if isinstance(a, str):
                        ammo_ids.add(a)
            if ammo_ids:
                gun_row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                wt = "artillery" if "artillery" in table else "atba" if "atba" in table else "torpedo"
                if wt:
                    for aid in ammo_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO rel_ship_weapon_ammo "
                            "(weapon_type, weapon_ref_id, ammo_id) VALUES (?,?,?)",
                            (wt, gun_row_id, aid))

    @staticmethod
    def _dispersion_formula(ir, mr, id_dist):
        if not all(v is not None and v != 0 for v in (ir, mr, id_dist)):
            return None
        slope = (ir - mr) / (id_dist / 1000)
        intercept = mr * 30
        return f"{slope:.1f}R + {intercept:.0f}"

    def _write_torpedoes(self, conn, ship_id, letter, items):
        groups = {}
        for item in (items or []):
            key = (item.get("launcher_name"), item.get("num_barrels"), item.get("reload_time"))
            groups.setdefault(key, []).append(item)
        for (name, barrels, reload_t), group in groups.items():
            conn.execute("""INSERT OR REPLACE INTO ship_module_torpedoes
                (ship_id, module_letter, launcher_name, count, num_barrels, reload_time)
                VALUES (?,?,?,?,?,?)""",
                (ship_id, letter, name, len(group), barrels or 0, reload_t or 0))

    def _write_aa(self, conn, ship_id, letter, items):
        if not items:
            return
        # 去重：相同 (aura_name, aura_type, aura_dps, bubble_damage) 合并计数
        from collections import Counter
        aura_counter: Counter = Counter()
        gun_counter: Counter = Counter()
        for item in items:
            if item.get("aura_name"):
                key = (item["aura_name"], item["aura_type"], item["aura_dps"], item.get("bubble_damage"))
                aura_counter[key] += 1
            elif item.get("aa_gun_name"):
                gun_counter[item["aa_gun_name"]] += 1
        for (name, atype, dps, bdmg), cnt in aura_counter.items():
            conn.execute("""INSERT OR REPLACE INTO ship_module_aa
                (ship_id, module_letter, aura_name, aura_type, aura_dps,
                 bubble_damage, aa_gun_name, aa_gun_count)
                VALUES (?,?,?,?,?,?,?,?)""",
                (ship_id, letter, name, atype, dps, bdmg, None, cnt))
        for gun_name, cnt in gun_counter.items():
            conn.execute("""INSERT OR REPLACE INTO ship_module_aa
                (ship_id, module_letter, aura_name, aura_type, aura_dps,
                 bubble_damage, aa_gun_name, aa_gun_count)
                VALUES (?,?,?,?,?,?,?,?)""",
                (ship_id, letter, None, None, None, None, gun_name, cnt))

    def _write_simple_guns(self, conn, ship_id, letter, table, items):
        counts = Counter(i.get("gun_name") for i in (items or []) if i.get("gun_name"))
        for name, cnt in counts.items():
            conn.execute(f"""INSERT OR REPLACE INTO {table}
                (ship_id, module_letter, gun_name, count)
                VALUES (?,?,?,?)""", (ship_id, letter, name, cnt))

    def _write_aircraft(self, conn, ship_id, letter, items):
        for item in (items or []):
            conn.execute("""INSERT OR REPLACE INTO ship_module_aircraft
                (ship_id, module_letter, module_variant, plane_name, armament_name)
                VALUES (?,?,?,?,?)""",
                (ship_id, letter, item.get("module_variant", ""),
                 item.get("plane_name"), item.get("armament_name")))

    def _write_hangar(self, conn, ship_id, letter, hangar, flight_control):
        if not hangar:
            return
        hangar_item = hangar.get("hangar_1", {}) if isinstance(hangar, dict) else {}
        air_sq = 0
        if isinstance(flight_control, dict):
            air_sq = len(flight_control.get("airSupportSquadrons", []))
        conn.execute("""INSERT OR REPLACE INTO ship_module_hangar
            (ship_id, module_letter, deck_place_count, plane_reserve_capacity,
             launchpad_type, launch_prepare_time, is_parallel_launch,
             joint_launch_count, joint_launch_delay,
             hangar_hp, hangar_regen_part, air_support_squadrons)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ship_id, letter,
             hangar.get("deckPlaceCount"), hangar.get("planesReserveCapacity"),
             hangar.get("launchpadType"), hangar.get("launchPrepareTime"),
             1 if hangar.get("isParallelLaunch") else 0,
             hangar.get("jointLaunchPlaneCount", 1),
             hangar.get("jointLaunchDelay", 0),
             hangar_item.get("maxHP"), hangar_item.get("regeneratedHPPart"),
             air_sq))

    def _write_air_support(self, conn, ship_id, letter, items):
        for item in (items or []):
            conn.execute("""INSERT OR REPLACE INTO ship_module_air_support
                (ship_id, module_letter, plane_name, charges, reload_time,
                 work_time, max_range, min_range, armament_name)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (ship_id, letter, item.get("plane_name"),
                 item.get("charges"), item.get("reload_time"),
                 item.get("work_time"), item.get("max_range"),
                 item.get("min_range"), item.get("armament_name")))

    def _find_plane_armament(self, plane_id: str) -> str:
        """从数据库 plane_basic_info 获取飞机弹药名"""
        row = self.conn.execute(
            "SELECT armament_name FROM plane_basic_info WHERE plane_id=?",
            (plane_id,)).fetchone()
        if row and row[0]:
            return row[0]
        return ""

    # ── 其他实体写入 ──────────────────────────────────────

    def store_gun(self, gun_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or gun_id
        bd = raw_data.get("barrelDiameter", 0) or 0
        caliber = round(bd * 1000, 1) if bd else None
        conn.execute("""INSERT OR REPLACE INTO gun_basic_info
            (gun_id, gun_name_zh, gun_index, num_barrels, caliber,
             reload_time, rotation_speed_h, rotation_speed_v)
            VALUES (?,?,?,?,?,?,?,?)""",
            (gun_id, title, raw_data.get("index", gun_id),
             raw_data.get("numBarrels"), caliber,
             raw_data.get("shotDelay"),
             (raw_data.get("rotationSpeed") or [0, 0])[0],
             (raw_data.get("rotationSpeed") or [0, 0])[1] if len(raw_data.get("rotationSpeed") or []) > 1 else None))
        # 弹药
        for ammo_id in (raw_data.get("ammoList") or []):
            conn.execute("INSERT OR IGNORE INTO gun_ammo_list (gun_id, ammo_id) VALUES (?,?)",
                         (gun_id, ammo_id))
        conn.commit()

    def store_projectile(self, proj_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or proj_id
        from models.name_mapping import Mapping as NM

        species = raw_data.get("typeinfo", {}).get("species", "")
        ammo_type = raw_data.get("ammoType", "")
        nation_raw = raw_data.get("typeinfo", {}).get("nation", "")

        # 收集物种专属额外字段放入 extra_json
        extra = {}
        stp = raw_data.get("SubmarineTorpedoParams", {})
        if stp:
            extra["submarineTorpedoParams"] = stp
        buoyancy = raw_data.get("buoyancyToDamageCoeff", {})
        if buoyancy:
            extra["buoyancyToDamageCoeff"] = buoyancy
        on_hit = raw_data.get("onHit", {})
        if on_hit:
            extra["onHit"] = on_hit
        seq = raw_data.get("attackSequenceDurations")
        if seq:
            extra["attackSequenceDurations"] = seq
        ignore = raw_data.get("ignoreClasses", [])
        if ignore:
            extra["ignoreClasses"] = ignore

        conn.execute("""INSERT OR REPLACE INTO projectile_basic_info
            (projectile_id, ammo_name_zh, projectile_index, species, ammo_type,
             nation_zh, alpha_damage, bullet_speed, bullet_mass, bullet_krupp,
             alpha_piercing_he, burn_prob, explosion_radius,
             bullet_always_ricochet_at, bullet_ricochet_at,
             bullet_detonator, bullet_detonator_threshold,
             bullet_air_drag, bullet_diameter, bullet_cap_normalize_max,
             torpedo_type, is_deep_water, torpedo_max_dist, torpedo_speed,
             torpedo_visibility, torpedo_arming_time, torpedo_uw_critical,
             ignore_classes, dc_speed, dc_timer, dc_max_depth,
             attack_sequence_durations,
             wave_max_damage_pct, wave_min_damage_pct, wave_speed, wave_sector,
             laser_heat, laser_heat_radius, laser_damage_types,
             damage, alpha_piercing_cs,
             depth_splash_size, depth_splash_size_to_torpedo,
             custom_ui_postfix, extra_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
             ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
             ?,?,?,?,?)""",
            (proj_id, title, raw_data.get("index", proj_id),
             species, ammo_type,
             NM.NATION_MAP.get(nation_raw, nation_raw),
             raw_data.get("alphaDamage"), raw_data.get("bulletSpeed"),
             raw_data.get("bulletMass"), raw_data.get("bulletKrupp"),
             raw_data.get("alphaPiercingHE"), raw_data.get("burnProb"),
             raw_data.get("explosionRadius"),
             raw_data.get("bulletAlwaysRicochetAt"), raw_data.get("bulletRicochetAt"),
             raw_data.get("bulletDetonator"), raw_data.get("bulletDetonatorThreshold"),
             raw_data.get("bulletAirDrag"), raw_data.get("bulletDiametr"),
             raw_data.get("bulletCapNormalizeMaxAngle"),
             raw_data.get("torpedoType"), 1 if raw_data.get("isDeepWater") else 0,
             raw_data.get("maxDist"), raw_data.get("speed"),
             raw_data.get("visibilityFactor"), raw_data.get("armingTime"),
             raw_data.get("uwCritical"),
             json.dumps(ignore, ensure_ascii=False) if ignore else '',
             raw_data.get("speed"), raw_data.get("timer"),
             raw_data.get("maxDepth"),
             json.dumps(seq, ensure_ascii=False) if seq else '',
             raw_data.get("maxDamagePercent"), raw_data.get("minDamagePercent"),
             raw_data.get("waveSpeed"), raw_data.get("waveSector"),
             (on_hit.get("HeatEffect", {}) or {}).get("heat") if on_hit else None,
             (on_hit.get("HeatEffect", {}) or {}).get("heatZoneRadius") if on_hit else None,
             json.dumps((on_hit.get("HeatEffect", {}) or {}).get("damageTypes", [])) if on_hit else '',
             raw_data.get("damage"), raw_data.get("alphaPiercingCS"),
             raw_data.get("depthSplashSize"), raw_data.get("depthSplashSizeToTorpedo"),
             raw_data.get("customUIPostfix"),
             json.dumps(extra, ensure_ascii=False)))
        conn.commit()

    def store_plane(self, plane_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or plane_id
        from models.name_mapping import Mapping as NM
        hangar = raw_data.get("hangarSettings", {}) or {}
        squad_size = raw_data.get("numPlanesInSquadron", 0) or 0
        max_hp = raw_data.get("maxHealth", 0) or 0
        armaments = list(filter(None, [raw_data.get("bombName"),
                                       raw_data.get("torpedoName"),
                                       raw_data.get("rocketName"),
                                       raw_data.get("armamentName")]))
        armament_name = ",".join(armaments) or raw_data.get("bombName", "")
        armament_name_zh = ",".join(
            (conn.execute("SELECT lang_zh FROM name_mappings WHERE category='ammo' AND key_name=?",
                          (aid.upper(),)).fetchone() or [None])[0] or aid
            for aid in armaments
        )
        conn.execute("""INSERT INTO plane_basic_info
            (plane_id, plane_name_zh, plane_index, tier, nation_zh, aircraft_class,
             cruise_speed, max_speed, min_speed, max_health, squadron_health, restore_time, deck_capacity,
             squadron_size, attack_size, attack_count, bomb_drop_delay,
             preparation_time, aiming_time, armament_name, armament_name_zh)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plane_id) DO UPDATE SET
             plane_name_zh=excluded.plane_name_zh, plane_index=excluded.plane_index,
             tier=excluded.tier, nation_zh=excluded.nation_zh, aircraft_class=excluded.aircraft_class,
             cruise_speed=excluded.cruise_speed, max_speed=excluded.max_speed, min_speed=excluded.min_speed,
             max_health=excluded.max_health, squadron_health=excluded.squadron_health,
             restore_time=excluded.restore_time, deck_capacity=excluded.deck_capacity,
             squadron_size=excluded.squadron_size, attack_size=excluded.attack_size,
             attack_count=excluded.attack_count, bomb_drop_delay=excluded.bomb_drop_delay,
             preparation_time=excluded.preparation_time, aiming_time=excluded.aiming_time,
             armament_name=excluded.armament_name, armament_name_zh=excluded.armament_name_zh""",
            (plane_id, title, raw_data.get("index", plane_id),
             raw_data.get("level"),
             NM.NATION_MAP.get(
                 raw_data.get("typeinfo", {}).get("nation", ""), ""),
             NM.AIRCRAFT_CLASS_MAP.get(
                 raw_data.get("typeinfo", {}).get("species", ""), ""),
             raw_data.get("speedMoveWithBomb"),
             raw_data.get("speedMax"),
             raw_data.get("speedMin"),
             max_hp, int(max_hp * squad_size) if max_hp and squad_size else None,
             hangar.get("timeToRestore"), hangar.get("maxValue"),
             squad_size, raw_data.get("attackerSize"),
             raw_data.get("attackCount"),
             raw_data.get("bombingDropPointTime"),
             raw_data.get("preparationTime"), raw_data.get("aimingTime"),
             armament_name, armament_name_zh))
        # 消耗品槽位（参照归档 plane_analyzer.py _parse_abilities）
        # 先清理旧槽位，再写入新数据
        conn.execute("DELETE FROM plane_ability_slots WHERE plane_id=?", (plane_id,))
        abilities = raw_data.get("PlaneAbilities", {})
        for sk in sorted(abilities.keys()):
            if "AbilitySlot" not in sk:
                continue
            slot_data = abilities[sk]
            if not isinstance(slot_data, dict):
                continue
            abils = slot_data.get("abils", [])
            slot_num = (slot_data.get('slot') or 0) + 1
            for item in abils:
                if isinstance(item, list) and len(item) > 0:
                    aid = item[0]
                    limit = item[1] if len(item) > 1 else None
                    conn.execute("INSERT OR IGNORE INTO plane_ability_slots "
                        "(plane_id, slot_index, ability_id, ability_limit) VALUES (?,?,?,?)",
                        (plane_id, slot_num, aid, limit))
        conn.commit()

    def store_consumable(self, cid: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or cid

        # 收集所有子配置（每个子 key 对应一个 slot 配置，如 "Default"/"Slot2" 等）
        slot_configs: dict[str, dict] = {}
        main_cfg = None
        for key, val in raw_data.items():
            if not isinstance(val, dict) or key in ("typeinfo", "custom", "ShipAbilities", "PlaneAbilities"):
                continue
            if val.get("consumableType"):
                slot_configs[key] = val
                if main_cfg is None:
                    main_cfg = val  # 第一个找到的作为主配置

        # 顶层也可能有 consumableType
        if raw_data.get("consumableType"):
            slot_configs["_top"] = raw_data
            if main_cfg is None:
                main_cfg = raw_data

        if not main_cfg:
            # 保底：写一条只有 ID 的记录
            conn.execute("INSERT OR REPLACE INTO consumable_basic_info "
                         "(consumable_id, display_name, extra_json) VALUES (?,?,'{}')",
                         (cid, title))
            conn.commit()
            return

        def _g(key, default=None):
            return main_cfg.get(key, default)

        # 将子配置和所有额外字段一并存入 extra_json
        all_extra = {
            "radiusToKill": _g("distanceToKill"),
            "dogFightTime": _g("dogFightTime"),
            "flyAwayTime": _g("flyAwayTime"),
            "flightClimbAngle": _g("climbAngle"),
            "radius": _g("radius"),
            "timeDelayAtk": _g("timeDelayAttack"),
            "timeWaitDelayAtk": _g("timeWaitDelayAttack"),
            "gunsDistCoeff": _g("artilleryDistCoeff"),
            "speedLimit": _g("speedLimit"),
            "height": _g("height"),
            "lifeTime": _g("lifeTime"),
            "forwardEngForsag": _g("forwardEngineForsag"),
            "forwardEngForsagMaxSpd": _g("forwardEngineForsagMaxSpeed"),
            "backwardEngForsag": _g("backwardEngineForsag"),
            "backwardEngForsagMaxSpd": _g("backwardEngineForsagMaxSpeed"),
            "boostCoeff": _g("boostCoeff"),
            "distShip": _g("distShip"),
            "distTorpedo": _g("distTorpedo"),
            "distMine": _g("distSeaMine"),
            "torpedoReloadTime": _g("torpedoReloadTime"),
            "affectedClasses": _g("affectedClasses"),
            "hpUpdFreq": _g("hydrophoneUpdateFrequency"),
            "hpWaveRadius": _g("hydrophoneWaveRadius"),
            "zoneLifeTime": _g("zoneLifeTime"),
            "canUseOnEmpty": _g("canUseOnEmpty"),
            "activationDelay": _g("activationDelay"),
            "buoyancyRudderTimeCoeff": _g("buoyancyRudderTimeCoeff"),
            "maxBuoyancySpeedCoeff": _g("maxBuoyancySpeedCoeff"),
            "battleDropActTime": _g("battleDropActivationTime"),
            "battleDropVisualName": _g("battleDropVisualName"),
            "supportBuoyZoneLifetime": _g("zoneLifetime"),
            "buffDuration": _g("buffDuration"),
            "buffZoneRadius": _g("buffZoneRadius"),
            "damageGMHealCoeff": (_g("modifiers") or {}).get("damageGMHealCoeff"),
            "ownHealPart": _g("ownHealPart"),
            "workRadius": _g("workRadius"),
            "allyBuffName": _g("allyBuffName"),
            "allyBuffLevel": _g("allyBuffLevel"),
            "regenerationRate": _g("regenerationRate"),
            "_slot_configs": slot_configs,  # 所有子配置，供 ship 分析时按 config_key 查询
        }
        extra_json = json.dumps(all_extra, ensure_ascii=False)

        conn.execute("""INSERT OR REPLACE INTO consumable_basic_info
            (consumable_id, display_name, consumable_type,
             num_consumables, work_time, preparation_time, reload_time,
             is_auto_consumable, is_interceptor,
             regen_hp_speed, area_dmg_multiplier, bubble_dmg_multiplier,
             fighter_name, fighter_num, extra_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, title, _g("consumableType"),
             str(_g("numConsumables", 0)),
             _g("workTime"), _g("preparationTime"),
             _g("reloadTime"),
             1 if _g("isAutoConsumable") else 0,
             1 if _g("isInterceptor") else 0,
             _g("regenerationHPSpeed"),
             _g("areaDamageMultiplier"),
             _g("bubbleDamageMultiplier"),
             _g("fightersName"), _g("fightersNum"),
             extra_json))
        conn.commit()

    def store_mod(self, mod_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or mod_id
        conn.execute("""INSERT OR REPLACE INTO modernization_basic_info
            (mod_id, mod_name_zh, mod_index, cost_cr, slot)
            VALUES (?,?,?,?,?)""",
            (mod_id, title, raw_data.get("index", mod_id),
             raw_data.get("costCR"), raw_data.get("slot")))
        # 加成效果
        modifiers = raw_data.get("modifiers", {})
        from models.name_mapping import Mapping as NM
        for mk, mv in modifiers.items():
            name = NM.MODIFIER_MAP.get(mk, mk)
            if isinstance(mv, dict):
                mv_str = str(mv)
            elif isinstance(mv, (int, float)):
                dv = (mv - 1) * 100
                mv_str = f"+{dv:.0f}%" if dv > 0 else f"{dv:.0f}%"
            else:
                mv_str = str(mv)
            conn.execute("""INSERT OR REPLACE INTO modernization_modifiers
                (mod_id, modifier_key, modifier_name_zh, modifier_value, formatted_value)
                VALUES (?,?,?,?,?)""", (mod_id, mk, name, str(mv), mv_str))
        conn.commit()

    def store_crew(self, crew_id: str, raw_data: dict, result) -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or crew_id
        pers = raw_data.get("CrewPersonality", {})
        conn.execute("""INSERT OR REPLACE INTO crew_basic_info
            (crew_id, crew_name, crew_index, nation_zh,
             is_unique, is_animated, is_elite, is_person, is_retrainable)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (crew_id, title, raw_data.get("index", crew_id),
             raw_data.get("typeinfo", {}).get("nation", ""),
             1 if pers.get("isUnique") else 0,
             1 if pers.get("isAnimated") else 0,
             1 if pers.get("isElite") else 0,
             1 if pers.get("isPerson") else 0,
             1 if pers.get("isRetrainable") else 0))
        # 特殊技能
        unique = raw_data.get("UniqueSkills", {})
        for sk, sv in unique.items():
            conn.execute("""INSERT OR REPLACE INTO crew_unique_skills
                (crew_id, skill_key, trigger_type, max_trigger_num,
                 trigger_achievement, trigger_damage_num, trigger_damage_type,
                 damage_percent_threshold, trigger_ribbons_num,
                 trigger_ribbon_types, trigger_allowed_ships)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (crew_id, sk,
                 sv.get("triggerType"), sv.get("maxTriggerNum"),
                 sv.get("triggerAchievement"), sv.get("triggerDamageNum"),
                 sv.get("triggerDamageType"), sv.get("damagePercentThreshold"),
                 sv.get("triggerRibbonsNum"),
                 str(sv.get("triggerRibbonsTypes", [])),
                 str(sv.get("triggerAllowedShips") or sv.get("triggerAllowedShipTypes") or "")))
        conn.commit()



class AnalysisService:
    """分析服务 —— 从 split JSON 读取数据并写入结构化表（无需 analyzers 包）"""

    def __init__(self):
        self._ready = True

    def initialize(self) -> None:
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return self._ready

    @staticmethod
    def _make_entity_result(entity_id: str, category: str, raw_data: dict, db=None):
        """创建一个简单的 AnalysisResult，无需 analyzer"""
        from models.analysis_result import AnalysisResult, DataSection, DataItem
        # 从 name_mappings 获取显示名称（优先使用传入的 db 实例）
        map_cat = {"Ship": "ship", "Gun": "gun", "Projectile": "projectile",
                    "Aircraft": "plane", "Ability": "consumable",
                    "Modernization": "modernization", "Crew": "crew"}
        mc = map_cat.get(category, category.lower())
        names = {}
        if db and db.exists:
            names = db.get_all_name_mappings(mc)
        if not names:
            from services.database_service import get_db
            pdb = get_db()
            if pdb and pdb.exists:
                names = pdb.get_all_name_mappings(mc)
        raw_name = raw_data.get("name", raw_data.get("id", entity_id))
        # 尝试多种 key 格式查找本地化名称
        candidates = [entity_id.upper(), str(raw_name).upper()]
        # 从完整 ID 中提取短索引（如 PASA210_Essex → PASA210）
        for src in (entity_id, str(raw_name)):
            parts = src.split("_")
            if len(parts) > 1:
                candidates.append(parts[0].upper())
        title = entity_id
        for c in candidates:
            if c in names:
                title = names[c]
                break
        return AnalysisResult(title, category, [DataSection("基础属性", [DataItem("名称", title)])])

    def analyze_one(self, category: str, raw_data: dict, entity_id: str = "",
                    db: DatabaseManager | None = None):
        """直接写入数据库（无需 analyzer）"""
        from services.database_service import get_db as _get_db
        store = AnalysisStore(db or _get_db())
        store_func_map = {
            "Ship": store.store_ship,
            "Gun": store.store_gun,
            "Projectile": store.store_projectile,
            "Aircraft": store.store_plane,
            "Ability": store.store_consumable,
            "Modernization": store.store_mod,
            "Crew": store.store_crew,
        }
        store_method = store_func_map.get(category)
        if not store_method:
            return None
        try:
            result = self._make_entity_result(entity_id, category, raw_data, db)
            store_method(entity_id, raw_data, result)
            return result
        except Exception as e:
            print(f"[Analysis] {category}/{entity_id} 失败: {e}")
            return None

    def precompute_all(self, db: DatabaseManager,
                       progress_callback=None) -> dict:
        results: dict[str, int] = {}
        total_processed = 0
        split_dir = get_split_dir()

        # 检查 split 目录是否存在
        if not split_dir.exists():
            bus.log_message.emit("⏳ split 目录不存在，跳过预分析（数据已入库）")
            bus.task_progress.emit(100, "跳过预分析")
            return results

        categories = ["Gun", "Projectile", "Aircraft", "Ability", "Ship",
                       "Modernization", "Crew"]

        # 统计总数
        total_entities = 0
        for cat_name in categories:
            cat_dir = split_dir / cat_name
            if cat_dir.exists():
                total_entities += len(list(cat_dir.glob("*.json")))

        if total_entities == 0:
            bus.task_progress.emit(100, "无数据可分析")
            return results

        bus.task_progress.emit(80, "预分析数据")
        for cat_name in categories:
            cat_dir = split_dir / cat_name
            if not cat_dir.exists():
                results[cat_name] = 0
                continue
            success = 0
            for fp in sorted(cat_dir.glob("*.json")):
                entity_id = fp.stem
                try:
                    raw_data = json.loads(fp.read_text(encoding="utf-8"))
                    self.analyze_one(cat_name, raw_data, entity_id, db)
                    success += 1
                    total_processed += 1
                except Exception:
                    continue
                if total_processed % 50 == 0:
                    bus.task_progress.emit(
                        80 + min(15, total_processed * 15 // max(total_entities, 1)),
                        f"预分析 {total_processed}/{total_entities}")
            results[cat_name] = success

        bus.task_progress.emit(95, f"分析完成: {total_processed} 实体")
        return results
