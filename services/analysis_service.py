"""
预分析服务 —— 将原始 JSON 数据深度解析后写入结构化数据库表（完全重构版）。

按 database_new.sql 的 34 张表设计，从 split JSON 文件或内存字典读取数据并写入。
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Callable, Optional

from services.database_service import DatabaseManager
from utils.path_utils import get_split_dir
from app.signals import bus


# ── 辅助函数 ────────────────────────────────────────────

def _unwrap(v):
    """从可能的单元素数组中解出标量值"""
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return v[0]
    return v


def _v(v, default=None):
    """取标量值，若为 list/dict 则返回 default"""
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        return default
    return v


def _i(v):
    """转为 int"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _bn(v):
    """布尔转 0/1"""
    return 1 if v else 0


def _unwrap_list(lst, idx):
    """从列表中取第 idx 个元素，非列表则返回 None"""
    if isinstance(lst, (list, tuple)) and len(lst) > idx:
        return lst[idx]
    return None


def _ability_str(pabs, slot_idx):
    """从 PlaneAbilities 中提取指定槽位的消耗品字符串 'ability_id|variant'"""
    if not isinstance(pabs, dict):
        return None
    sk = f"AbilitySlot{slot_idx}"
    slot = pabs.get(sk)
    if not isinstance(slot, dict):
        return None
    abils = slot.get("abils", [])
    if not abils:
        return None
    ab = abils[0]
    aid = ab[0] if isinstance(ab, (list, tuple)) and len(ab) > 0 else (ab or "")
    variant = ab[1] if isinstance(ab, (list, tuple)) and len(ab) > 1 else ""
    if not aid:
        return None
    return f"{aid}|{variant}" if variant else aid


def _json_dumps(v):
    """安全 JSON 序列化"""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


# ── 模块匹配模式 ────────────────────────────────────────

MODULE_PATTERNS = {
    "Hull": re.compile(r'(?:([A-Z]+\d*)_)?Hull(?:Default)?'),
    "Artillery": re.compile(r'(?:([A-Z]+\d*)_)?Artillery(?:Default)?'),
    "SecondaryArtillery": re.compile(r'(?:([A-Z]+\d*)_)?SecondaryArtillery(?:Default)?'),
    "ATBA": re.compile(r'(?:([A-Z]+\d*)_)?ATBA(?:Default)?'),
    "Torpedoes": re.compile(r'(?:([A-Z]+\d*)_)?Torpedoes(?:Default)?'),
    "DiveBomber": re.compile(r'(?:([A-Z]+\d*)_)?DiveBomber(?:Default)?'),
    "Fighter": re.compile(r'(?:([A-Z]+\d*)_)?Fighter(?:Default)?'),
    "SkipBomber": re.compile(r'(?:([A-Z]+\d*)_)?SkipBomber(?:Default)?'),
    "TorpedoBomber": re.compile(r'(?:([A-Z]+\d*)_)?TorpedoBomber(?:Default)?'),
    "AirSupport": re.compile(r'(?:([A-Z]+\d*)_)?AirSupport(?:Default)?'),
    "AirDefense": re.compile(r'(?:([A-Z]+\d*)_)?AirDefense(?:Default)?'),
    "DepthChargeGuns": re.compile(r"(?:([A-Z]+\d*)_)?DepthChargeGuns(?:Default)?"),
    "AirArmament": re.compile(r'(?:([A-Z]+\d*)_)?AirArmament(?:Default)?'),
    "FlightControl": re.compile(r'(?:([A-Z]+\d*)_)?FlightControl(?:Default)?'),
}

HP_PATTERNS = {
    "Artillery": re.compile(r'HP_[A-Z]GM_\d+'),
    "SecondaryArtillery": re.compile(r'HP_[A-Z]GM_\d+'),
    "ATBA": re.compile(r'HP_([A-Z]GS)_\d+'),
    "AirDefense": re.compile(r'(HP_[A-Z]GA_\d+|HP_[A-Z]GM_\d+_HP_[A-Z]GA_\d+|Aura_\d+|(Far|Medium|Near)\d*(_Bubbles)?)'),
    "Torpedoes": re.compile(r'HP_[A-Z]GT_\d+'),
    "DepthChargeGuns": re.compile(r"HP_[A-Z]GB_\d+"),
}

# 飞机实体 ID 格式: P + [区域码] + A(Aircraft标记) + [类型] + 数字
# 类型: B=Bomber/TB, D=DiveBomber, F=Fighter, S=Scout, M=Mine, L=?, C=Cruise, X=Special
PLANE_PREFIX_RE = re.compile(
    r'^P[A-Z]A[ABDFLMSXC]\d'
)


def _extract_letter(mod_key: str) -> str:
    parts = mod_key.split("_", 1)
    if parts:
        m = re.match(r'([A-Z]+)', parts[0])
        return m.group(1) if m else parts[0][0]
    return "A"


PROJECTILE_EXT_MAP = {
    "Artillery": {
        "table": "projectile_bullet_ext",
        "cols": ("alpha_damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag, "
                 "bullet_krupp, alpha_piercing_he, explosion_radius, burn_prob, "
                 "alpha_piercing_cs, "
                 "bullet_always_ricochet_at, bullet_ricochet_at, "
                 "bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"),
        "phs": 15,
        "fields": (
            "alphaDamage", "bulletMass", "bulletSpeed", "bulletDiametr", "bulletAirDrag",
            "bulletKrupp", "alphaPiercingHE", "explosionRadius", "burnProb",
            "alphaPiercingCS",
            "bulletAlwaysRicochetAt", "bulletRicochetAt",
            "bulletDetonator", "bulletDetonatorThreshold", "bulletCapNormalizeMaxAngle"
        ),
    },
    "Torpedo": {
        "table": "projectile_torpedo_ext",
        "cols": ("bullet_diameter, alpha_damage, damage, flood_generation, "
                 "affected_by_ptz, apply_ptz_coeff, "
                 "torpedo_max_dist, torpedo_speed, torpedo_visibility, "
                 "alert_dist, torpedo_arming_time, burn_prob, uw_critical, "
                 "is_deep_water, deep_water_ignore_classes"),
        "phs": 15,
        "fields": (
            "bulletDiametr", "alphaDamage", "damage",
            lambda r: _bn(r.get("floodGeneration")),
            lambda r: _bn(r.get("affectedByPTZ")),
            lambda r: _bn(r.get("applyPTZCoeff")),
            "maxDist", "speed", "visibilityFactor",
            "alertDist", "armingTime",
            "burnProb", "uwCritical",
            lambda r: _bn(r.get("isDeepWater")),
            lambda r: r.get("deepWaterIgnoreClasses") or ""
        ),
    },
    "DepthCharge": {
        "table": "projectile_depth_charge_ext",
        "cols": "damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size, depth_splash_size_to_torpedo",
        "phs": 6,
        "fields": ("alphaDamage", "speed", "timer", "maxDepth", "depthSplashSize", "depthSplashSizeToTorpedo"),
    },
    "Bomb": {
        "table": "projectile_bomb_ext",
        "cols": ("alpha_damage, damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag, "
                 "alpha_piercing_he, burn_prob, explosion_radius, alpha_piercing_cs, "
                 "flight_time_coef, skip_effect, max_skip_angle, skips_json, "
                 "bullet_krupp, bullet_always_ricochet_at, bullet_ricochet_at, "
                 "bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max, is_bomb"),
        "phs": 21,
        "fields": (
            "alphaDamage", "damage", "bulletMass", "bulletSpeed", "bulletDiametr", "bulletAirDrag",
            "alphaPiercingHE", "burnProb", "explosionRadius", "alphaPiercingCS",
            "flightTimeCoef", "skipEffect", "maxSkipAngle",
            lambda r: _json_dumps(r.get("skips") or r.get("skipParams")),
            "bulletKrupp", "bulletAlwaysRicochetAt", "bulletRicochetAt",
            "bulletDetonator", "bulletDetonatorThreshold", "bulletCapNormalizeMaxAngle",
            lambda r: 1,
        ),
    },
    "SkipBomb": {
        "table": "projectile_bomb_ext",
        "cols": ("alpha_damage, damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag, "
                 "alpha_piercing_he, burn_prob, explosion_radius, alpha_piercing_cs, "
                 "flight_time_coef, skip_effect, max_skip_angle, skips_json, "
                 "bullet_krupp, bullet_always_ricochet_at, bullet_ricochet_at, "
                 "bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max, is_bomb"),
        "phs": 21,
        "fields": (
            "alphaDamage", "damage", "bulletMass", "bulletSpeed", "bulletDiametr", "bulletAirDrag",
            "alphaPiercingHE", "burnProb", "explosionRadius", "alphaPiercingCS",
            "flightTimeCoef", "skipEffect", "maxSkipAngle",
            lambda r: _json_dumps(r.get("skips") or r.get("skipParams")),
            "bulletKrupp", "bulletAlwaysRicochetAt", "bulletRicochetAt",
            "bulletDetonator", "bulletDetonatorThreshold", "bulletCapNormalizeMaxAngle",
            lambda r: 0,
        ),
    },
    "Rocket": {
        "table": "projectile_rocket_ext",
        "cols": ("alpha_damage, damage, bullet_mass, bullet_speed, bullet_diameter, bullet_air_drag, "
                 "alpha_piercing_he, burn_prob, explosion_radius, alpha_piercing_cs, "
                 "attack_sequence_durations, "
                 "bullet_krupp, bullet_always_ricochet_at, bullet_ricochet_at, "
                 "bullet_detonator, bullet_detonator_threshold, bullet_cap_normalize_max"),
        "phs": 17,
        "fields": (
            "alphaDamage", "damage", "bulletMass", "bulletSpeed", "bulletDiametr", "bulletAirDrag",
            "alphaPiercingHE", "burnProb", "explosionRadius", "alphaPiercingCS",
            lambda r: _json_dumps(r.get("attackSequenceDurations")),
            "bulletKrupp", "bulletAlwaysRicochetAt", "bulletRicochetAt",
            "bulletDetonator", "bulletDetonatorThreshold", "bulletCapNormalizeMaxAngle"
        ),
    },
    "Sonar": {
        "table": "projectile_sonar_wave_ext",
        "cols": "wave_speed, wave_max_damage_pct, wave_min_damage_pct, wave_sector, attack_sequence_durations, laser_heat, laser_heat_radius, laser_damage_types",
        "phs": 8,
        "fields": (
            "waveSpeed", "waveMaxDamagePct", "waveMinDamagePct",
            "waveSector", "attackSequenceDurations",
            "laserHeat", "laserHeatRadius", "laserDamageTypes"
        ),
    },
}


