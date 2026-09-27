"""火炮射程的「弹道封顶」计算（对齐客户端 HoopRanging）。

游戏里"最大射程加成"（射程插 / 侦察机消耗品 / 技能 / 战斗指令）并不是无限的：
客户端 `HoopRanging.__artilleryUpdate` 里

    maxDist(实际可达) = min(最大仰角对应的弹道落水距离, 名义射程 × 加成)

其中：
- 名义射程 = 火控系数 × ModifiersApply.getArtilleryMaxDist(...)（射程插/技能/战斗指令），
  侦察机的 artilleryDistCoeff 在 HoopRanging 里单独相乘；
- 弹道落水距离按**当前装填弹种**的弹道参数算（同一门炮 HE/AP 不同），
  仰角取炮塔垂直射界上限，并按客户端 `DEFAULT_MAX_PITCH = radians(45)` 钳制。

本模块只做数据装配（DB → 弹道参数 → 封顶值），数学在 `services.ballistics_service`。
所有查询结果按 (版本, 船, 模块, 弹种) 缓存在模块级字典，计算器高频调用不会反复查库。
"""

from __future__ import annotations

import json

from services.ballistics_service import BallisticsCalculator

# 计算器的火炮类型键 → ship_turret_arcs.slot_type
SLOT_TYPES_BY_KIND: dict[str, tuple[str, ...]] = {
    "main": ("artillery",),
    "atba": ("atba",),
    "sec": ("secondary_artillery",),
}

_pitch_cache: dict[tuple, float | None] = {}
_cap_cache: dict[tuple, float | None] = {}


def slot_types_for_kind(kind: str) -> tuple[str, ...]:
    return SLOT_TYPES_BY_KIND.get(kind, ("artillery",))


def clear_cache() -> None:
    """清空缓存（加载了新版本数据/切库后调用）。"""
    _pitch_cache.clear()
    _cap_cache.clear()


def max_pitch_deg(conn, version_code: str, ship_id: str, slot_types: tuple[str, ...]) -> float | None:
    """该舰对应武器槽位的炮塔最大仰角（度）；无数据返回 None。"""
    key = (version_code, ship_id, tuple(slot_types))
    if key in _pitch_cache:
        return _pitch_cache[key]
    best: float | None = None
    try:
        ph = ",".join("?" * len(slot_types))
        rows = conn.execute(
            f"SELECT vert_sector_json FROM ship_turret_arcs "
            f"WHERE version_code=? AND ship_id=? AND slot_type IN ({ph})",
            (version_code, ship_id, *slot_types),
        ).fetchall()
        for r in rows:
            try:
                v = json.loads(r["vert_sector_json"] or "null")
            except (TypeError, ValueError):
                continue
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    up = float(v[1])
                except (TypeError, ValueError):
                    continue
                best = up if best is None else max(best, up)
    except Exception:  # noqa: BLE001 —— 无表/无列时退化为"不封顶"
        best = None
    _pitch_cache[key] = best
    return best


def module_ballistics(conn, version_code: str, ship_id: str, module_id: str,
                      slot_types: tuple[str, ...]) -> list[dict]:
    """该炮模块可选弹药的弹道参数（每种弹一行）。"""
    ph = ",".join("?" * len(slot_types))
    try:
        rows = conn.execute(
            f"""SELECT p.ammo_id, e.bullet_mass, e.bullet_diameter, e.bullet_air_drag, e.bullet_speed
                FROM ship_weapon_projectiles p
                LEFT JOIN projectile_bullet_ext e ON e.projectile_id = p.ammo_id
                WHERE p.version_code=? AND p.ship_id=? AND p.module_id=? AND p.slot_type IN ({ph})
                GROUP BY p.ammo_id""",
            (version_code, ship_id, module_id, *slot_types),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rows:
        try:
            out.append({
                "ammo_id": r["ammo_id"],
                "bullet_mass": r["bullet_mass"],
                "bullet_diameter": r["bullet_diameter"],
                "bullet_air_drag": r["bullet_air_drag"],
                "bullet_speed": r["bullet_speed"],
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def ballistic_cap_km(conn, version_code: str, ship_id: str, module_id: str,
                     slot_types: tuple[str, ...], ammo_id: str | None = None) -> float | None:
    """弹道封顶值（km）。

    ammo_id 给定 → 该弹种的封顶值（对齐游戏"按当前装填弹种"）；
    否则取该模块所有可选弹种封顶值的最大值（用于不指定弹种的展示，如主界面卡片）。
    无仰角/无弹道参数时返回 None（表示不封顶）。
    """
    key = (version_code, ship_id, module_id, tuple(slot_types), ammo_id)
    if key in _cap_cache:
        return _cap_cache[key]

    cap: float | None = None
    pitch = max_pitch_deg(conn, version_code, ship_id, slot_types)
    if pitch is not None and pitch > 0.0:
        for a in module_ballistics(conn, version_code, ship_id, module_id, slot_types):
            if ammo_id is not None and a["ammo_id"] != ammo_id:
                continue
            try:
                mass = float(a["bullet_mass"] or 0.0)
                diameter = float(a["bullet_diameter"] or 0.0)
                drag = float(a["bullet_air_drag"] or 0.0)
                speed = float(a["bullet_speed"] or 0.0)
            except (TypeError, ValueError):
                continue
            if mass <= 0.0 or diameter <= 0.0 or speed <= 0.0:
                continue
            dist = BallisticsCalculator.max_range_at_pitch(mass, diameter, drag, speed, pitch) / 1000.0
            cap = dist if cap is None else max(cap, dist)
    _cap_cache[key] = cap
    return cap


def effective_max_range_km(nominal_km: float, conn, version_code: str, ship_id: str,
                           module_id: str, slot_types: tuple[str, ...],
                           ammo_id: str | None = None) -> float:
    """名义射程（已含加成）→ 实际可达射程 = min(名义, 弹道封顶)。"""
    try:
        nominal = float(nominal_km or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if nominal <= 0.0 or not ship_id or not module_id:
        return nominal
    cap = ballistic_cap_km(conn, version_code, ship_id, module_id, slot_types, ammo_id)
    if cap is None or cap <= 0.0:
        return nominal
    return min(nominal, cap)


def main_gun_cap_km(conn, version_code: str, ship_id: str, module_key: str) -> float | None:
    """主炮模块的弹道封顶值（该模块各弹种取最大）；无数据返回 None。"""
    if not ship_id or not module_key:
        return None
    return ballistic_cap_km(conn, version_code, ship_id, module_key, SLOT_TYPES_BY_KIND["main"])
