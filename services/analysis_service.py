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
import sqlite3
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
        # 消耗品配置缓存：避免重复 SELECT consumable_configs
        self._ability_config_cache: dict[str, dict] = {}

    def store_ship(self, ship_id: str, raw_data: dict, result, version_code: str = "") -> None:
        """将舰船完整数据写入所有 ship_* 结构化表"""
        version_code = str(version_code).strip() if version_code else ""
        conn = self.conn

        # ── 基础属性 ──
        self._write_basic_info(ship_id, raw_data, result, version_code=version_code)

        # ── 消耗品 ──
        try:
            self._write_consumables(ship_id, raw_data, version_code=version_code)
        except sqlite3.IntegrityError as e:
            bus.log_message.emit(f"  ⚠️ {ship_id} _write_consumables FK失败: {e}")

        # ── 战斗指令 ──
        try:
            self._write_rage_mode(ship_id, raw_data, version_code=version_code)
        except sqlite3.IntegrityError as e:
            bus.log_message.emit(f"  ⚠️ {ship_id} _write_rage_mode FK失败: {e}")

        # ── 模块数据 (船体/武器/飞机) ──
        try:
            self._write_modules(ship_id, raw_data, version_code=version_code)
        except sqlite3.IntegrityError as e:
            bus.log_message.emit(f"  ⚠️ {ship_id} _write_modules FK失败: {e}")



    # ── 基础信息 ──────────────────────────────────────────

    def _write_basic_info(self, ship_id: str, raw_data: dict, result,
                           version_code: str = "") -> None:
        conn = self.conn
        from models.name_mapping import Mapping as NM
        ti = raw_data.get("typeinfo", {}) or {}
        raw_species = ti.get("species", "")
        raw_level = raw_data.get("level", 0)
        if isinstance(raw_level, dict):
            raw_level = 0
        ship_index = raw_data.get("index", "") or ""
        if not ship_index and "_" in ship_id:
            ship_index = ship_id.split("_", 1)[0]

        # 写入 name_mappings：舰船显示名
        ship_name = result.title or ship_id
        name_mapping_id = None
        if ship_name and ship_name != ship_id:
            try:
                cur = conn.execute(
                    "SELECT id FROM name_mappings WHERE category='ship' AND key_name=?",
                    (ship_id.upper(),))
                row = cur.fetchone()
                if row:
                    name_mapping_id = row[0]
                else:
                    cur = conn.execute(
                        "INSERT INTO name_mappings (category, key_name, lang_zh) VALUES (?,?,?)",
                        ('ship', ship_id.upper(), ship_name))
                    name_mapping_id = cur.lastrowid
            except Exception:
                pass

        # 原型舰船 entity_id
        raw_parent = str(raw_data.get("parentShip", "") or "").strip()
        raw_origin = str(raw_data.get("originShipName", "") or "").strip()
        parent_id = raw_parent.split("_")[0] if raw_parent and "_" in raw_parent else (raw_parent or None)
        origin_id = raw_origin.split("_")[0] if raw_origin and "_" in raw_origin else (raw_origin or None)

        # 确保 entity_registry 有此实体（防止 FK 约束失败）
        if version_code:
            try:
                cur = conn.execute(
                    "SELECT 1 FROM entity_registry WHERE version_code=? AND entity_id=?",
                    (version_code, ship_id))
                if not cur.fetchone():
                    nation = str(ti.get("nation", "") if ti else "")
                    conn.execute(
                        "INSERT OR IGNORE INTO entity_registry "
                        "(version_code, entity_id, entity_type, nation) VALUES (?,?,?,?)",
                        (version_code, ship_id, 'ship', nation))
            except Exception:
                pass

        conn.execute("""INSERT OR REPLACE INTO ship_basic_info
            (version_code, ship_id, name_mapping_id, shiptype, tier,
             ship_index, ship_id_num, group_status_key,
             parent_ship_id, origin_ship_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (version_code, ship_id, name_mapping_id,
             raw_species, int(raw_level or 0),
             ship_index, int(raw_data.get("id", 0) or 0),
             str(raw_data.get("group", "") or ""),
             parent_id, origin_id))

    # ── 消耗品（参照 archived ship_analyzer.py 逻辑）────

    @staticmethod
    def _merge_config_row(row: sqlite3.Row) -> dict:
        """将 consumable_configs 行（列 + extra_json）合并为一个 cfg dict"""
        import json
        cfg = dict(row)
        # 列名 → 驼峰原始 key 的映射（仅对列字段做转换）
        COL2GAME = {
            "consumable_type": "consumableType",
            "num_consumables": "numConsumables",
            "work_time": "workTime",
            "preparation_time": "preparationTime",
            "reload_time": "reloadTime",
            "is_auto_consumable": "isAutoConsumable",
            "is_interceptor": "isInterceptor",
            "regen_hp_speed": "regenerationHPSpeed",
            "area_dmg_multiplier": "areaDamageMultiplier",
            "bubble_dmg_multiplier": "bubbleDamageMultiplier",
            "fighter_name": "fightersName",
            "fighter_num": "fightersNum",
            "available_buoyancy_states": "availableBuoyancyStates",
        }
        # 合并 extra_json 到 cfg，使用原始字段名
        ej = cfg.pop('extra_json', None)
        extra = {}
        if ej:
            try:
                extra = json.loads(ej)
            except (json.JSONDecodeError, TypeError):
                pass
        # 列字段用原始 key 名（驼峰）放入 cfg
        result = {}
        for col, game_key in COL2GAME.items():
            if col in cfg and cfg[col] is not None:
                result[game_key] = cfg[col]
        # extra_json 的字段已经是原始 key 名，直接合并
        result.update(extra)
        # 清理内部字段
        for _k in ('id', 'consumable_id', 'config_key'):
            result.pop(_k, None)
        return result

    def _load_ability_config(self, file_key: str, config_key: str) -> dict:
        """从 consumable_configs 表加载指定 config_key 的子配置（带缓存）"""
        cache_key = f"{file_key}::{config_key}"
        if cache_key not in self._ability_config_cache:
            row = self.conn.execute(
                "SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key=?",
                (file_key, config_key)).fetchone()
            if not row:
                # 回退：尝试查询 Default 配置
                row = self.conn.execute(
                    "SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key='Default'",
                    (file_key,)).fetchone()
            if not row:
                self._ability_config_cache[cache_key] = None
            else:
                self._ability_config_cache[cache_key] = self._merge_config_row(row)
        result = self._ability_config_cache.get(cache_key)
        return result if result else {}

    def _write_consumables(self, ship_id: str, raw_data: dict,
                            version_code: str = "") -> None:
        conn = self.conn
        abilities = raw_data.get("ShipAbilities", {})
        # 缓存消耗品显示名
        name_map = self.db.get_all_name_mappings("consumable") if self.db.exists else {}
        rows = []  # 批量收集 INSERT 数据
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
                    rows.append((
                        version_code, ship_id, slot_idx, i + 1,
                        None,
                        None, '0', 0, 0, 0, 0, file_key, config_key))
                    continue

                display_name = name_map.get(file_key.upper(), file_key)
                num_raw = cfg.get("numConsumables", 0)
                if num_raw == -1:
                    num_str = '-1'
                elif isinstance(num_raw, float):
                    num_str = str(int(num_raw)) if num_raw == int(num_raw) else str(num_raw)
                else:
                    num_str = str(num_raw)
                rows.append((
                    version_code, ship_id, slot_idx, i + 1,
                    None,
                    cfg.get("consumableType"),
                    num_str,
                    cfg.get("preparationTime", 0),
                    cfg.get("workTime", 0),
                    cfg.get("reloadTime", 0),
                    1 if cfg.get("isAutoConsumable") else 0,
                    file_key, config_key))
        if rows:
            conn.executemany("""INSERT OR REPLACE INTO ship_consumable_slots
                (version_code, ship_id, slot_index, item_index, display_name_id, consumable_type,
                 num_consumables, preparation_time, work_time, reload_time,
                 is_auto_consumable, consumable_id, config_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)

    # ── 战斗指令 ──────────────────────────────────────────

    def _write_rage_mode(self, ship_id: str, raw_data: dict,
                          version_code: str = "") -> None:
        import json
        conn = self.conn
        rage = raw_data.get("A_Specials", {}).get("RageMode", {})
        if not rage:
            return

        # 写入 name_mappings：rage_mode 显示名
        raw_name = str(rage.get("rageModeName", ""))
        base_msgid = f"IDS_DOCK_RAGE_MODE_TITLE_{raw_name.upper()}" if raw_name else ""
        display_name_id = None
        if base_msgid:
            try:
                cur = conn.execute(
                    "SELECT id FROM name_mappings WHERE category='rage_mode' AND key_name=?",
                    (base_msgid,))
                row = cur.fetchone()
                if row:
                    display_name_id = row[0]
                else:
                    rage_map = self.db.get_all_name_mappings("rage_mode")
                    display_name = rage_map.get(base_msgid, raw_name)
                    if display_name:
                        cur = conn.execute(
                            "INSERT INTO name_mappings (category, key_name, lang_zh) VALUES (?,?,?)",
                            ('rage_mode', base_msgid, display_name))
                        display_name_id = cur.lastrowid
            except Exception:
                pass

        # 描述 ID
        desc_ids = str(rage.get("descriptionIDS", "") or "")
        description_id = None
        if desc_ids:
            try:
                cur = conn.execute(
                    "SELECT id FROM name_mappings WHERE category='rage_mode' AND key_name=?",
                    (desc_ids,))
                row = cur.fetchone()
                if row:
                    description_id = row[0]
                else:
                    cur = conn.execute(
                        "INSERT INTO name_mappings (category, key_name, lang_zh) VALUES (?,?,?)",
                        ('rage_mode', desc_ids, desc_ids))
                    description_id = cur.lastrowid
            except Exception:
                pass

        triggers = []
        for key in sorted(rage.keys()):
            if "Trigger" in key and isinstance(rage[key], dict):
                triggers.append({key: rage[key]})

        conn.execute("""INSERT OR REPLACE INTO ship_rage_mode
            (version_code, ship_id, display_name_id, boost_duration, max_activation_count,
             is_auto_usage, is_modifier_works_always,
             decrement_delay, decrement_period, decrement_count,
             description_id, modifiers_json, triggers_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (version_code, ship_id,
             display_name_id,
             rage.get("boostDuration", 0),
             str(rage.get("maxActivationCount", 0)),
             1 if rage.get("isAutoUsage") else 0,
             1 if rage.get("isModifierWorksAlways") else 0,
             rage.get("decrementDelay", 0),
             rage.get("decrementPeriod", 0),
             rage.get("decrementCount", 0),
             description_id,
             json.dumps(rage.get("modifiers", {}), ensure_ascii=False),
             json.dumps(triggers, ensure_ascii=False)))

    # ── 模块数据（核心）───────────────────────────────────

    def _write_modules(self, ship_id: str, raw_data: dict,
                        version_code: str = "") -> None:
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
                # ── 提取系统级参数（射程、sigma）──
                # 尝试多种可能的key名称（Lesta版数据可能使用不同命名）
                system_max_dist = (module_data.get("maxDist") or
                                   module_data.get("maxdist") or
                                   module_data.get("maxDistance") or
                                   module_data.get("maxRange") or 0)
                system_sigma = (module_data.get("sigmaCount") or
                                module_data.get("sigma") or None)
                if current_cat in ("Artillery", "ATBA"):
                    sys_key = f"{current_cat}_System"
                    for lt in target_letters:
                        combined_stats[lt][sys_key] = {
                            "max_dist": system_max_dist,
                            "sigma": system_sigma,
                        }

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
                        # 同时检查单个炮塔级别是否有 maxDist（某些数据结构的 fallback）
                        gun_max_dist = (sv.get("maxDist") or
                                        sv.get("maxdist") or
                                        sv.get("maxDistance") or
                                        sv.get("maxRange") or 0)
                        if gun_max_dist and not system_max_dist:
                            system_max_dist = gun_max_dist  # 用单炮数据补充系统级
                            for lt2 in target_letters:
                                sys_key2 = f"{current_cat}_System"
                                if sys_key2 in combined_stats.get(lt2, {}):
                                    combined_stats[lt2][sys_key2]["max_dist"] = gun_max_dist
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
                                    "max_dist": gun_max_dist,
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
                                    "max_dist": gun_max_dist,
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
        try:
            self._write_hulls(ship_id, raw_data, version_code=version_code)
        except sqlite3.IntegrityError as e:
            bus.log_message.emit(f"  ⚠️ {ship_id} _write_hulls FK失败: {e}")

        # ── 补充飞机数据：扫描顶层中未被模块匹配的飞机实体 ──
        self._scan_plane_entities(raw_data, combined_stats)

        # ── 写入武器/模块数据 ──
        for letter in sorted(combined_stats.keys()):
            cs = combined_stats[letter]
            try:
                self._write_hull_for_letter(ship_id, letter, raw_data, raw_species)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_hull_for_letter({letter}) FK失败: {e}")
            sys_arty = cs.get("Artillery_System", {})
            sys_atba = cs.get("ATBA_System", {})
            try:
                self._write_guns(conn, ship_id, letter, cs.get("artillery", []),
                                 "ship_module_artillery", drum_configs.get(letter),
                                 sys_arty, version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_guns(artillery, {letter}) FK失败: {e}")
            try:
                self._write_guns(conn, ship_id, letter, cs.get("atba", []),
                                 "ship_module_atba", None, sys_atba, version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_guns(atba, {letter}) FK失败: {e}")
            try:
                self._write_torpedoes(conn, ship_id, letter, cs.get("torpedoes", []),
                                      version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_torpedoes({letter}) FK失败: {e}")
            try:
                self._write_aa(conn, ship_id, letter, cs.get("aa", []), version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_aa({letter}) FK失败: {e}")
            try:
                self._write_simple_guns(conn, ship_id, letter, "ship_module_depth_charge",
                                        cs.get("depth_charge", []), version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_depth_charge({letter}) FK失败: {e}")
            try:
                self._write_aircraft(conn, ship_id, letter, cs.get("aircraft", []),
                                     version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_aircraft({letter}) FK失败: {e}")
            try:
                self._write_air_support(conn, ship_id, letter, cs.get("air_support", []),
                                        version_code=version_code)
            except sqlite3.IntegrityError as e:
                bus.log_message.emit(f"  ⚠️ {ship_id} _write_air_support({letter}) FK失败: {e}")

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
                # 新架构：plane_basic_info 表已移除，飞机数据通过 ship_module_aircraft 查询
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

    def _write_hulls(self, ship_id: str, raw_data: dict,
                      version_code: str = "") -> None:
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

            import json as _json
            hp_work = hydro.get("workingBuoyancyStates")
            hp_detect = hydro.get("detectableBuoyancyStates")
            hp_work_str = _json.dumps(hp_work, ensure_ascii=False) if hp_work else None
            hp_detect_str = _json.dumps(hp_detect, ensure_ascii=False) if hp_detect else None

            # ── 写入 ship_module_hulls（基础船体字段）──
            conn.execute("""INSERT OR REPLACE INTO ship_module_hulls
                (version_code, ship_id, config_group, module_key, health, max_speed,
                 turning_radius, rudder_time, conceal_sea, conceal_air,
                 visibility_factor_by_plane, has_citadel,
                 hull_regen_part, citadel_regen_part, engine_power)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, ship_id, letter, mod_key,
                 mod_data.get("health"), mod_data.get("maxSpeed"),
                 mod_data.get("turningRadius"),
                 (mod_data.get("rudderTime", 0) or 0) * 0.77,
                 mod_data.get("visibilityFactor"),
                 mod_data.get("visibilityFactorByPlane"),
                 mod_data.get("visibilityFactorByPlane"),
                 has_cit,
                 hull.get("regeneratedHPPart"), cit.get("regeneratedHPPart"),
                 mod_data.get("enginePower")))

            # ── 潜艇扩展数据写入 ship_module_hulls_ext ──
            if sub:
                conn.execute("""INSERT OR REPLACE INTO ship_module_hulls_ext
                    (version_code, ship_id, config_group, module_key,
                     battery_capacity, battery_regen,
                     hydrophone_radius, hydrophone_update_freq,
                     hydrophone_work_states, hydrophone_detect_states,
                     buoyancy_rudder_time, max_buoyancy_speed)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_code, ship_id, letter, mod_key,
                     sub.get("capacity"), sub.get("regenRate"),
                     (hydro.get("waveRadius") or 0) / 1000 if hydro else None,
                     hydro.get("updateFrequency") if hydro else None,
                     hp_work_str, hp_detect_str if hydro else None,
                     mod_data.get("buoyancyRudderTime", 0) * 0.77,
                     mod_data.get("maxBuoyancySpeed")))

    def _write_hull_for_letter(self, ship_id: str, letter: str,
                                raw_data: dict, raw_species: str,
                                version_code: str = "") -> None:
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
            # 新架构：ship_module_hulls 无自增 id 列，ship_sub_depth_states 使用复合 FK
            # 必须先检查 ship_module_hulls_ext 父行是否存在（仅潜艇有该表数据）
            buoyancy = mod_data.get("buoyancyStates", {})
            depth_rows = []
            for state, values in buoyancy.items():
                if not isinstance(values, (list, tuple)) or len(values) < 2:
                    continue
                speed = values[1] if len(values) >= 2 else 1.0
                if isinstance(speed, (list, dict)):
                    speed = 1.0
                depth_rows.append((version_code, ship_id, letter, mod_key, state, float(speed)))
            if depth_rows:
                # 验证父行 ship_module_hulls_ext 是否存在
                has_parent = conn.execute(
                    "SELECT 1 FROM ship_module_hulls_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                    (version_code, ship_id, letter, mod_key)).fetchone()
                if has_parent:
                    conn.executemany("""INSERT OR REPLACE INTO ship_sub_depth_states
                        (version_code, ship_id, config_group, module_key, state_name, underwater_max_speed)
                        VALUES (?,?,?,?,?,?)""", depth_rows)

    # ── 武器写入 ──

    def _write_guns(self, conn, ship_id: str, letter: str,
                    items: list[dict], table: str,
                    drum_info: dict | None = None,
                    system_info: dict | None = None,
                    version_code: str = ""):
        """写入主炮/副炮表并分组去重"""
        max_dist = (system_info or {}).get("max_dist", 0)
        sigma_val = (system_info or {}).get("sigma")
        groups: dict[tuple, list[dict]] = {}
        for item in items:
            key = (item.get("gun_name"), item.get("num_barrels"),
                   item.get("reload_time"), item.get("ideal_radius", 0),
                   item.get("min_radius", 0), item.get("ideal_distance", 0),
                   tuple(sorted(item.get("ammo_list", []))))
            groups.setdefault(key, []).append(item)
        is_artillery = "artillery" in table
        drum_params = {}
        if is_artillery and drum_info:
            conf = drum_info.get("conf", {})
            ctp = conf.get("chargeTimeParams", [0, 0, 0])
            drum_params = {
                "special_mode_name": drum_info.get("name", ""),
                "drum_shots_count": conf.get("shotsCount", 0),
                "drum_shot_delay": conf.get("shotDelay", 0),
                "drum_full_reload_time": conf.get("fullReloadTime", 0),
                "drum_is_switchable": 1 if conf.get("isSwitchable") else 0,
                "drum_is_chargeable": 1 if conf.get("isChargeable") else 0,
                "drum_charge_time_min": ctp[0] if len(ctp) > 0 else 0,
                "drum_charge_time_max": ctp[1] if len(ctp) > 1 else 0,
                "drum_charge_mode": ctp[2] if len(ctp) > 2 else 0,
                "drum_modifiers_json": json.dumps(conf.get("modifiers", {}), ensure_ascii=False),
            }

        # 从表名推断 slot_type
        slot_type = "artillery" if "artillery" in table else "atba"

        for (gun_name, barrels, reload_t, ir, mr, id_dist, ammo_tuple), group in groups.items():
            count = len(group)
            ref = group[0]
            formula = self._dispersion_formula(ir, mr, id_dist)
            # 射程：优先系统级 maxDist，其次尝试单炮 max_dist，最后用 idealDistance 近似
            gun_max_dist = ref.get("max_dist", 0) or 0
            effective_max_dist = max_dist or gun_max_dist or id_dist
            max_range = (effective_max_dist / 1000) if effective_max_dist else None
            sigma_val_use = sigma_val
            if is_artillery:
                conn.execute(f"""INSERT OR REPLACE INTO {table}
                    (version_code, ship_id, config_group, module_key, count, num_barrels,
                     reload_time, sigma, max_range,
                     radius_zero, radius_delim, radius_max, delim)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_code, ship_id, letter, gun_name, count, barrels or 0,
                     reload_t or 0, sigma_val_use, max_range,
                     ref.get("radius_zero", 0), ref.get("radius_delim", 0),
                     ref.get("radius_max", 0), ref.get("delim", 0)))
                # 弹鼓/弹夹特殊模式写入 ship_module_artillery_ext
                if drum_info:
                    conn.execute("""INSERT OR REPLACE INTO ship_module_artillery_ext
                        (version_code, ship_id, config_group, module_key,
                         special_mode_name, drum_shots_count, drum_shot_delay,
                         drum_full_reload_time, drum_is_switchable, drum_is_chargeable,
                         drum_charge_time_min, drum_charge_time_max, drum_charge_mode,
                         drum_modifiers_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (version_code, ship_id, letter, gun_name,
                         drum_params.get("special_mode_name", ""),
                         drum_params.get("drum_shots_count", 0),
                         drum_params.get("drum_shot_delay", 0),
                         drum_params.get("drum_full_reload_time", 0),
                         drum_params.get("drum_is_switchable", 0),
                         drum_params.get("drum_is_chargeable", 0),
                         drum_params.get("drum_charge_time_min", 0),
                         drum_params.get("drum_charge_time_max", 0),
                         drum_params.get("drum_charge_mode", 0),
                         drum_params.get("drum_modifiers_json", "{}")))
            else:
                conn.execute(f"""INSERT OR REPLACE INTO {table}
                    (version_code, ship_id, config_group, module_key, count, num_barrels,
                     reload_time, sigma, max_range,
                     radius_zero, radius_delim, radius_max, delim)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_code, ship_id, letter, gun_name, count, barrels or 0,
                     reload_t or 0, sigma_val_use, max_range,
                     ref.get("radius_zero", 0), ref.get("radius_delim", 0),
                     ref.get("radius_max", 0), ref.get("delim", 0)))
            # 写入 ship_module_relations
            conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                VALUES (?,?,?,?,?,?)""",
                (version_code, ship_id, gun_name, slot_type, letter, count))



    @staticmethod
    def _dispersion_formula(ir, mr, id_dist):
        if not all(v is not None and v != 0 for v in (ir, mr, id_dist)):
            return None
        slope = (ir - mr) / (id_dist / 1000)
        intercept = mr * 30
        return f"{slope:.1f}R + {intercept:.0f}"

    def _write_torpedoes(self, conn, ship_id, letter, items,
                          version_code: str = ""):
        groups = {}
        for item in (items or []):
            key = (item.get("launcher_name"), item.get("num_barrels"), item.get("reload_time"))
            groups.setdefault(key, []).append(item)
        for (name, barrels, reload_t), group in groups.items():
            cnt = len(group)
            conn.execute("""INSERT OR REPLACE INTO ship_module_torpedoes
                (version_code, ship_id, config_group, module_key, count, num_barrels, reload_time)
                VALUES (?,?,?,?,?,?,?)""",
                (version_code, ship_id, letter, name, cnt, barrels or 0, reload_t or 0))
            conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                VALUES (?,?,?,?,?,?)""",
                (version_code, ship_id, name, 'torpedoes', letter, cnt))



    def _write_aa(self, conn, ship_id, letter, items,
                   version_code: str = ""):
        if not items:
            return
        from collections import Counter
        aura_counter: Counter = Counter()
        gun_counter: Counter = Counter()
        for item in items:
            if item.get("aura_name"):
                key = (item["aura_name"], item["aura_type"], item["aura_dps"], item.get("bubble_damage"))
                aura_counter[key] += 1
            elif item.get("aa_gun_name"):
                gun_counter[item["aa_gun_name"]] += 1
        aa_rows = []
        for (name, atype, dps, bdmg), cnt in aura_counter.items():
            aa_rows.append((version_code, ship_id, letter, name, name, atype, dps, bdmg, None, cnt))
        for gun_name, cnt in gun_counter.items():
            aa_rows.append((version_code, ship_id, letter, gun_name, None, None, None, None, gun_name, cnt))
        if aa_rows:
            conn.executemany("""INSERT OR REPLACE INTO ship_module_aa
                (version_code, ship_id, config_group, module_key, aura_name, aura_type, aura_dps,
                 bubble_damage, aa_gun_name, aa_gun_count)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", aa_rows)
            # 写入 ship_module_relations（光环用 aura_name 作 module_id，防空炮用 aa_gun_name）
            for row in aa_rows:
                mod_id = row[3]  # module_key
                conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                    (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                    VALUES (?,?,?,?,?,?)""",
                    (version_code, ship_id, mod_id, 'airDefense', letter, 1))

    def _write_simple_guns(self, conn, ship_id, letter, table, items,
                             version_code: str = ""):
        counts = Counter(i.get("gun_name") for i in (items or []) if i.get("gun_name"))
        if counts:
            rows = [(version_code, ship_id, letter, name, name, cnt) for name, cnt in counts.items()]
            conn.executemany(f"""INSERT OR REPLACE INTO {table}
                (version_code, ship_id, config_group, module_key, gun_name, count)
                VALUES (?,?,?,?,?,?)""", rows)
            for name, cnt in counts.items():
                conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                    (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                    VALUES (?,?,?,?,?,?)""",
                    (version_code, ship_id, name, 'depthCharge', letter, cnt))

    def _write_aircraft(self, conn, ship_id, letter, items,
                         version_code: str = ""):
        if items:
            rows = [(version_code, ship_id, letter,
                     item.get("plane_name") or "",
                     item.get("module_variant", ""),
                     item.get("plane_name"),
                     item.get("armament_name"))
                    for item in items]
            conn.executemany("""INSERT OR REPLACE INTO ship_module_aircraft
                (version_code, ship_id, config_group, module_key, module_variant, plane_name, armament_name)
                VALUES (?,?,?,?,?,?,?)""", rows)
            # 写入 ship_module_relations（去重）
            seen = set()
            for item in items:
                pn = item.get("plane_name") or ""
                if pn and (version_code, ship_id, pn) not in seen:
                    seen.add((version_code, ship_id, pn))
                    conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                        (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                        VALUES (?,?,?,?,?,?)""",
                        (version_code, ship_id, pn, 'aircraft', letter, 1))

    def _write_air_support(self, conn, ship_id, letter, items,
                            version_code: str = ""):
        if items:
            rows = [(version_code, ship_id, letter, item.get("plane_name") or "",
                     item.get("plane_name"), item.get("charges"),
                     item.get("reload_time"), item.get("work_time"),
                     item.get("max_range"), item.get("min_range"),
                     item.get("armament_name"))
                    for item in items]
            conn.executemany("""INSERT OR REPLACE INTO ship_module_air_support
                (version_code, ship_id, config_group, module_key, plane_name, charges, reload_time,
                 work_time, max_range, min_range, armament_name)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
            seen = set()
            for item in items:
                pn = item.get("plane_name") or ""
                if pn and (version_code, ship_id, pn) not in seen:
                    seen.add((version_code, ship_id, pn))
                    conn.execute("""INSERT OR REPLACE INTO ship_module_relations
                        (version_code, ship_id, module_id, slot_type, config_group, mount_count)
                        VALUES (?,?,?,?,?,?)""",
                        (version_code, ship_id, pn, 'airSupport', letter, 1))

    def _find_plane_armament(self, plane_id: str) -> str:
        """从 ship_module_aircraft 获取飞机弹药名（新架构）"""
        row = self.conn.execute(
            "SELECT armament_name FROM ship_module_aircraft WHERE plane_name=? LIMIT 1",
            (plane_id,)).fetchone()
        if row and row[0]:
            return row[0]
        return ""

    # ── 其他实体写入 ──────────────────────────────────────

    def store_gun(self, gun_id: str, raw_data: dict, result, version_code: str = "") -> None:
        # 新架构：火炮数据作为舰船模块存入 ship_module_artillery，此处仅为注册占位
        pass

    def store_projectile(self, proj_id: str, raw_data: dict, result, version_code: str = "") -> None:
        # 新架构：写入 projectile_basic_info（基础信息）+ 按 species 写入扩增表
        conn = self.conn
        title = getattr(result, 'title', '') or proj_id
        species = raw_data.get("typeinfo", {}).get("species", "")
        ammo_type = raw_data.get("ammoType", "")

        conn.execute("""INSERT OR REPLACE INTO projectile_basic_info
            (version_code, projectile_id, projectile_index, species, ammo_type, custom_ui_postfix)
            VALUES (?,?,?,?,?,?)""",
            (version_code, proj_id, raw_data.get("index", proj_id),
             species, ammo_type, raw_data.get("customUIPostfix", "")))

        # ── 按 species 写入对应扩增表 ──
        if species == "Artillery":
            conn.execute("""INSERT OR REPLACE INTO projectile_bullet_ext
                (version_code, projectile_id,
                 alpha_damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag,
                 bullet_krupp, alpha_piercing_he, explosion_radius, burn_prob,
                 alpha_piercing_cs,
                 bullet_always_ricochet_at, bullet_ricochet_at,
                 bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("alphaDamage"), raw_data.get("mass"),
                 raw_data.get("speed"), raw_data.get("diameter"),
                 raw_data.get("airDrag"), raw_data.get("krupp"),
                 raw_data.get("alphaPiercingHE"), raw_data.get("explosionRadius"),
                 raw_data.get("burnProbability"),
                 raw_data.get("alphaPiercingCS"),
                 raw_data.get("alwaysRicochetAt"), raw_data.get("ricochetAt"),
                 raw_data.get("detonator"), raw_data.get("detonatorThreshold"),
                 raw_data.get("capNormalizeMax")))

        elif species == "Torpedo":
            conn.execute("""INSERT OR REPLACE INTO projectile_torpedo_ext
                (version_code, projectile_id,
                 bullet_diameter, alpha_damage, damage, flood_generation,
                 affected_by_ptz, apply_ptz_coeff,
                 torpedo_max_dist, torpedo_speed, torpedo_visibility,
                 alert_dist, torpedo_arming_time,
                 is_deep_water, deep_water_ignore_classes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("diameter"), raw_data.get("alphaDamage"),
                 raw_data.get("damage"),
                 1 if raw_data.get("floodChance") else 0,
                 1 if raw_data.get("affectedByPtz") else 0,
                 1 if raw_data.get("applyPtzCoeff") else 0,
                 raw_data.get("speed") and raw_data.get("distance"),
                 raw_data.get("speed"), raw_data.get("visibilityDist"),
                 raw_data.get("alertDist"), raw_data.get("armingTime"),
                 1 if raw_data.get("isDeepWater") else 0,
                 raw_data.get("deepWaterIgnoreClasses") or ""))

            # 潜艇声呐导向鱼雷扩增
            guidance = raw_data.get("submarineGuidance") or raw_data.get("guidance") or {}
            if guidance or raw_data.get("searchRadius") is not None:
                g = guidance if isinstance(guidance, dict) else {}
                conn.execute("""INSERT OR REPLACE INTO projectile_torpedo_sub_guidance_ext
                    (version_code, projectile_id,
                     search_radius, search_angle, max_depth_level, max_vertical_speed, max_yaw,
                     target_lost_degradation_time,
                     drop_dist_aircarrier, drop_dist_battleship, drop_dist_cruiser,
                     drop_dist_destroyer, drop_dist_submarine, drop_dist_default)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_code, proj_id,
                     g.get("searchRadius") or raw_data.get("searchRadius"),
                     g.get("searchAngle") or raw_data.get("searchAngle"),
                     g.get("maxDepthLevel") or raw_data.get("maxDepthLevel"),
                     g.get("maxVerticalSpeed") or raw_data.get("maxVerticalSpeed"),
                     g.get("maxYaw") or raw_data.get("maxYaw"),
                     g.get("targetLostDegradationTime") or raw_data.get("targetLostDegradationTime"),
                     g.get("dropDistAircraftCarrier") or raw_data.get("dropDistAircraftCarrier"),
                     g.get("dropDistBattleship") or raw_data.get("dropDistBattleship"),
                     g.get("dropDistCruiser") or raw_data.get("dropDistCruiser"),
                     g.get("dropDistDestroyer") or raw_data.get("dropDistDestroyer"),
                     g.get("dropDistSubmarine") or raw_data.get("dropDistSubmarine"),
                     g.get("dropDistDefault") or raw_data.get("dropDistDefault")))

        elif species == "Rocket":
            conn.execute("""INSERT OR REPLACE INTO projectile_rocket_ext
                (version_code, projectile_id,
                 alpha_damage, damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag,
                 alpha_piercing_he, burn_prob, explosion_radius, alpha_piercing_cs,
                 attack_sequence_durations,
                 bullet_krupp,
                 bullet_always_ricochet_at, bullet_ricochet_at,
                 bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("alphaDamage"), raw_data.get("damage"),
                 raw_data.get("mass"), raw_data.get("speed"),
                 raw_data.get("diameter"), raw_data.get("airDrag"),
                 raw_data.get("alphaPiercingHE"), raw_data.get("burnProbability"),
                 raw_data.get("explosionRadius"), raw_data.get("alphaPiercingCS"),
                 raw_data.get("attackSequenceDurations"),
                 raw_data.get("krupp"),
                 raw_data.get("alwaysRicochetAt"), raw_data.get("ricochetAt"),
                 raw_data.get("detonator"), raw_data.get("detonatorThreshold"),
                 raw_data.get("capNormalizeMax")))

        elif species == "Bomb":
            import json as _json
            skips = raw_data.get("skips") or raw_data.get("skipParams")
            conn.execute("""INSERT OR REPLACE INTO projectile_bomb_ext
                (version_code, projectile_id,
                 alpha_damage, damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag,
                 alpha_piercing_he, burn_prob, explosion_radius, alpha_piercing_cs,
                 flight_time_coef,
                 skip_effect, skips_json,
                 bullet_krupp,
                 bullet_always_ricochet_at, bullet_ricochet_at,
                 bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("alphaDamage"), raw_data.get("damage"),
                 raw_data.get("mass"), raw_data.get("speed"),
                 raw_data.get("diameter"), raw_data.get("airDrag"),
                 raw_data.get("alphaPiercingHE"), raw_data.get("burnProbability"),
                 raw_data.get("explosionRadius"), raw_data.get("alphaPiercingCS"),
                 raw_data.get("flightTimeCoef"),
                 raw_data.get("skipEffect"),
                 _json.dumps(skips, ensure_ascii=False) if skips else None,
                 raw_data.get("krupp"),
                 raw_data.get("alwaysRicochetAt"), raw_data.get("ricochetAt"),
                 raw_data.get("detonator"), raw_data.get("detonatorThreshold"),
                 raw_data.get("capNormalizeMax")))

        elif species == "Sonar":
            conn.execute("""INSERT OR REPLACE INTO projectile_sonar_wave_ext
                (version_code, projectile_id,
                 wave_speed, wave_max_damage_pct, wave_min_damage_pct,
                 wave_sector, attack_sequence_durations,
                 laser_heat, laser_heat_radius, laser_damage_types)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("waveSpeed"), raw_data.get("waveMaxDamagePct"),
                 raw_data.get("waveMinDamagePct"),
                 raw_data.get("waveSector"), raw_data.get("attackSequenceDurations"),
                 raw_data.get("laserHeat"), raw_data.get("laserHeatRadius"),
                 raw_data.get("laserDamageTypes")))

        elif species == "DepthCharge":
            conn.execute("""INSERT OR REPLACE INTO projectile_depth_charge_ext
                (version_code, projectile_id,
                 damage, dc_speed, dc_timer, dc_max_depth,
                 depth_splash_size, depth_splash_size_to_torpedo)
                VALUES (?,?,?,?,?,?,?,?)""",
                (version_code, proj_id,
                 raw_data.get("damage"), raw_data.get("speed"),
                 raw_data.get("timer"), raw_data.get("explosionDepth"),
                 raw_data.get("splashSize"), raw_data.get("splashSizeToTorpedo")))

    def store_plane(self, plane_id: str, raw_data: dict, result, version_code: str = "") -> None:
        # 新架构：飞机数据作为舰船模块存入 ship_module_aircraft，此处仅为注册占位
        pass

    # consumable_configs 有专用列的字段名（蛇形→驼峰映射），其余全部自动进 extra_json
    CONFIG_COLUMN_KEYS = {
        "consumableType", "numConsumables", "workTime", "preparationTime",
        "reloadTime", "isAutoConsumable", "isInterceptor",
        "regenerationHPSpeed", "areaDamageMultiplier", "bubbleDamageMultiplier",
        "fightersName", "fightersNum", "availableBuoyancyStates",
    }

    def store_consumable(self, cid: str, raw_data: dict, result, version_code: str = "") -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or cid

        conn.execute("""INSERT OR REPLACE INTO consumable_basic_info
            (version_code, consumable_id, consumable_index, consumable_id_num)
            VALUES (?,?,?,?)""",
            (version_code, cid,
             raw_data.get("index", cid),
             int(raw_data.get("id", 0) or 0)))

        config_rows: list[tuple] = []
        for key, val in raw_data.items():
            if not isinstance(val, dict) or key in ("typeinfo", "custom", "ShipAbilities", "PlaneAbilities"):
                continue
            ct = val.get("consumableType")
            if not ct:
                continue

            col_vals = {}
            extra_vals = {}
            for k, v in val.items():
                if k == "modifiers" and isinstance(v, dict):
                    extra_vals[k] = v
                elif k in self.CONFIG_COLUMN_KEYS:
                    col_vals[k] = v
                elif k in ("typeinfo", "custom", "ShipAbilities", "PlaneAbilities"):
                    continue
                else:
                    extra_vals[k] = v

            extra_json_str = json.dumps(extra_vals, ensure_ascii=False) if extra_vals else '{}'
            buoyancy = col_vals.get("availableBuoyancyStates", [])
            buoyancy_str = json.dumps(buoyancy, ensure_ascii=False) if buoyancy else None

            num_raw = col_vals.get("numConsumables", 0)
            num_str = '-1' if num_raw == -1 else (str(int(num_raw)) if isinstance(num_raw, float) and num_raw == int(num_raw) else str(num_raw))

            config_rows.append((
                version_code, cid, key, ct,
                num_str,
                val.get("workTime", 0),
                val.get("preparationTime", 0),
                val.get("reloadTime", 0),
                1 if val.get("isAutoConsumable") else 0,
                1 if val.get("isInterceptor") else 0,
                val.get("regenerationHPSpeed"),
                val.get("areaDamageMultiplier"),
                val.get("bubbleDamageMultiplier"),
                None,
                val.get("fightersNum"),
                buoyancy_str,
                extra_json_str,
            ))

        if config_rows:
            conn.executemany("""INSERT OR REPLACE INTO consumable_configs
                (version_code, consumable_id, config_key, consumable_type,
                 num_consumables, work_time, preparation_time, reload_time,
                 is_auto_consumable, is_interceptor,
                 regen_hp_speed, area_dmg_multiplier, bubble_dmg_multiplier,
                 fighter_name_id, fighter_num,
                 available_buoyancy_states, extra_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", config_rows)

    def store_mod(self, mod_id: str, raw_data: dict, result, version_code: str = "") -> None:
        # 新架构：升级品数据暂不独立存储，后续可按需扩展
        pass

    def store_crew(self, crew_id: str, raw_data: dict, result, version_code: str = "") -> None:
        conn = self.conn
        title = getattr(result, 'title', '') or crew_id
        pers = raw_data.get("CrewPersonality", {})
        conn.execute("""INSERT OR REPLACE INTO crew_basic_info
            (version_code, crew_id, crew_index, crew_id_num, person_name, nation,
             is_unique, is_animated, is_elite, is_person, is_retrainable)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (version_code, crew_id, raw_data.get("index", crew_id),
             int(raw_data.get("id", 0) or 0),
             pers.get("personName", ""),
             raw_data.get("typeinfo", {}).get("nation", ""),
             1 if pers.get("isUnique") else 0,
             1 if pers.get("isAnimated") else 0,
             1 if pers.get("isElite") else 0,
             1 if pers.get("isPerson") else 0,
             1 if pers.get("isRetrainable") else 0))
        # 特殊技能
        unique = raw_data.get("UniqueSkills", {})
        import json as _json
        META_KEYS = {
            "triggerType", "maxTriggerNum", "sortIndex", "damagePercentThreshold",
            "triggerAllowedShips", "triggerAllowedShipTypes", "triggerRibbonsNum",
            "triggerIsSubRibbons", "triggerJoinRibbons", "triggerRibbonsTypes",
        }
        for sk, sv in unique.items():
            effects = {}
            for ek, ev in sv.items():
                if ek in META_KEYS or not isinstance(ev, dict):
                    continue
                effects[ek] = ev
            conn.execute("""INSERT OR REPLACE INTO crew_unique_skills
                (version_code, crew_id, skill_key, sort_index,
                 trigger_type, max_trigger_num,
                 trigger_achievement, trigger_damage_num, trigger_damage_type,
                 damage_percent_threshold, trigger_ribbons_num,
                 trigger_ribbon_types, trigger_allowed_ships, effects_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, crew_id, sk, sv.get("sortIndex", 0),
                 sv.get("triggerType"), sv.get("maxTriggerNum"),
                 sv.get("triggerAchievement"), sv.get("triggerDamageNum"),
                 sv.get("triggerDamageType"), sv.get("damagePercentThreshold"),
                 sv.get("triggerRibbonsNum"),
                 str(sv.get("triggerRibbonsTypes", [])),
                 str(sv.get("triggerAllowedShips") or sv.get("triggerAllowedShipTypes") or ""),
                 _json.dumps(effects, ensure_ascii=False)))



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
                    db: DatabaseManager | None = None,
                    version_code: str = ""):
        """直接写入数据库（无需 analyzer）"""
        version_code = str(version_code).strip() if version_code else ""
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
            store_method(entity_id, raw_data, result, version_code=version_code)
            return result
        except Exception as e:
            bus.log_message.emit(f"⚠️ [分析] {category}/{entity_id} 失败: {e}")
            return None

    def precompute_all(self, db: DatabaseManager,
                       progress_callback=None,
                       data_by_category: dict[str, dict[str, dict]] | None = None,
                       version_code: str = "") -> dict:
        """预分析数据并写入结构化表。

        参数:
            data_by_category: { 'Ship': { 'PASA001': {...}, ... }, 'Gun': {...}, ... }
            version_code: 数据版本号，由 processor_service 传入
        """
        results: dict[str, int] = {}
        total_processed = 0
        split_dir = get_split_dir()
        categories = ["Gun", "Projectile", "Aircraft", "Ability", "Ship",
                       "Modernization", "Crew"]

        # ── 写入性能调优 ──
        raw_conn = db._conn
        raw_conn.execute("PRAGMA synchronous=OFF")
        raw_conn.execute("PRAGMA cache_size=-32000")
        raw_conn.execute("PRAGMA temp_store=MEMORY")
        raw_conn.execute("PRAGMA mmap_size=268435456")
        raw_conn.execute("PRAGMA page_size=8192")

        if data_by_category:
            # ── 内存模式：直接分析传入的字典 ──
            total_entities = sum(len(v) for v in data_by_category.values())
            if total_entities == 0:
                bus.task_progress.emit(100, "无数据可分析")
                return results
            bus.task_progress.emit(80, "预分析数据")
            for cat_name in categories:
                cat_data = data_by_category.get(cat_name)
                if not cat_data:
                    results[cat_name] = 0
                    continue
                raw_conn.execute("BEGIN TRANSACTION")
                success = 0
                for entity_id, raw_data in sorted(cat_data.items()):
                    try:
                        self.analyze_one(cat_name, raw_data, entity_id, db, version_code=version_code)
                        success += 1
                        total_processed += 1
                    except Exception:
                        continue
                    if total_processed % 100 == 0:
                        bus.task_progress.emit(
                            80 + min(15, total_processed * 15 // max(total_entities, 1)),
                            f"预分析 {total_processed}/{total_entities}")
                raw_conn.commit()
                results[cat_name] = success
            bus.task_progress.emit(95, f"分析完成: {total_processed} 实体")
            return results

        # ── 文件模式：从 split 目录读取（原有逻辑） ──
        if not split_dir.exists():
            bus.log_message.emit("⏳ split 目录不存在，跳过预分析（数据已入库）")
            bus.task_progress.emit(100, "跳过预分析")
            return results

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
            raw_conn.execute("BEGIN TRANSACTION")
            success = 0
            for fp in sorted(cat_dir.glob("*.json")):
                entity_id = fp.stem
                try:
                    raw_data = json.loads(fp.read_text(encoding="utf-8"))
                    self.analyze_one(cat_name, raw_data, entity_id, db, version_code=version_code)
                    success += 1
                    total_processed += 1
                except Exception:
                    continue
                if total_processed % 100 == 0:
                    bus.task_progress.emit(
                        80 + min(15, total_processed * 15 // max(total_entities, 1)),
                        f"预分析 {total_processed}/{total_entities}")
            raw_conn.commit()
            results[cat_name] = success

        bus.task_progress.emit(95, f"分析完成: {total_processed} 实体")
        return results