# ═════════════════════════════════════════════════════════════════════
# AnalysisStore —— 数据写入器
# ═════════════════════════════════════════════════════════════════════

class AnalysisStore:
    """将解析后的数据写入结构化数据库表"""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.conn = db._conn

    def _gf(self, raw_data: dict, field_spec, default=None):
        if callable(field_spec):
            return field_spec(raw_data)
        return raw_data.get(field_spec, default)

    # ── 1. Ship ──────────────────────────────────────────

    def store_ship(self, ship_id: str, raw_data: dict, version_code: str = ""):
        ti = raw_data.get("typeinfo", {}) or {}
        species = ti.get("species", "")
        level = _v(raw_data.get("level"), 0)
        # ship_index 是纯数字前缀如 PASA206，name_mappings 中 ship 类别的 key 也是此前缀
        ship_index = raw_data.get("index", "") or ""
        if not ship_index and "_" in ship_id:
            ship_index = ship_id.split("_", 1)[0]
        self.conn.execute("""INSERT OR REPLACE INTO ship_basic_info
            (version_code, ship_id, name_mapping_id, shiptype, tier,
             ship_index, ship_id_num, group_status_key,
             parent_ship_id, origin_ship_id)
            VALUES (?,?,(SELECT id FROM name_mappings WHERE category='ship' AND key_name=?),?,?,?,?,?,?,?)""",
            (version_code, ship_id, ship_index.upper(), species, _i(level),
             ship_index, _i(raw_data.get("id")),
             str(raw_data.get("group", "") or ""),
             raw_data.get("parentShip"), raw_data.get("originShipName")))

        # 解析模块
        combined_stats: dict[str, dict] = {}
        drum_configs: dict[str, dict] = {}
        has_pure_b = any(k.startswith("B_") for k in raw_data if isinstance(raw_data.get(k), dict))

        for mod_key, module_data in raw_data.items():
            if not isinstance(module_data, dict):
                continue
            target_letters = []
            current_cat = None
            for cat, pattern in MODULE_PATTERNS.items():
                m = pattern.match(mod_key)
                if m:
                    raw_prefix = m.group(1)
                    if raw_prefix is None:
                        # *Default 模式无前缀字母，使用默认 "A"
                        target_letters = ["A"]
                    else:
                        prefix = "".join(re.findall(r'[A-Z]+', raw_prefix))
                        target_letters = list(prefix) if prefix != "AB" else (["A", "B"] if has_pure_b else ["A"])
                    current_cat = cat
                    break
            if not target_letters or not current_cat:
                continue
            for lt in target_letters:
                combined_stats.setdefault(lt, {})
            m2 = re.match(r'([A-Z]+)(\d*)', m.group(1)) if m and m.group(1) else None
            variant = m2.group(2) if m2 and m2.group(2) else ""

            # 飞机（仅当存在纯 B 前缀的飞机模块时才拆 AB → A+B）
            if current_cat in ("DiveBomber", "TorpedoBomber", "Fighter", "SkipBomber"):
                if prefix == "AB":
                    has_pure_b_air = any(
                        k.startswith("B") and any(
                            pat.match(k) for pat in MODULE_PATTERNS.values()
                        ) for k in raw_data if isinstance(raw_data.get(k), dict)
                    )
                    target_letters = ["A", "B"] if has_pure_b_air else ["A"]
                for pl in (module_data.get("planes", []) or []):
                    if isinstance(pl, dict):
                        pn, arm = pl.get("name", ""), pl.get("armamentName", "")
                    elif isinstance(pl, str):
                        pn, arm = pl, module_data.get("armamentName", "")
                    else:
                        continue
                    config_prefix = mod_key  # 完整模块名如 "A1_Fighter"
                    for lt in target_letters:
                        combined_stats[lt].setdefault("aircraft", []).append(
                            {"plane_name": pn, "armament_name": arm, "module_variant": variant, "plane_type": current_cat,
                             "config_prefix": config_prefix})
                continue

            # 空袭
            if current_cat == "AirSupport":
                for lt in target_letters:
                    combined_stats.setdefault(lt, {}).setdefault("air_support", [])
                for k, v in module_data.items():
                    if isinstance(v, dict) and "Armament" in k:
                        for lt in target_letters:
                            combined_stats[lt]["air_support"].append({
                                "plane_name": v.get("planeName", ""),
                                "charges": v.get("chargesNum", 0),
                                "reload_time": v.get("reloadTime", 0),
                                "work_time": v.get("workTime", 0),
                                "max_range": _v(v.get("maxDist")) if v.get("maxDist") is not None else None,
                                "min_range": _v(v.get("minDist")) if v.get("minDist") is not None else None,
                                "armament_name": self._find_armament(v.get("planeName", "")),
                                "support_type": v.get("uiType", ""),
                            })
                continue

            if current_cat in ("AirArmament", "FlightControl"):
                for lt in target_letters:
                    combined_stats.setdefault(lt, {})["hangar" if current_cat == "AirArmament" else "flight_control"] = module_data
                continue

            if current_cat in ("Artillery", "SecondaryArtillery", "ATBA", "AirDefense", "Torpedoes", "DepthChargeGuns"):
                sys_max_dist = module_data.get("maxDist") or module_data.get("maxdist") or module_data.get("maxDistance") or module_data.get("maxRange") or 0
                sys_sigma = module_data.get("sigmaCount") or module_data.get("sigma") or None
                if current_cat in ("Artillery", "SecondaryArtillery", "ATBA"):
                    skey = f"{current_cat}_System"
                    for lt in target_letters:
                        combined_stats[lt][skey] = {"max_dist": sys_max_dist, "sigma": sys_sigma}
                for sk, sv in module_data.items():
                    if not isinstance(sv, dict):
                        continue
                    if any(kw in sk for kw in ("Aura", "Far", "Medium", "Med", "Near")):
                        is_bubble = "_Bubbles" in sk
                        area_dmg = _v(sv.get("areaDamage"), 0)
                        ap = _v(sv.get("areaDamagePeriod"), 1)
                        dps = area_dmg / ap if ap else 0
                        bd = _v(sv.get("bubbleDamage"), 0) * 2 / ap if is_bubble and ap else 0
                        # 黑云总数 = innerBubbleCount + outerBubbleCount
                        bubble_total = (_v(sv.get("innerBubbleCount"), 0) or 0) + (_v(sv.get("outerBubbleCount"), 0) or 0)
                        for lt in target_letters:
                            cs = combined_stats[lt]
                            atype = sv.get("type", "").capitalize()
                            cs.setdefault("aa", []).append({
                                "aura_name": f"{sv.get('name', sk)}_{atype}" if atype else sv.get("name", sk),
                                "aura_type": "bubble" if is_bubble else "continuous",
                                "aura_type_raw": sv.get("type", ""),
                                "aura_dps": round(dps, 1), "bubble_damage": round(bd, 1),
                                "explosion_count": bubble_total,
                                "hit_chance": _v(sv.get("hitChance")),
                                "max_distance": _v(sv.get("maxDistance"), 0),
                                "min_distance": _v(sv.get("minDistance"), 0),
                                "aa_gun_name": None, "aa_gun_count": None,
                            })
                        continue
                    hp_cats = [current_cat]
                    if current_cat in ("Artillery", "SecondaryArtillery", "ATBA"):
                        hp_cats.append("AirDefense")
                    for hp_cat in hp_cats:
                        hp_pat = HP_PATTERNS.get(hp_cat)
                        if not hp_pat or not hp_pat.match(sk):
                            continue
                        gn = sv.get("name", sk)
                        br = _v(sv.get("numBarrels"), 0)
                        rt = sv.get("shotDelay")
                        gmd = sv.get("maxDist") or sv.get("maxdistance") or sv.get("maxDistance") or sv.get("maxRange") or 0
                        if gmd and not sys_max_dist:
                            sys_max_dist = gmd
                            for lt2 in target_letters:
                                sk2 = f"{current_cat}_System"
                                if sk2 in combined_stats.get(lt2, {}):
                                    combined_stats[lt2][sk2]["max_dist"] = gmd
                        for lt in target_letters:
                            cs = combined_stats[lt]
                            entry = {"gun_name": gn, "count": 1, "num_barrels": br, "reload_time": rt,
                                     "max_dist": gmd, "ammo_list": sv.get("ammoList", [])}
                            if hp_cat == "Artillery":
                                entry.update({
                                    "caliber": _v(sv.get("caliber"), 0),
                                    "ideal_radius": _v(sv.get("idealRadius"), 0),
                                    "min_radius": _v(sv.get("minRadius"), 0),
                                    "ideal_distance": _v(sv.get("idealDistance"), 0),
                                    "radius_zero": _v(sv.get("radiusOnZero"), 0),
                                    "radius_delim": _v(sv.get("radiusOnDelim"), 0),
                                    "radius_max": _v(sv.get("radiusOnMax"), 0),
                                    "delim": _v(sv.get("delim"), 0),
                                    "rotation_speed_h": _v((sv.get("rotationSpeed") or [None, None])[0]),
                                    "rotation_speed_v": _v((sv.get("rotationSpeed") or [None, None])[1]),
                                })
                                cs.setdefault("artillery", []).append(entry)
                            elif hp_cat == "SecondaryArtillery":
                                entry.update({
                                    "caliber": _v(sv.get("caliber"), 0),
                                    "ideal_radius": _v(sv.get("idealRadius"), 0),
                                    "min_radius": _v(sv.get("minRadius"), 0),
                                    "ideal_distance": _v(sv.get("idealDistance"), 0),
                                    "radius_zero": _v(sv.get("radiusOnZero"), 0),
                                    "radius_delim": _v(sv.get("radiusOnDelim"), 0),
                                    "radius_max": _v(sv.get("radiusOnMax"), 0),
                                    "delim": _v(sv.get("delim"), 0),
                                    "rotation_speed_h": _v((sv.get("rotationSpeed") or [None, None])[0]),
                                    "rotation_speed_v": _v((sv.get("rotationSpeed") or [None, None])[1]),
                                })
                                cs.setdefault("secondary_artillery", []).append(entry)
                            elif hp_cat == "ATBA":
                                entry.update({
                                    "ideal_radius": _v(sv.get("idealRadius"), 0),
                                    "min_radius": _v(sv.get("minRadius"), 0),
                                    "ideal_distance": _v(sv.get("idealDistance"), 0),
                                    "radius_zero": _v(sv.get("radiusOnZero"), 0),
                                    "radius_delim": _v(sv.get("radiusOnDelim"), 0),
                                    "radius_max": _v(sv.get("radiusOnMax"), 0),
                                    "delim": _v(sv.get("delim"), 0),
                                })
                                cs.setdefault("atba", []).append(entry)
                            elif hp_cat == "Torpedoes":
                                entry.update({"launcher_name": gn})
                                cs.setdefault("torpedoes", []).append(entry)
                            elif hp_cat == "AirDefense":
                                if not re.match(r'^(Medium|Near|Far)\d*_?', gn):
                                    cs.setdefault("aa", []).append({
                                        "aa_gun_name": gn, "aa_gun_count": 1,
                                        "aura_name": None, "aura_type": None, "aura_dps": None, "bubble_damage": None,
                                    })
                            elif hp_cat == "DepthChargeGuns":
                                # 模块级数据
                                ammo_id = (sv.get("ammoList") or [None])[0]
                                cs.setdefault("depth_charge", []).append({
                                    "gun_name": gn, "count": 1,
                                    "reload_time": _v(module_data.get("reloadTime")),
                                    "shot_delay": _v(module_data.get("shotDelay")),
                                    "max_packs": _v(module_data.get("maxPacks")),
                                    "num_shots": _v(module_data.get("numShots")),
                                    "num_bombs": _v(sv.get("numBombs")),
                                    "ammo_id": ammo_id,
                                })
                        break

                if current_cat == "Artillery":
                    for ck in ("SwitchableModeArtilleryModule", "DrumArtilleryModule"):
                        conf = module_data.get(ck)
                        if conf:
                            mn = "连发射击模式" if "Switchable" in ck else "弹鼓炮"
                            for lt in target_letters:
                                drum_configs[lt] = {"name": mn, "conf": conf}
                            break

        self._write_hulls(ship_id, raw_data, version_code=version_code)
        self._write_engine(ship_id, raw_data, version_code=version_code)
        self._scan_planes(raw_data, combined_stats)

        letters = sorted(combined_stats.keys())
        for letter in letters:
            cs = combined_stats[letter]
            self._write_hull_letter(ship_id, letter, raw_data, version_code=version_code)
            self._write_artillery(ship_id, letter, cs, drum_configs.get(letter), version_code=version_code)
            self._write_atba(ship_id, letter, cs, version_code=version_code)
            self._write_secondary_artillery(ship_id, letter, cs, version_code=version_code)
            self._write_torpedoes(ship_id, letter, cs, version_code=version_code)
            self._write_aa(ship_id, letter, cs, version_code=version_code)
            self._write_depth_charge(ship_id, letter, cs, version_code=version_code)
            self._write_aircraft(ship_id, letter, cs, version_code=version_code)
            self._write_air_support(ship_id, letter, cs, version_code=version_code)

        self._write_consumables(ship_id, raw_data, version_code=version_code)
        self._write_rage_mode(ship_id, raw_data, version_code=version_code)

        # 解析 ShipUpgradeInfo
        self._write_upgrade_info(ship_id, raw_data, version_code=version_code)

    # ── Ship 子写入器 ─────────────────────────────────────

    def _write_upgrade_info(self, ship_id: str, raw_data: dict, version_code: str = ""):
        """解析 ShipUpgradeInfo 并存入库，同时提取模块名称映射"""
        sui = raw_data.get("ShipUpgradeInfo")
        if not isinstance(sui, dict):
            return
        uc_type_map = {
            "PAUA": "_Artillery", "PAUE": "_Engine", "PAUH": "_Hull",
            "PAUS": "_Suo", "PAUT": "_Torpedoes",
        }
        # 收集所有出现的模块 ID，尝试从原始 JSON 中解析名称
        all_module_ids: set[str] = set()

        for upgrade_key, upgrade_val in sui.items():
            if not isinstance(upgrade_val, dict):
                continue
            prefix = upgrade_key[:4]
            uc_type = uc_type_map.get(prefix, upgrade_val.get("ucType", ""))
            components = upgrade_val.get("components", {})
            filtered = {k: v for k, v in components.items() if isinstance(v, list) and v}
            self.conn.execute(
                """INSERT OR REPLACE INTO ship_upgrade_info
                   (version_code, ship_id, upgrade_key, uc_type, components_json)
                   VALUES (?,?,?,?,?)""",
                (version_code, ship_id, upgrade_key, uc_type, json.dumps(filtered, ensure_ascii=False))
            )
            # 收集所有模块 ID
            for mods in filtered.values():
                for m in mods:
                    all_module_ids.add(m)

        # 尝试从原始 JSON 中为模块 ID 提取名称
        name_items = []
        for mid in all_module_ids:
            # 跳过系统内部名称
            if mid.endswith("Default") or mid in ("None", ""):
                continue
            # 跳过已有映射的
            existing = self.conn.execute(
                "SELECT 1 FROM name_mappings WHERE key_name=?",
                (mid.upper(),)).fetchone()
            if existing:
                continue
            # 尝试从原始 JSON 的对应 key 中找 name 字段
            mod_data = raw_data.get(mid)
            if isinstance(mod_data, dict):
                display_name = mod_data.get("name") or ""
                if display_name and display_name != mid:
                    name_items.append(("module_upgrade", mid.upper(), display_name))
        if name_items:
            try:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO name_mappings (category, key_name, lang_zh) VALUES (?,?,?)",
                    name_items)
                self.conn.commit()
            except Exception:
                pass

    def _write_hulls(self, ship_id: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        for mod_key, mod_data in raw_data.items():
            if not isinstance(mod_data, dict):
                continue
            m = MODULE_PATTERNS["Hull"].match(mod_key)
            if not m and mod_key != "Hull_A":
                continue
            letter = _extract_letter(mod_key)
            hull = mod_data.get("Hull", {})
            cit = mod_data.get("Cit", {})
            sub = mod_data.get("SubmarineBattery", {}) or {}
            hydro = mod_data.get("Hydrophone", {}) or {}
            conn.execute("""INSERT OR REPLACE INTO ship_module_hulls
                (version_code, ship_id, config_group, module_key, health, max_speed,
                 turning_radius, rudder_time, conceal_sea, conceal_air,
                 visibility_factor_by_plane, has_citadel,
                 hull_regen_part, citadel_regen_part, engine_power)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (version_code, ship_id, letter, mod_key,
                 mod_data.get("health"), mod_data.get("maxSpeed"),
                 _v(mod_data.get("turningRadius")),
                 _v(mod_data.get("rudderTime"), 0) * 0.77 if mod_data.get("rudderTime") else None,
                 mod_data.get("visibilityFactor"), mod_data.get("visibilityFactorByPlane"),
                 mod_data.get("visibilityFactorByPlane"),
                 _bn(mod_data.get("Cit")),
                 hull.get("regeneratedHPPart"), cit.get("regeneratedHPPart"),
                 mod_data.get("enginePower")))
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
                     _v(hydro.get("waveRadius"), 0) / 1000 if hydro.get("waveRadius") else None,
                     hydro.get("updateFrequency"),
                     _json_dumps(hydro.get("workingBuoyancyStates")),
                     _json_dumps(hydro.get("detectableBuoyancyStates")),
                     _v(mod_data.get("buoyancyRudderTime"), 0) * 0.77,
                     mod_data.get("maxBuoyancySpeed")))

    def _write_hull_letter(self, ship_id: str, letter: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        for mod_key, mod_data in raw_data.items():
            if not isinstance(mod_data, dict):
                continue
            m = MODULE_PATTERNS["Hull"].match(mod_key)
            if not m and mod_key != "Hull_A":
                continue
            if _extract_letter(mod_key) != letter:
                continue
            buoyancy = mod_data.get("buoyancyStates", {}) or {}
            rows = []
            for state, vals in buoyancy.items():
                if not isinstance(vals, (list, tuple)) or len(vals) < 2:
                    continue
                sp = vals[1] if len(vals) >= 2 else 1.0
                rows.append((version_code, ship_id, letter, mod_key, state, float(sp) if not isinstance(sp, (list, dict)) else 1.0))
            if rows:
                hp = conn.execute("SELECT 1 FROM ship_module_hulls_ext WHERE version_code=? AND ship_id=? AND config_group=? AND module_key=?",
                                  (version_code, ship_id, letter, mod_key)).fetchone()
                if hp:
                    conn.executemany("INSERT OR REPLACE INTO ship_sub_depth_states (version_code, ship_id, config_group, module_key, state_name, underwater_max_speed) VALUES (?,?,?,?,?,?)", rows)

    def _write_engine(self, ship_id: str, raw_data: dict, version_code: str = ""):
        eng = raw_data.get("EngineDefault") or {}
        if not eng:
            return
        hms = None
        for mk, md in raw_data.items():
            if isinstance(md, dict) and md.get("maxSpeed"):
                hms = md["maxSpeed"]
                break
        bs = hms * (1 + (_v(eng.get("backwardSpeedOnFlood"), 0))) if hms else None
        self.conn.execute("INSERT OR REPLACE INTO ship_module_engine (version_code, ship_id, config_group, module_key, engine_type, engine_power, forward_max_speed, backward_max_speed, forward_forsage_power, backward_forsage_power) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (version_code, ship_id, "A", "EngineDefault", eng.get("engineType"),
                           eng.get("histEnginePower") or eng.get("enginePower"),
                           hms, bs, eng.get("forwardEngineForsag") or eng.get("forwardEngineForsagMaxSpeed"),
                           eng.get("backwardEngineForsag") or eng.get("backwardEngineForsagMaxSpeed")))

    def _weapon_groups(self, items, *keys):
        g: dict = {}
        for item in items:
            k = tuple(item.get(k, "") for k in keys)
            g.setdefault(k, []).append(item)
        return g

    def _rel(self, sid, mid, st, lt, cnt=1, vc=""):
        self.conn.execute("INSERT OR REPLACE INTO ship_module_relations (version_code, ship_id, module_id, slot_type, config_group, mount_count) VALUES (?,?,?,?,?,?)", (vc, sid, mid, st, lt, cnt))

    def _ammo(self, sid, mid, st, lt, al, vc=""):
        if not al:
            return
        seen = set()
        for o, a in enumerate(al):
            if a not in seen:
                seen.add(a)
                self.conn.execute("INSERT OR REPLACE INTO ship_weapon_projectiles (version_code, ship_id, module_id, slot_type, config_group, ammo_id, ammo_order) VALUES (?,?,?,?,?,?,?)", (vc, sid, mid, st, lt, a, o))

    def _write_artillery(self, ship_id: str, letter: str, cs: dict, di: dict | None = None, version_code: str = ""):
        conn = self.conn
        sys = cs.get("Artillery_System", {})
        md = sys.get("max_dist", 0)
        sv = sys.get("sigma")
        for key, group in self._weapon_groups(cs.get("artillery", []), "gun_name").items():
            gn = key[0]
            cnt = len(group)
            r = group[0]
            br = _v(r.get("num_barrels"), 0)
            rt = r.get("reload_time")
            ir, mr, ide = r.get("ideal_radius", 0), r.get("min_radius", 0), r.get("ideal_distance", 0)
            em = md or r.get("max_dist", 0) or ide
            mr2 = em / 1000 if em else None
            conn.execute("INSERT OR REPLACE INTO ship_module_artillery (version_code, ship_id, config_group, module_key, count, num_barrels, reload_time, sigma, max_range, rotation_speed_h, rotation_speed_v, ideal_radius, min_radius, ideal_distance, radius_zero, radius_delim, radius_max, delim) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (version_code, ship_id, letter, gn, cnt, br, rt, sv, mr2,
                          r.get("rotation_speed_h"), r.get("rotation_speed_v"),
                          ir, mr, ide,
                          r.get("radius_zero", 0), r.get("radius_delim", 0), r.get("radius_max", 0), r.get("delim", 0)))
            self._rel(ship_id, gn, "artillery", letter, cnt, version_code)
            self._ammo(ship_id, gn, "artillery", letter, r.get("ammo_list", []), version_code)
            if di:
                c = di.get("conf", {})
                ctp = c.get("chargeTimeParams", [0, 0, 0])
                conn.execute("INSERT OR REPLACE INTO ship_module_artillery_ext (version_code, ship_id, config_group, module_key, special_mode_name, drum_shots_count, drum_shot_delay, drum_full_reload_time, drum_is_switchable, drum_is_chargeable, drum_charge_time_min, drum_charge_time_max, drum_charge_mode, drum_modifiers_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (version_code, ship_id, letter, gn, di.get("name", ""),
                              _v(c.get("shotsCount"), 0), _v(c.get("shotDelay"), 0),
                              _v(c.get("fullReloadTime"), 0),
                              _bn(c.get("isSwitchable")), _bn(c.get("isChargeable")),
                              ctp[0] if len(ctp) > 0 else 0, ctp[1] if len(ctp) > 1 else 0,
                              ctp[2] if len(ctp) > 2 else 0, _json_dumps(c.get("modifiers", {}))))

    def _write_atba(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        conn = self.conn
        sys = cs.get("ATBA_System", {})
        md = sys.get("max_dist", 0)
        sv = sys.get("sigma")
        for key, group in self._weapon_groups(cs.get("atba", []), "gun_name").items():
            gn = key[0]
            cnt = len(group)
            r = group[0]
            br = _v(r.get("num_barrels"), 0)
            rt = r.get("reload_time")
            ir, mr, ide = r.get("ideal_radius", 0), r.get("min_radius", 0), r.get("ideal_distance", 0)
            em = md or r.get("max_dist", 0) or ide
            mr2 = em / 1000 if em else None
            conn.execute("INSERT OR REPLACE INTO ship_module_atba (version_code, ship_id, config_group, module_key, count, num_barrels, reload_time, sigma, max_range, ideal_radius, min_radius, ideal_distance, radius_zero, radius_delim, radius_max, delim) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (version_code, ship_id, letter, gn, cnt, br, rt, sv, mr2,
                          ir, mr, ide,
                          r.get("radius_zero", 0), r.get("radius_delim", 0), r.get("radius_max", 0), r.get("delim", 0)))
            self._rel(ship_id, gn, "atba", letter, cnt, version_code)
            self._ammo(ship_id, gn, "atba", letter, r.get("ammo_list", []), version_code)

    def _write_secondary_artillery(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        """将 SecondaryArtillery（第二主炮）写入独立表 ship_module_secondary_artillery"""
        conn = self.conn
        sys = cs.get("SecondaryArtillery_System", {})
        md = sys.get("max_dist", 0)
        sv = sys.get("sigma")
        for key, group in self._weapon_groups(cs.get("secondary_artillery", []), "gun_name").items():
            gn = key[0]
            cnt = len(group)
            r = group[0]
            br = _v(r.get("num_barrels"), 0)
            rt = r.get("reload_time")
            ir, mr, ide = r.get("ideal_radius", 0), r.get("min_radius", 0), r.get("ideal_distance", 0)
            em = md or r.get("max_dist", 0) or ide
            mr2 = em / 1000 if em else None
            conn.execute("INSERT OR REPLACE INTO ship_module_secondary_artillery (version_code, ship_id, config_group, module_key, count, num_barrels, reload_time, sigma, max_range, rotation_speed_h, rotation_speed_v, ideal_radius, min_radius, ideal_distance, radius_zero, radius_delim, radius_max, delim, caliber) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (version_code, ship_id, letter, gn, cnt, br, rt, sv, mr2,
                          r.get("rotation_speed_h"), r.get("rotation_speed_v"),
                          ir, mr, ide,
                          r.get("radius_zero", 0), r.get("radius_delim", 0), r.get("radius_max", 0), r.get("delim", 0),
                          r.get("caliber", 0)))
            self._rel(ship_id, gn, "secondary_artillery", letter, cnt, version_code)
            self._ammo(ship_id, gn, "secondary_artillery", letter, r.get("ammo_list", []), version_code)

    def _write_torpedoes(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        conn = self.conn
        for key, group in self._weapon_groups(cs.get("torpedoes", []), "launcher_name").items():
            nm = key[0]
            cnt = len(group)
            r = group[0]
            conn.execute("INSERT OR REPLACE INTO ship_module_torpedoes (version_code, ship_id, config_group, module_key, count, num_barrels, reload_time) VALUES (?,?,?,?,?,?,?)",
                         (version_code, ship_id, letter, nm, cnt, _v(r.get("num_barrels"), 0), r.get("reload_time")))
            self._rel(ship_id, nm, "torpedo", letter, cnt, version_code)
            self._ammo(ship_id, nm, "torpedo", letter, r.get("ammo_list", []), version_code)

    def _write_aa(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        conn = self.conn
        items = cs.get("aa", [])
        if not items:
            return
        # 先清除旧数据（避免 NULL 在复合主键中导致重复行）
        conn.execute(
            "DELETE FROM ship_module_aa WHERE version_code=? AND ship_id=? AND config_group=?",
            (version_code, ship_id, letter))
        ac, gc = Counter(), Counter()
        for item in items:
            if item.get("aura_name"):
                ac[(item["aura_name"], item["aura_type"], item["aura_dps"], item.get("bubble_damage"))] += 1
            elif item.get("aa_gun_name"):
                gc[item["aa_gun_name"]] += 1
        rows = []
        for (n, t, d, bd), c in ac.items():
            # 取第一个匹配项的扩展字段
            src = next((i for i in items if i.get("aura_name") == n), {})
            rows.append((version_code, ship_id, letter, n, n, src.get("aura_type_raw", ""), t, d, bd,
                         src.get("explosion_count"), src.get("hit_chance"),
                         src.get("max_distance"), src.get("min_distance"),
                         None, c))
        for gn, c in gc.items():
            rows.append((version_code, ship_id, letter, gn, None, None, None, None, None, None, None, None, None, gn, c))
        if rows:
            conn.executemany("INSERT OR REPLACE INTO ship_module_aa (version_code, ship_id, config_group, module_key, aura_name, type, aura_type, aura_dps, bubble_damage, explosion_count, hit_chance, max_distance, min_distance, aa_gun_name, aa_gun_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            for row in rows:
                self._rel(ship_id, row[3], "airDefense", letter, 1, version_code)

    def _write_depth_charge(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        conn = self.conn
        items = cs.get("depth_charge", [])
        if not items:
            return
        conn.execute(
            "DELETE FROM ship_module_depth_charge WHERE version_code=? AND ship_id=? AND config_group=?",
            (version_code, ship_id, letter))
        rows = []
        for item in items:
            gn = item.get("gun_name")
            if not gn:
                continue
            cnt = item.get("count", 0) or 0
            aid = item.get("ammo_id")
            # 查询弹药扩展数据
            de = None
            if aid:
                de = conn.execute(
                    "SELECT damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size "
                    "FROM projectile_depth_charge_ext WHERE version_code=? AND projectile_id=?",
                    (version_code, aid)).fetchone()
            rows.append((
                version_code, ship_id, letter, gn, gn, cnt,
                _v(item.get("reload_time")), _v(item.get("shot_delay")),
                item.get("max_packs"), item.get("num_shots"),
                item.get("num_bombs"),
                aid,
                de["damage"] if de else None,
                de["dc_speed"] if de else None,
                de["dc_timer"] if de else None,
                de["dc_max_depth"] if de else None,
                de["depth_splash_size"] if de else None,
            ))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO ship_module_depth_charge "
                "(version_code, ship_id, config_group, module_key, gun_name, count, "
                "reload_time, shot_delay, max_packs, num_shots, num_bombs, "
                "projectile_id, damage, dc_speed, dc_timer, dc_max_depth, depth_splash_size) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            for row in rows:
                self._rel(ship_id, row[3], "depthCharge", letter, 1, version_code)

    def _write_aircraft(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        items = cs.get("aircraft", [])
        if not items:
            return
        self.conn.executemany("INSERT OR REPLACE INTO ship_module_aircraft (version_code, ship_id, config_group, module_key, module_variant, plane_type, plane_name, armament_name) VALUES (?,?,?,?,?,?,?,?)",
                              [(version_code, ship_id, i.get("config_prefix", letter), i.get("plane_name") or "", i.get("module_variant", ""), i.get("plane_type", ""), i.get("plane_name"), i.get("armament_name")) for i in items])
        seen = set()
        for i in items:
            pn = i.get("plane_name") or ""
            if pn and (version_code, ship_id, pn) not in seen:
                seen.add((version_code, ship_id, pn))
                self._rel(ship_id, pn, "aircraft", letter, 1, version_code)

    def _write_air_support(self, ship_id: str, letter: str, cs: dict, version_code: str = ""):
        items = cs.get("air_support", [])
        if not items:
            return
        self.conn.executemany("INSERT OR REPLACE INTO ship_module_air_support (version_code, ship_id, config_group, module_key, plane_name, charges, reload_time, work_time, max_range, min_range, armament_name, support_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                              [(version_code, ship_id, letter, i.get("plane_name") or "", i.get("plane_name"), i.get("charges"), i.get("reload_time"), i.get("work_time"), i.get("max_range"), i.get("min_range"), i.get("armament_name"), i.get("support_type", "")) for i in items])
        seen = set()
        for i in items:
            pn = i.get("plane_name") or ""
            if pn and (version_code, ship_id, pn) not in seen:
                seen.add((version_code, ship_id, pn))
                self._rel(ship_id, pn, "airSupport", letter, 1, version_code)

    def _find_armament(self, plane_id: str) -> str:
        r = self.conn.execute("SELECT armament_name FROM ship_module_aircraft WHERE plane_name=? LIMIT 1", (plane_id,)).fetchone()
        return r[0] if r else ""

    def _scan_planes(self, raw_data: dict, cs: dict):
        for key, val in raw_data.items():
            if not isinstance(val, dict) or any(p.match(key) for p in MODULE_PATTERNS.values()):
                continue
            if "planes" in val or PLANE_PREFIX_RE.match(key):
                lt = "A" if not (key.startswith("A_") or key.startswith("B_")) else key[0]
                cs.setdefault(lt, {}).setdefault("aircraft", []).append(
                    {"plane_name": key, "armament_name": "", "module_variant": "", "plane_type": "",
                     "config_prefix": lt})

    def _write_consumables(self, ship_id: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        abilities = raw_data.get("ShipAbilities", {}) or {}
        rows = []
        for sk in sorted(abilities.keys()):
            sd = abilities[sk]
            si = 1
            m = re.search(r'\d+', sk)
            if m:
                si = int(m.group()) + 1
            for i, ap in enumerate(sd.get("abils", []) or []):
                if not (isinstance(ap, (list, tuple)) and len(ap) >= 2):
                    continue
                fk, ck = str(ap[0]).strip(), str(ap[1]).strip()
                rows.append((version_code, ship_id, si, i + 1, fk, ck))
        if rows:
            conn.executemany("""INSERT OR REPLACE INTO ship_consumable_slots
                (version_code, ship_id, slot_index, item_index, display_name_id, consumable_id, config_key)
                VALUES (?,?,?,?,(SELECT id FROM name_mappings WHERE category='consumable' AND key_name=?),?,?)""",
                             [(r[0], r[1], r[2], r[3], r[4].upper(), r[4], r[5]) for r in rows])

    _cfg_cache: dict[str, dict] = {}

    def _load_cfg(self, file_key: str, config_key: str) -> dict:
        ck = f"{file_key}::{config_key}"
        if ck not in self._cfg_cache:
            r = self.conn.execute("SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key=?", (file_key, config_key)).fetchone()
            if not r:
                r = self.conn.execute("SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key='Default'", (file_key,)).fetchone()
            self._cfg_cache[ck] = dict(r) if r else None
        return self._cfg_cache[ck]

    def _write_rage_mode(self, ship_id: str, raw_data: dict, version_code: str = ""):
        rage = (raw_data.get("A_Specials") or {}).get("RageMode", {}) if isinstance(raw_data.get("A_Specials"), dict) else {}
        if not rage:
            return
        triggers = []
        for k in sorted(rage.keys()):
            if "Trigger" in k and isinstance(rage[k], dict):
                triggers.append({k: rage[k]})
        # 构造 display_name msgid 并查询 name_mappings id
        raw_name = str(rage.get("rageModeName", "")).upper()
        base_msgid = f"IDS_DOCK_RAGE_MODE_TITLE_{raw_name}" if raw_name else ""
        # 构造 descriptionIDS msgid
        desc_ids = rage.get("descriptionIDS", "")
        desc_msgid = str(desc_ids).upper() if desc_ids else ""
        self.conn.execute("""INSERT OR REPLACE INTO ship_rage_mode
            (version_code, ship_id, display_name_id, boost_duration, max_activation_count,
             is_auto_usage, is_modifier_works_always, decrement_delay, decrement_period, decrement_count,
             description_id, rage_mode_name, modifiers_json, triggers_json)
            VALUES (?,?,(SELECT id FROM name_mappings WHERE category='rage_mode' AND key_name=?),?,?,?,?,?,?,?,
                    (SELECT id FROM name_mappings WHERE category='rage_mode' AND key_name=?),?,?,?)""",
                          (version_code, ship_id, base_msgid, _v(rage.get("boostDuration"), 0),
                           str(rage.get("maxActivationCount", 0)),
                           _bn(rage.get("isAutoUsage")), _bn(rage.get("isModifierWorksAlways")),
                           _v(rage.get("decrementDelay"), 0), _v(rage.get("decrementPeriod"), 0),
                           _v(rage.get("decrementCount"), 0), desc_msgid,
                           base_msgid, _json_dumps(rage.get("modifiers", {})), _json_dumps(triggers)))
    def store_projectile(self, proj_id: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        species = raw_data.get("typeinfo", {}).get("species", "")
        ammo_type = raw_data.get("ammoType", "")
        conn.execute("INSERT OR REPLACE INTO projectile_basic_info (version_code, projectile_id, projectile_index, projectile_id_num, species, ammo_type, custom_ui_postfix) VALUES (?,?,?,?,?,?,?)",
                     (version_code, proj_id, raw_data.get("index", proj_id), _i(raw_data.get("id")), species, ammo_type, raw_data.get("customUIPostfix", "")))
        sk = species if species in PROJECTILE_EXT_MAP else ("SkipBomb" if species == "SkipBomb" else None)
        if sk:
            ei = PROJECTILE_EXT_MAP[sk]
            vals = [self._gf(raw_data, f) for f in ei["fields"]]
            conn.execute(f"INSERT OR REPLACE INTO {ei['table']} (version_code, projectile_id, {ei['cols']}) VALUES (?,?,{','.join(['?']*ei['phs'])})",
                         (version_code, proj_id, *vals))
        if species == "Torpedo":
            stp = raw_data.get("SubmarineTorpedoParams") or {}
            if stp or raw_data.get("searchRadius") is not None:
                g = stp if isinstance(stp, dict) else {}
                dr = g.get("dropTargetAtDistance") or {}
                conn.execute("INSERT OR REPLACE INTO projectile_torpedo_sub_guidance_ext (version_code, projectile_id, search_radius, search_angle, max_depth_level, max_vertical_speed, max_yaw, target_lost_degradation_time, drop_dist_aircarrier, drop_dist_battleship, drop_dist_cruiser, drop_dist_destroyer, drop_dist_submarine, drop_dist_default) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (version_code, proj_id,
                              _unwrap(g.get("searchRadius")) or raw_data.get("searchRadius"),
                              _unwrap(g.get("searchAngle")) or raw_data.get("searchAngle"),
                              _unwrap(g.get("maxDepthLevel")) or raw_data.get("maxDepthLevel"),
                              _unwrap(g.get("maxVerticalSpeed")) or raw_data.get("maxVerticalSpeed"),
                              _unwrap(g.get("maxYaw")) or raw_data.get("maxYaw"),
                              _unwrap(g.get("targetLostDegradationTime")) or raw_data.get("targetLostDegradationTime"),
                              _unwrap(dr.get("AirCarrier")) or raw_data.get("dropDistAircraftCarrier"),
                              _unwrap(dr.get("Battleship")) or raw_data.get("dropDistBattleship"),
                              _unwrap(dr.get("Cruiser")) or raw_data.get("dropDistCruiser"),
                              _unwrap(dr.get("Destroyer")) or raw_data.get("dropDistDestroyer"),
                              _unwrap(dr.get("Submarine")) or raw_data.get("dropDistSubmarine"),
                              _unwrap(dr.get("default")) or raw_data.get("dropDistDefault")))

    # ── 4. Aircraft ──────────────────────────────────────

    def store_plane(self, plane_id: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        ti = raw_data.get("typeinfo", {}) or {}
        # 核心字段（CV 飞机用 maxHealth 替代 hp）
        raw_hp = raw_data.get("hp") or raw_data.get("maxHealth")
        core = {
            "maxSpeed": raw_data.get("maxSpeed"),
            "cruisingSpeed": raw_data.get("cruisingSpeed"),
            "hp": raw_hp,
            "attackCount": raw_data.get("attackCount"),
            "attackCooldown": raw_data.get("attackCooldown"),
            "attackInterval": raw_data.get("attackInterval"),
            "arrangeSize": raw_data.get("arrangeSize"),
            "canDestroy": raw_data.get("canDestroy"),
            "canStop": raw_data.get("canStop"),
            "bombName": raw_data.get("bombName"),
        }
        SKIP = {"typeinfo", "custom", "ShipAbilities", "PlaneAbilities"} | set(core.keys())
        extra = {k: v for k, v in raw_data.items()
                 if k not in SKIP and not k.startswith("_")}
        # 从 extra 中提取结构化字段
        hs = raw_data.get("hangarSettings") or {}
        sql = ("INSERT OR REPLACE INTO plane_basic_info "
               "(version_code, plane_id, plane_index, plane_id_num, species, nation, plane_level, "
               "max_speed, cruising_speed, hp, attack_count, attack_cooldown, "
               "attack_interval, arrange_size, can_destroy, can_stop, bomb_name, "
               "speed_move_with_bomb, speed_max_mult, speed_min_mult, "
               "angle_of_climb, angle_of_dive, attack_angle, "
               "preparation_time, preparation_accel_increase, preparation_accel_decrease, "
               "aiming_time, aiming_accel_increase, aiming_accel_decrease, flight_height, "
               "attacker_size, num_planes_in_squadron, fuel_time, max_forsage_amount, "
               "hangar_max_value, hangar_start_value, hangar_restore_amount, hangar_time_to_restore, "
               "outer_salvo_size_x, outer_salvo_size_y, "
               "inner_salvo_size_x, inner_salvo_size_y, "
               "max_spread_x, max_spread_y, min_spread_x, min_spread_y, "
               "max_spread, min_spread, "
               "inner_bombs_percentage, visibility_factor, "
               "skip_height, aiming_height, "
               "post_attack_invulnerability_duration, "
               "ability_slot_0, ability_slot_1, ability_slot_2, ability_slot_3, ability_slot_4) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
               "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
               "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
               "?,?,?,?,?,?,?,?)")
        conn.execute(sql,
                     (version_code, plane_id,
                      raw_data.get("index", plane_id), _i(raw_data.get("id")),
                      ti.get("species", ""), ti.get("nation", ""),
                      _i(raw_data.get("level")),
                      _v(core["maxSpeed"]), _v(core["cruisingSpeed"]), _v(core["hp"]),
                      _i(core["attackCount"]), _v(core["attackCooldown"]),
                      _v(core["attackInterval"]), _i(core["arrangeSize"]),
                      core["canDestroy"] if core["canDestroy"] is not None else 1,
                      _bn(core["canStop"]), core["bombName"] or "",
                      _v(raw_data.get("speedMoveWithBomb")),
                      _v(raw_data.get("speedMax")),
                      _v(raw_data.get("speedMin")),
                      _v(raw_data.get("angleOfClimb")),
                      _v(raw_data.get("angleOfDive")),
                      _v(raw_data.get("attackAngle")),
                      _v(raw_data.get("preparationTime")),
                      _v(raw_data.get("preparationAccuracyIncreaseRate")),
                      _v(raw_data.get("preparationAccuracyDecreaseRate")),
                      _v(raw_data.get("aimingTime")),
                      _v(raw_data.get("aimingAccuracyIncreaseRate")),
                      _v(raw_data.get("aimingAccuracyDecreaseRate")),
                      _v(raw_data.get("flightHeight")),
                      _i(raw_data.get("attackerSize")),
                      _i(raw_data.get("numPlanesInSquadron")),
                      _v(raw_data.get("fuelTime")),
                      _v(raw_data.get("maxForsageAmount")),
                      _i(hs.get("maxValue")), _i(hs.get("startValue")),
                      _i(hs.get("restoreAmount")), _v(hs.get("timeToRestore")),
                      _unwrap_list(raw_data.get("outerSalvoSize"), 0),
                      _unwrap_list(raw_data.get("outerSalvoSize"), 1),
                      _unwrap_list(raw_data.get("innerSalvoSize"), 0),
                      _unwrap_list(raw_data.get("innerSalvoSize"), 1),
                      _unwrap_list(raw_data.get("maxSpread"), 0),
                      _unwrap_list(raw_data.get("maxSpread"), 1),
                      _unwrap_list(raw_data.get("minSpread"), 0),
                      _unwrap_list(raw_data.get("minSpread"), 1),
                      _v(raw_data.get("maxSpread")) if not isinstance(raw_data.get("maxSpread"), (list, tuple)) else None,
                      _v(raw_data.get("minSpread")) if not isinstance(raw_data.get("minSpread"), (list, tuple)) else None,
                      _v(raw_data.get("innerBombsPercentage")),
                      _v(raw_data.get("visibilityFactor")),
                      _v(raw_data.get("skipHeight")),
                      _v(raw_data.get("aimingHeight")),
                      _v(raw_data.get("postAttackInvulnerabilityDuration")),
                      _ability_str(raw_data.get("PlaneAbilities"), 0),
                      _ability_str(raw_data.get("PlaneAbilities"), 1),
                      _ability_str(raw_data.get("PlaneAbilities"), 2),
                      _ability_str(raw_data.get("PlaneAbilities"), 3),
_ability_str(raw_data.get("PlaneAbilities"), 4)))

    # ── 5. Ability ───────────────────────────────────────

    def store_consumable(self, cid: str, raw_data: dict, result=None, version_code: str = ""):
        conn = self.conn
        conn.execute("INSERT OR REPLACE INTO consumable_basic_info (version_code, consumable_id, consumable_index, consumable_id_num) VALUES (?,?,?,?)",
                     (version_code, cid, raw_data.get("index", cid), _i(raw_data.get("id"))))
        SKIP_KEYS = {"typeinfo", "custom", "ShipAbilities", "PlaneAbilities"}
        rows = []
        for key, val in raw_data.items():
            if not isinstance(val, dict) or key in SKIP_KEYS:
                continue
            ct = val.get("consumableType")
            if not ct:
                continue
            extra = {k: v for k, v in val.items() if k not in SKIP_KEYS}
            rows.append((version_code, cid, key, ct, _json_dumps(extra)))
        if rows:
            conn.executemany("INSERT OR REPLACE INTO consumable_configs (version_code, consumable_id, config_key, consumable_type, extra_json) VALUES (?,?,?,?,?)", rows)

    # ── 6. Modernization ─────────────────────────────────

    def store_mod(self, mod_id: str, raw_data: dict, result=None, version_code: str = ""):
        conn = self.conn
        conn.execute("""INSERT OR REPLACE INTO modernization_basic_info
            (version_code, mod_id, mod_index, mod_id_num, name,
             cost_cr, slot, rarity, sort_index,
             modifiers_json, excludes_json, ships_json,
             groups_json, nations_json, shiptype_json, shiplevel_json, tags_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (version_code, mod_id,
                      raw_data.get("index", mod_id), _i(raw_data.get("id")),
                      raw_data.get("name", ""),
                      raw_data.get("costCR", 0), raw_data.get("slot", 0),
                      raw_data.get("rarity", 0), raw_data.get("sortIndex", 0),
                      _json_dumps(raw_data.get("modifiers", {})),
                      _json_dumps(raw_data.get("excludes", [])),
                      _json_dumps(raw_data.get("ships", [])),
                      _json_dumps(raw_data.get("group", [])),
                      _json_dumps(raw_data.get("nation", [])),
                      _json_dumps(raw_data.get("shiptype", [])),
                      _json_dumps(raw_data.get("shiplevel", [])),
                      _json_dumps(raw_data.get("tags", []))))

    # ── 7. Crew ──────────────────────────────────────────

    def store_crew(self, crew_id: str, raw_data: dict, version_code: str = ""):
        conn = self.conn
        pers = raw_data.get("CrewPersonality", {}) or {}
        conn.execute("""INSERT OR REPLACE INTO crew_basic_info
            (version_code, crew_id, display_name_id, crew_index, crew_id_num, person_name, nation,
             is_unique, is_animated, is_elite, is_person, is_retrainable, skills_container, base_training_level)
            VALUES (?,?,(SELECT id FROM name_mappings WHERE category='crew' AND key_name=?),?,?,?,?,?,?,?,?,?,?,?)""",
                     (version_code, crew_id, crew_id.upper(),
                      raw_data.get("index", crew_id), _i(raw_data.get("id")),
                      pers.get("personName", ""), raw_data.get("typeinfo", {}).get("nation", ""),
                      _bn(pers.get("isUnique")), _bn(pers.get("isAnimated")),
                      _bn(pers.get("isElite")), _bn(pers.get("isPerson")),
                      _bn(pers.get("isRetrainable")), raw_data.get("skillsContainer"),
                      _v(raw_data.get("baseTrainingLevel"), 1)))
        unique = raw_data.get("UniqueSkills", {}) or {}
        MK = {"triggerIsSubRibbons", "triggerJoinRibbons", "triggerRibbonsTypes"}
        for sk, sv in unique.items():
            if not isinstance(sv, dict):
                continue
            eff = {ek: ev for ek, ev in sv.items() if ek not in MK and isinstance(ev, dict)}
            conn.execute("INSERT OR REPLACE INTO crew_unique_skills (version_code, crew_id, skill_key, sort_index, trigger_type, max_trigger_num, trigger_achievement, trigger_damage_num, trigger_damage_type, damage_percent_threshold, trigger_ribbons_num, trigger_ribbon_types, trigger_allowed_ships, effects_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (version_code, crew_id, sk, _v(sv.get("sortIndex"), 0),
                          sv.get("triggerType"), sv.get("maxTriggerNum"),
                          sv.get("triggerAchievement"), sv.get("triggerDamageNum"),
                          sv.get("triggerDamageType"), sv.get("damagePercentThreshold"),
                          sv.get("triggerRibbonsNum"),
                          str(sv.get("triggerRibbonsTypes", [])),
                          str(sv.get("triggerAllowedShips") or sv.get("triggerAllowedShipTypes") or ""),
                          _json_dumps(eff)))


# ═════════════════════════════════════════════════════════════════════
# AnalysisService —— 分析编排器
# ═════════════════════════════════════════════════════════════════════

class AnalysisService:
    """分析服务——从 split JSON 读取数据并写入结构化表"""

    def __init__(self):
        self._ready = True

    def initialize(self) -> None:
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return self._ready

    def analyze_one(self, category: str, raw_data: dict, entity_id: str = "",
                    db: DatabaseManager | None = None, version_code: str = ""):
        version_code = str(version_code).strip() if version_code else ""
        from services.database_service import get_db as _get_db
        store = AnalysisStore(db or _get_db())
        func_map = {
            "Ship": store.store_ship, "Projectile": store.store_projectile,
            "Aircraft": store.store_plane, "Ability": store.store_consumable,
            "Modernization": store.store_mod, "Crew": store.store_crew,
        }
        m = func_map.get(category)
        if not m:
            return
        try:
            if category in ("Ability", "Modernization"):
                m(entity_id, raw_data, None, version_code=version_code)
            else:
                m(entity_id, raw_data, version_code=version_code)
        except Exception as e:
            bus.log_message.emit(f"⚠️ [分析] {category}/{entity_id} 失败: {e}")

    def precompute_all(self, db: DatabaseManager,
                       data_by_category: dict[str, dict[str, dict]] | None = None,
                       version_code: str = "") -> dict:
        results: dict[str, int] = {}
        total_processed = 0
        split_dir = get_split_dir()
        categories = ["Projectile", "Aircraft", "Ability", "Ship", "Modernization", "Crew"]
        raw_conn = db._conn

        def _process_batch(items):
            nonlocal total_processed
            try:
                raw_conn.execute("COMMIT")
            except Exception:
                pass
            raw_conn.execute("BEGIN TRANSACTION")
            success = 0
            for entity_id, raw_data in items:
                self.analyze_one(cat_name, raw_data, entity_id, db, version_code=version_code)
                success += 1
                total_processed += 1
            raw_conn.commit()
            return success

        use_memory = data_by_category is not None

        if use_memory:
            total_entities = sum(len(v) for v in data_by_category.values())
            if total_entities == 0:
                return results
            bus.task_progress.emit(80, "步骤 3/3: 预分析数据")
            for cat_name in categories:
                cd = data_by_category.get(cat_name)
                if not cd:
                    results[cat_name] = 0
                    continue
                items = sorted(cd.items())
                results[cat_name] = _process_batch(items)
            bus.task_progress.emit(95, f"步骤 3/3: 分析完成: {total_processed} 实体")
        else:
            if not split_dir.exists():
                bus.log_message.emit("⏳ split 目录不存在，跳过预分析")
                return results
            total_entities = sum(len(list((split_dir / c).glob("*.json"))) for c in categories if (split_dir / c).exists())
            if total_entities == 0:
                return results
            bus.task_progress.emit(80, "步骤 3/3: 预分析数据")
            for cat_name in categories:
                cat_dir = split_dir / cat_name
                if not cat_dir.exists():
                    results[cat_name] = 0
                    continue
                fps = sorted(cat_dir.glob("*.json"))
                items = []
                for fp in fps:
                    try:
                        items.append((fp.stem, json.loads(fp.read_text(encoding="utf-8"))))
                    except Exception:
                        continue
                results[cat_name] = _process_batch(items)
            bus.task_progress.emit(95, f"步骤 3/3: 分析完成: {total_processed} 实体")

        return results
