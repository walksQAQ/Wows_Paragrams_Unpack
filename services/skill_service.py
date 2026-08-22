"""
SkillService —— 指挥官技能数据服务（数据库驱动）。

数据来源：
- crew_skill_definitions: PCOK 技能效果定义
- crew_skill_containers: PCOL 技能容器（标记哪些技能在指定舰种上是 EPIC）
"""

from __future__ import annotations

import json
from typing import Optional

from services.database_service import get_db


class SkillService:
    """技能数据服务（单例，读取数据库）"""

    _instance: Optional["SkillService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._ship_type_map = {
            "航母": "AirCarrier", "战列舰": "Battleship", "巡洋舰": "Cruiser",
            "驱逐舰": "Destroyer", "潜艇": "Submarine", "通用": "",
        }
        self._reverse_type_map = {v: k for k, v in self._ship_type_map.items() if v}
        self._rarity_order = {"COMMON": 0, "REGULAR": 1, "RARE": 2, "EPIC": 3, "LEGENDARY": 4}
        # skill_key 集合缓存（按 version_code），避免 _icon_to_skill_key 每次全表查询
        self._skill_keys_cache: dict[str, list[str]] = {}
        self._grid_map = {
            "航母": {
                "1-1": "planes_forsage_renewal", "1-2": "planes_forsage_duration",
                "1-3": "planes_consumables_speedbooster_reload", "1-4": "planes_reload",
                "1-5": "consumables_fighter_additional", "1-6": "planes_consumables_callfighters_range",
                "2-1": "planes_torpedo_armingrange", "2-2": "planes_torpedo_speed",
                "2-3": "planes_speed", "2-4": "planes_consumables_regeneratehealth_upgrade",
                "2-5": "aa_damage_constant_bubbles_cv", "2-6": "planes_consumables_callfighters_additional",
                "3-1": "planes_aiming_boost", "3-2": "planes_ap_damage",
                "3-3": "he_fire_probability_cv", "3-4": "planes_defense_damage_constant",
                "3-5": "planes_hp", "3-6": "extra_call_fighters",
                "4-1": "planes_divebomber_speed", "4-2": "planes_torpedo_uw_reduced",
                "4-3": "atba_upgrade", "4-4": "planes_defense_damage_bubbles",
                "4-5": "detection_visibility_crashcrew", "4-6": "planes_consumables_callfighters_preparationtime",
            },
            "战列舰": {
                "1-1": "gm_shell_reload", "1-2": "he_fire_probability",
                "1-3": "consumables_reload", "1-4": "consumables_crashcrew_regencrew_reload",
                "1-5": "detection_alert", "1-6": "defense_crit_probability",
                "2-1": "gm_turn", "2-2": "he_penetration",
                "2-3": "trigger_speed_bb", "2-4": "detection_torpedo_range",
                "2-5": "detection_aiming", "2-6": "aa_damage_constant_bubbles",
                "3-1": "ap_damage_bb", "3-2": "atba_range",
                "3-3": "armament_reload_aa_damage", "3-4": "defence_crit_fire_flooding",
                "3-5": "defence_uw", "3-6": "aa_prioritysector_damage_constant",
                "4-1": "trigger_burn_gm_reload", "4-2": "atba_accuracy",
                "4-3": "trigger_gm_atba_reload_bb", "4-4": "consumables_crashcrew_regencrew_upgrade",
                "4-5": "detection_visibility_range", "4-6": "defence_fire_probability",
            },
            "巡洋舰": {
                "1-1": "gm_turn", "1-2": "torpedo_speed",
                "1-3": "consumables_reload", "1-4": "gm_shell_reload",
                "1-5": "detection_alert", "1-6": "maneuverability",
                "2-1": "he_fire_probability", "2-2": "torpedo_reload",
                "2-3": "consumables_duration", "2-4": "consumables_spotter_upgrade",
                "2-5": "detection_aiming", "2-6": "aa_prioritysector_damage_constant",
                "3-1": "he_sap_damage", "3-2": "torpedo_damage",
                "3-3": "armament_reload_aa_damage", "3-4": "ap_damage_ca",
                "3-5": "consumables_additional", "3-6": "defense_hp",
                "4-1": "trigger_gm_atba_reload_ca", "4-2": "trigger_speed_accuracy",
                "4-3": "detection_direction", "4-4": "he_penetration",
                "4-5": "detection_visibility_range", "4-6": "aa_damage_constant_bubbles",
            },
            "驱逐舰": {
                "1-1": "gm_turn", "1-2": "torpedo_flooding_probability",
                "1-3": "consumables_reload", "1-4": "detection_aiming",
                "1-5": "detection_alert", "1-6": "defense_crit_probability",
                "2-1": "he_fire_probability", "2-2": "torpedo_speed",
                "2-3": "consumables_duration", "2-4": "ap_damage_dd",
                "2-5": "he_penetration", "2-6": "maneuverability",
                "3-1": "gm_reload_aa_damage_constant", "3-2": "torpedo_reload",
                "3-3": "armament_reload_aa_damage", "3-4": "trigger_spreading",
                "3-5": "consumables_additional", "3-6": "defense_hp",
                "4-1": "gm_range_aa_damage_bubbles", "4-2": "trigger_speed",
                "4-3": "detection_direction", "4-4": "trigger_gm_reload",
                "4-5": "detection_visibility_range", "4-6": "trigger_torpedo_speed_reload",
            },
            "潜艇": {
                "1-1": "pinger_speed_buff", "1-2": "torpedo_flooding_probability",
                "1-3": "defense_crit_probability", "1-4": "gun_main_shot_delay",
                "1-5": "smoke_screen_setter", "1-6": "shoot_shift_bonus",
                "2-1": "submarine_battery_capacity", "2-2": "trigger_seen_torpedo_reload",
                "2-3": "trigger_cons_rudder_time_coeff", "2-4": "depth_charge_bomber_alert",
                "2-5": "maneuverability", "2-6": "trigger_hydrophone_zone",
                "3-1": "submarine_speed_on_buoyancy", "3-2": "acoustic_specialist",
                "3-3": "submarine_consumables_reload", "3-4": "submarine_danger_alert",
                "3-5": "consumables_additional", "3-6": "submarine_defense_hp",
                "4-1": "armament_reload_submarine", "4-2": "submarine_torpedo_damage",
                "4-3": "submarine_vulnerability_depth_bomb", "4-4": "submarine_speed",
                "4-5": "submarine_battery_burn_down", "4-6": "buoyancy_speed",
            },
        }

        # ── WG 服舰长技能位置映射（与 Lesta 位置不同，人工按 WG 实测填充）──
        # 潜艇 4 行 5 列；其他舰种 4 行 6 列。
        # 格式：{"row-col": "icon_name"}，如 "1-1": "gm_shell_reload"
        # ⚠️ 当前为空占位（由人工填充 WG 技能位置后生效）
        self._wg_grid_map = {
            "航母": {
                "1-1": "planes_forsage_renewal", "1-2": "planes_forsage_duration",
                "1-3": "planes_consumables_speedbooster_reload", "1-4": "planes_reload",
                "1-5": "consumables_fighter_additional", "1-6": "planes_consumables_callfighters_range",
                "2-1": "planes_torpedo_armingrange", "2-2": "planes_torpedo_speed",
                "2-3": "planes_speed", "2-4": "planes_consumables_active_maneuvering_upgrade",
                "2-5": "aa_damage_constant_bubbles_cv", "2-6": "planes_consumables_callfighters_additional",
                "3-1": "planes_aiming_boost", "3-2": "planes_ap_damage",
                "3-3": "he_fire_probability_cv", "3-4": "planes_defense_damage_constant",
                "3-5": "planes_hp", "3-6": "planes_consumables_callfighters_upgrade",
                "4-1": "planes_divebomber_speed", "4-2": "planes_torpedo_uw_reduced",
                "4-3": "atba_upgrade", "4-4": "planes_defense_damage_bubbles",
                "4-5": "detection_visibility_crashcrew", "4-6": "planes_consumables_callfighters_preparationtime",
            },
            "战列舰": {
                "1-1": "gm_shell_reload", "1-2": "he_fire_probability",
                "1-3": "consumables_reload", "1-4": "consumables_crashcrew_regencrew_reload",
                "1-5": "detection_alert", "1-6": "defense_crit_probability",
                "2-1": "gm_turn", "2-2": "he_penetration",
                "2-3": "trigger_speed_bb", "2-4": "detection_torpedo_range",
                "2-5": "detection_aiming", "2-6": "aa_damage_constant_bubbles",
                "3-1": "ap_damage_bb", "3-2": "atba_range",
                "3-3": "armament_reload_aa_damage", "3-4": "defence_crit_fire_flooding",
                "3-5": "defence_uw", "3-6": "aa_prioritysector_damage_constant",
                "4-1": "trigger_burn_gm_reload", "4-2": "atba_accuracy",
                "4-3": "trigger_gm_atba_reload_bb", "4-4": "consumables_crashcrew_regencrew_upgrade",
                "4-5": "detection_visibility_range", "4-6": "defence_fire_probability",
            },
            "巡洋舰": {
                "1-1": "gm_turn", "1-2": "torpedo_speed",
                "1-3": "consumables_reload", "1-4": "gm_shell_reload",
                "1-5": "detection_alert", "1-6": "maneuverability",
                "2-1": "he_fire_probability", "2-2": "torpedo_reload",
                "2-3": "consumables_duration", "2-4": "consumables_spotter_upgrade",
                "2-5": "detection_aiming", "2-6": "aa_prioritysector_damage_constant",
                "3-1": "he_sap_damage", "3-2": "torpedo_damage",
                "3-3": "armament_reload_aa_damage", "3-4": "ap_damage_ca",
                "3-5": "consumables_additional", "3-6": "defense_hp",
                "4-1": "trigger_gm_atba_reload_ca", "4-2": "trigger_speed_accuracy",
                "4-3": "detection_direction", "4-4": "he_penetration",
                "4-5": "detection_visibility_range", "4-6": "aa_damage_constant_bubbles",
            },
            "驱逐舰": {
                "1-1": "gm_turn", "1-2": "torpedo_flooding_probability",
                "1-3": "consumables_reload", "1-4": "gm_shell_reload",
                "1-5": "detection_alert", "1-6": "defense_crit_probability",
                "2-1": "he_fire_probability", "2-2": "torpedo_speed",
                "2-3": "consumables_duration", "2-4": "ap_damage_dd",
                "2-5": "detection_aiming", "2-6": "maneuverability",
                "3-1": "gm_reload_aa_damage_constant", "3-2": "torpedo_reload",
                "3-3": "armament_reload_aa_damage", "3-4": "he_penetration",
                "3-5": "consumables_additional", "3-6": "defense_hp",
                "4-1": "gm_range_aa_damage_bubbles", "4-2": "trigger_speed",
                "4-3": "detection_direction", "4-4": "trigger_gm_reload",
                "4-5": "detection_visibility_range", "4-6": "trigger_spreading",
            },
            "潜艇": {
                "1-1": "trigger_pinger_reload_buff", "1-2": "torpedo_flooding_probability",
                "1-3": "trigger_cons_rudder_time_coeff", "1-4": "detection_aiming",
                "1-5": "detection_alert", 
                "2-1": "submarine_battery_capacity", "2-2": "trigger_seen_torpedo_reload",
                "2-3": "consumables_duration", "2-4": "defense_crit_probability",
                "2-5": "maneuverability", 
                "3-1": "trigger_pinger_speed_buff", "3-2": "submarine_hold_sectors",
                "3-3": "consumables_reload", "3-4": "submarine_danger_alert",
                "3-5": "consumables_additional", 
                "4-1": "armament_reload_submarine", "4-2": "submarine_torpedo_ping_damage",
                "4-3": "trigger_cons_sonar_time_coeff", "4-4": "submarine_battery_burn_down",
                "4-5": "submarine_speed", 
            },
        }

    def _get_db(self):
        return get_db()

    def _get_version_code(self) -> str:
        db = self._get_db()
        if db:
            return db.get_latest_version_code() or ""
        return ""

    def get_skill_for_grid(self, icon_name: str, ship_type_en: str,
                           container_id: str) -> Optional[dict]:
        """
        获取指定位置的技能数据（按技能容器确定稀有度）。

        Args:
            icon_name: 图标文件名（snake_case，如 planes_reload）
            ship_type_en: 当前舰种英文名
            container_id: 技能容器ID（如 PCOL001_CommonCrewSkills）
        """
        db = self._get_db()
        vc = self._get_version_code()
        if not db or not vc:
            return None

        # 找技能 key
        sk = self._icon_to_skill_key(icon_name, db, vc)
        if not sk:
            return None

        # 从容器确定稀有度
        rarity = "REGULAR"
        if container_id:
            try:
                cur = db._conn.execute(
                    "SELECT ship_type_subtypes FROM crew_skill_containers WHERE version_code=? AND container_id=? AND skill_key=?",
                    (vc, container_id, sk)
                )
                row = cur.fetchone()
                if row:
                    sst = json.loads(row["ship_type_subtypes"]) if row["ship_type_subtypes"] else {}
                    if ship_type_en in sst:
                        rarity = sst[ship_type_en]
            except Exception:
                pass

        # 从定义取 modifiers 和 trigger 数据
        mods = {}
        trigger = {}
        try:
            cur = db._conn.execute(
                "SELECT modifiers_json, trigger_json FROM crew_skill_definitions WHERE version_code=? AND skill_key=? AND rarity=?",
                (vc, sk, rarity)
            )
            row = cur.fetchone()
            if row:
                mods = json.loads(row["modifiers_json"]) if row["modifiers_json"] else {}
                trigger = json.loads(row["trigger_json"]) if row["trigger_json"] else {}
        except Exception:
            pass

        return {
            "skill_key": sk,
            "modifiers": mods,
            "trigger": trigger,
            "rarity": rarity,
            "icon_name": icon_name,
        }

    def _icon_to_skill_key(self, icon_name: str, db, vc: str) -> Optional[str]:
        """通过图标文件名（snake_case）匹配 skill_key"""
        # 构建可能的 CamelCase 变体
        candidates = []
        parts = icon_name.split("_")
        # 标准 CamelCase
        candidates.append("".join(p.capitalize() for p in parts))
        # 全小写
        candidates.append(icon_name.lower())
        # 去除下划线全小写
        candidates.append(icon_name.lower().replace("_", ""))

        # 从缓存/DB 取所有 skill_key，不区分大小写匹配（按 version_code 缓存）
        keys = self._skill_keys_cache.get(vc)
        if keys is None:
            try:
                cur = db._conn.execute(
                    "SELECT DISTINCT skill_key FROM crew_skill_definitions WHERE version_code=?",
                    (vc,)
                )
                keys = [row["skill_key"] for row in cur.fetchall()]
            except Exception:
                keys = []
            self._skill_keys_cache[vc] = keys
        for db_sk in keys:
            db_lower = db_sk.lower().replace("_", "")
            for c in candidates:
                if c.lower().replace("_", "") == db_lower:
                    return db_sk
        return None

    def get_grid_skills(self, ship_type_cn: str, container_id: str = "PCOL001_CommonCrewSkills",
                        ship_type_en: str = "", wows_type: str = "", crew_id: str = "") -> list[list[Optional[dict]]]:
        """
        获取技能网格数据。
        - Lesta：固定 4×6，位置取 `_grid_map`
        - WG：潜艇 4×5、其他舰种 4×6，位置取 `_wg_grid_map`；
          指定 crew_id 时直接取该舰长技能组（crew_skill_groups）的数据，否则回退标准定义
        """
        if not ship_type_en:
            ship_type_en = self._ship_type_map.get(ship_type_cn, "")

        # 服务器判定：显式传参优先，其次取当前 DB
        if not wows_type:
            _db0 = self._get_db()
            wows_type = getattr(_db0, "_wows_type", "") or ""

        if wows_type == "Wargaming":
            cols = 5 if ship_type_cn == "潜艇" else 6
            grid = self._wg_grid_map.get(ship_type_cn, {})
            result = [[None] * cols for _ in range(4)]
            # 指定舰长 → 直接取该舰长技能组数据（WG 每个舰长内嵌完整技能）
            crew_data = self._get_crew_skill_group(crew_id, ship_type_en) if crew_id else None
            db = self._get_db()
            vc = self._get_version_code()
            for pos, icon_name in grid.items():
                try:
                    parts = pos.split("-")
                    row = int(parts[0]) - 1
                    col = int(parts[1]) - 1
                    if 0 <= row < 4 and 0 <= col < cols:
                        if crew_data is not None:
                            sk = self._icon_to_skill_key(icon_name, db, vc)
                            cd = crew_data.get(sk) if sk else None
                            if cd:
                                result[row][col] = {
                                    "skill_key": sk,
                                    "modifiers": cd["modifiers"],
                                    "trigger": cd["trigger"],
                                    "tier": cd["tier"],
                                    "rarity": "EPIC" if cd["is_epic"] else "REGULAR",
                                    "icon_name": icon_name,
                                    "is_epic": cd["is_epic"],
                                }
                        else:
                            skill = self.get_skill_for_grid(icon_name, ship_type_en, container_id)
                            if skill:
                                result[row][col] = skill
                except (ValueError, IndexError):
                    continue
            return result

        grid = self._grid_map.get(ship_type_cn, {})
        result = [[None] * 6 for _ in range(4)]

        for pos, icon_name in grid.items():
            try:
                parts = pos.split("-")
                row = int(parts[0]) - 1
                col = int(parts[1]) - 1
                if 0 <= row < 4 and 0 <= col < 6:
                    skill = self.get_skill_for_grid(icon_name, ship_type_en, container_id)
                    if skill:
                        result[row][col] = skill
            except (ValueError, IndexError):
                continue

        return result

    def _get_crew_skill_group(self, crew_id: str, ship_type_en: str = "") -> Optional[dict]:
        """取某舰长技能组（WG Crew 文件内嵌 Skills）→ {skill_key: {modifiers, trigger, tier, is_epic}}"""
        db = self._get_db()
        vc = self._get_version_code()
        if not db or not vc or not crew_id:
            return None
        try:
            rows = db._conn.execute(
                "SELECT skill_key, modifiers_json, trigger_json, tier_json, is_epic "
                "FROM crew_skill_groups WHERE version_code=? AND crew_id=?",
                (vc, crew_id)).fetchall()
        except Exception:
            return None
        out = {}
        for r in rows:
            mods = json.loads(r["modifiers_json"] or "{}")
            if ship_type_en:
                flat = {}
                for k, v in mods.items():
                    if isinstance(v, dict):
                        v = v.get(ship_type_en) or next((x for x in v.values() if isinstance(x, (int, float))), v)
                    flat[k] = v
                mods = flat
            out[r["skill_key"]] = {
                "modifiers": mods,
                "trigger": json.loads(r["trigger_json"] or "{}"),
                "tier": json.loads(r["tier_json"] or "{}"),
                "is_epic": bool(r["is_epic"]),
            }
        return out or None

    def reload_skill_with_rarity(self, skill_key: str, rarity: str,
                                 ship_type_en: str = "") -> Optional[dict]:
        """按指定稀有度重新查询技能定义，返回可用于 grid 的 skill dict"""
        db = self._get_db()
        vc = self._get_version_code()
        if not db or not vc:
            return None
        mods = {}
        trigger = {}
        try:
            cur = db._conn.execute(
                "SELECT modifiers_json, trigger_json FROM crew_skill_definitions WHERE version_code=? AND skill_key=? AND rarity=?",
                (vc, skill_key, rarity)
            )
            row = cur.fetchone()
            if row:
                mods = json.loads(row["modifiers_json"]) if row["modifiers_json"] else {}
                trigger = json.loads(row["trigger_json"]) if row["trigger_json"] else {}
        except Exception:
            pass
        # 按舰种扁平化 dict 类型修饰符
        if ship_type_en:
            flat_mods = {}
            for k, v in mods.items():
                if isinstance(v, dict):
                    v = v.get(ship_type_en) or next((x for x in v.values() if isinstance(x, (int, float))), v)
                flat_mods[k] = v
            mods = flat_mods
        return {
            "skill_key": skill_key,
            "modifiers": mods,
            "trigger": trigger,
            "rarity": rarity,
        }

    def get_ship_type_cn(self, ship_type_en_or_cn: str) -> str:
        """尝试转中文舰种名（用于 grid_map 查询）"""
        # 如果输入是英文，转中文；否则直接返回（已是最小中文名）
        cn = self._reverse_type_map.get(ship_type_en_or_cn)
        if cn:
            return cn
        return ship_type_en_or_cn

    @classmethod
    def reset(cls):
        """重置单例（数据重载后调用）"""
        cls._instance = None
