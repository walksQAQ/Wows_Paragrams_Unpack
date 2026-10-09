"""火炮 DPM（每分钟伤害）计算（纯数据层，供 presenter / UI 复用）。

    DPM = 单发标伤 × 齐射炮管数 × 60 / 齐射周期（装填时间）

「单侧齐射」= 同一次齐射中能同时开火的炮管数上限：某方位上，只有水平射界
（已减死区）覆盖该方位的炮位才能开火，因此分列两舷、射界互不覆盖的炮塔
（舷侧副炮、老式翼侧炮塔布局等）不会被算进同一次齐射，DPM 也不会按
「全炮塔同时开火」虚高。

方位约定同 `utils.firing_arc`：0° = 船首，顺时针，90° = 右舷，270° = 左舷。

对外接口：
    gun_covers(guns)          -> [frozenset, ...]  每门炮的可射方位（与 guns 同序）
    compute_dpm(turrets)      -> dict              炮管数 / 单侧齐射 / 各弹种 DPM
    dpm_items(...)            -> (items, order)    展示项（主炮/副炮/次级主炮共用）
    refresh_dpm_items(items, raw_ammo)
                              -> None            升级品/技能后按比例同步 DPM 值
"""

from __future__ import annotations

import json
import re

from utils.firing_arc import compute_facings, gun_abs_segments
from models.name_mapping import Mapping

__all__ = ["BEARINGS", "gun_covers", "compute_dpm", "dpm_items", "refresh_dpm_items"]

#: 方位分辨率：1° 一档（0-359，0° = 船首，顺时针）
BEARINGS = tuple(range(360))

#: 无射界数据时的兜底：视为全向可射
_ALL_BEARINGS = frozenset(BEARINGS)

#: 弹种显示顺序（与详情面板的 HE → SAP(CS) → AP 一致）
_AMMO_ORDER = {"HE": 0, "CS": 1, "SAP": 1, "AP": 2}


def _ammo_label(raw) -> str:
    """弹种显示名（CS → SAP，见 `Mapping.ammo_type_label`）"""
    return Mapping.ammo_type_label(raw)


def gun_covers(guns) -> list[frozenset]:
    """每门炮的可射方位集合（0-359），无射界数据者按全向可射处理。

    gun 结构同 `utils.firing_arc`：horiz_sector / dead_zones / position / mount_yaw。
    """
    out: list[frozenset] = []
    facings = compute_facings(guns) if guns else []
    for gun, facing in zip(guns, facings):
        segs = gun_abs_segments(gun, facing)
        cov: set = set()
        for start, end in segs:
            lo, hi = int(start), int(min(end, 360.0))
            if hi <= lo:
                cov.add(lo % 360)
                continue
            cov.update(b % 360 for b in range(lo, hi + 1))
        out.append(frozenset(cov) if cov else _ALL_BEARINGS)
    return out


def compute_dpm(turrets) -> dict:
    """计算齐射炮管数与各弹种 DPM。

    turrets: [{"barrels": int, "cycle": float, "damage": {弹种: 单发标伤}, "cover": set|None}]
        barrels 炮管数；cycle 齐射周期（= 装填时间，秒）；damage 该炮塔可用弹种的单发标伤；
        cover 可射方位集合（None = 无射界数据，按全向可射）。

    返回：
        barrels_total   全炮塔炮管数
        barrels_salvo   单侧（同一方位）可同时开火的最大炮管数
        salvo_bearing   取得最大齐射的方位（°，无射界数据时为 None）
        dpm_total       {弹种: 全部炮塔同时开火}（理论上限）
        dpm_salvo       {弹种: 单侧齐射}
        has_cover       是否存在射界数据（False = 单侧按全向估算，等于全炮塔）
    """
    active = [t for t in (turrets or []) if int(t.get("barrels") or 0) > 0]
    labels = sorted({l for t in active for l in (t.get("damage") or {}) if l},
                    key=lambda l: (_AMMO_ORDER.get(l, 9), l))
    result = {
        "barrels_total": sum(int(t["barrels"]) for t in active),
        "barrels_salvo": 0,
        "salvo_bearing": None,
        "dpm_total": {l: 0.0 for l in labels},
        "dpm_salvo": {l: 0.0 for l in labels},
        "has_cover": False,
    }
    if not active:
        return result

    barrels_at = [0] * 360
    dpm_at = [{l: 0.0 for l in labels} for _ in BEARINGS]
    totals = {l: 0.0 for l in labels}

    for t in active:
        barrels = int(t["barrels"])
        cover = t.get("cover")
        if cover is None:
            cover = _ALL_BEARINGS
        else:
            result["has_cover"] = True
        cycle = float(t.get("cycle") or 0.0)
        rate: dict = {}
        if cycle > 0:
            rate = {l: barrels * float(v) * 60.0 / cycle
                    for l, v in (t.get("damage") or {}).items() if v}
        for l, v in rate.items():
            totals[l] += v
        for bearing in cover:
            barrels_at[bearing] += barrels
            if rate:
                slot = dpm_at[bearing]
                for l, v in rate.items():
                    slot[l] += v

    best = max(BEARINGS, key=lambda b: barrels_at[b])
    result["barrels_salvo"] = barrels_at[best]
    if result["has_cover"]:
        result["salvo_bearing"] = best
    for l in labels:
        result["dpm_total"][l] = totals[l]
        result["dpm_salvo"][l] = max(d[l] for d in dpm_at)
    return result


def _fmt_barrels(full: bool, side: int, total: int) -> str:
    """全炮塔可同时齐射 → 只给全炮塔值；否则只给单侧值。"""
    return f"{total} 管" if full else f"{side} 管（单侧）"


def _fmt_dpm(full: bool, side: float, total: float) -> str:
    """DPM 同上：能全炮塔齐射就给全炮塔值，否则给单侧值。"""
    return f"{total:.0f}" if full else f"{side:.0f}（单侧）"


def _kv(name: str, value: str, order: int, raw_value=None, details=None) -> dict:
    """构造与 presenter `make_item` 同构的展示项。"""
    return {
        "name": name, "value": value, "order": order,
        "row_type": "kv", "unit": "",
        "raw_value": raw_value,
        "details": details or [],
        "color": "",
    }


def _as_list(raw, default=None):
    """解析 `ship_turret_arcs` 里的 JSON 文本字段（None / 空串 / "None" → default）。"""
    if raw is None or raw == "" or raw == "None":
        return default
    if isinstance(raw, (list, tuple)):
        return list(raw)
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _num(text):
    """从展示值文本里取数值（忽略「s / 架 / 管」等后缀），失败返回 None。"""
    if text is None:
        return None
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


def refresh_dpm_items(items, raw_ammo=None) -> None:
    """升级品/技能应用后按比例同步 DPM 行（原地修改 items）。

    卡片上的「装填时间」「标伤」已按同一套词条改过，因此直接取
    「显示值 / 基础值」求系数：DPM = 炮管数 × 单发标伤 × 60 / 装填时间，
    ⇒ DPM' = DPM × 标伤系数 / 装填系数，保证 DPM 与卡片上那两个因子始终一致
    （不重复实现词条匹配规则，以后改词条口径也能自动跟上）。

    基准值存在 raw_value 里（不覆盖），重复调用不会滚动叠加。
    """
    meta = None
    for it in items or []:
        rv = it.get("raw_value")
        if isinstance(rv, dict) and rv.get("kind") == "dpm_meta":
            meta = rv
            break
    if meta is None:
        return

    # 装填系数：同一 section 的炮塔装填吃同一条词条，任取一条能对上基准的即可
    reload_factor = 1.0
    bases = [float(b) for b in (meta.get("reloads") or []) if b]
    rows = sorted((it for it in items if str(it.get("name", "")).strip() == "装填时间"),
                  key=lambda it: it.get("order", 0))
    for it, base in zip(rows, bases):
        cur = _num(it.get("value"))
        if cur is not None and cur > 0 and base > 0:
            reload_factor = cur / base
            break

    # 标伤系数：按弹种从弹药明细（显示值）里取
    alpha_by_ammo = meta.get("alpha_by_ammo") or {}
    dmg_factor: dict = {}
    for a in raw_ammo or []:
        label = str(a.get("ammo_type") or "").upper()
        if not label or label in dmg_factor:
            continue
        base = alpha_by_ammo.get(a.get("ammo_id"))
        if not base:
            continue
        for d in a.get("detail_items") or []:
            if str(d.get("name", "")).strip() != "标伤":
                continue
            cur = _num(d.get("value"))
            if cur is not None and cur > 0:
                dmg_factor[label] = cur / float(base)
            break

    for it in items:
        rv = it.get("raw_value")
        if not isinstance(rv, dict) or rv.get("kind") != "dpm":
            continue
        d = dmg_factor.get(rv.get("ammo") or "", 1.0)
        r = reload_factor or 1.0
        base_salvo = float(rv.get("salvo") or 0.0)
        base_total = float(rv.get("total") or 0.0)
        if abs(d - 1.0) < 1e-9 and abs(r - 1.0) < 1e-9:
            continue
        salvo, total = base_salvo * d / r, base_total * d / r
        full = bool(rv.get("full"))
        it["value"] = _fmt_dpm(full, salvo, total)
        details = [{"name": "基础值（无升级品/技能）",
                    "value": _fmt_dpm(full, base_salvo, base_total)}]
        if abs(r - 1.0) > 1e-9:
            details.append({"name": "装填时间系数", "value": f"×{r:.3f}"})
        if abs(d - 1.0) > 1e-9:
            details.append({"name": "标伤系数", "value": f"×{d:.3f}"})
        it["details"] = details


def dpm_items(conn, vc, ship_id, letter, slot_type, mount_yaw_map=None, order=0):
    """组装「齐射炮管数 / DPM」展示项（主炮、副炮、次级主炮共用）。

    炮管数与射界：`ship_turret_arcs` 中该配置字母的炮位（按实际挂点计，比模块表的
    count 更贴近舰船实配）；齐射周期与单发标伤：模块表
    （module_key == ship_turret_arcs.gun_name）+ `ship_weapon_projectiles` +
    `projectile_bullet_ext.alpha_damage`。

    letter 为空时不做配置过滤；该舰无射界数据时回退模块表 count × num_barrels，
    按「全炮塔可同时开火」估算（DPM 单侧 = 全炮塔）。

    返回 (items, next_order)；无数据时返回 ([], order)。
    """
    table = {
        "artillery": "ship_module_artillery",
        "atba": "ship_module_atba",
        "secondary_artillery": "ship_module_secondary_artillery",
    }.get(slot_type)
    if table is None or not ship_id:
        return [], order

    # ── 模块：齐射周期（装填时间）+ 炮管（无射界数据时的回退口径） ──
    mod_sql = (f"SELECT module_key, count, num_barrels, reload_time FROM {table} "
               "WHERE version_code=? AND ship_id=?")
    mod_args: list = [vc, ship_id]
    if letter:
        mod_sql += " AND config_group LIKE ?"
        mod_args.append(f"{letter}%")
    mod_sql += " ORDER BY module_key"          # 与 presenter 的炮塔/装填行顺序一致
    mods: dict = {}
    for r in conn.execute(mod_sql, mod_args):
        mods[r["module_key"]] = r

    # ── 弹种单发标伤（同型炮共用一个模块 key，按 module_key 缓存） ──
    ammo_cache: dict = {}
    alpha_by_ammo: dict = {}          # {ammo_id: 单发标伤}（基础值，供升级品/技能按比例同步）

    def _ammo_damage(module_key: str) -> dict:
        if module_key in ammo_cache:
            return ammo_cache[module_key]
        out: dict = {}
        for a in conn.execute(
                "SELECT wp.ammo_id AS ammo_id, pb.ammo_type AS ammo_type, "
                "be.alpha_damage AS alpha_damage "
                "FROM ship_weapon_projectiles wp "
                "LEFT JOIN projectile_basic_info pb ON pb.version_code=wp.version_code "
                "AND pb.projectile_id=wp.ammo_id "
                "LEFT JOIN projectile_bullet_ext be ON be.version_code=wp.version_code "
                "AND be.projectile_id=wp.ammo_id "
                "WHERE wp.version_code=? AND wp.ship_id=? AND wp.module_id=? AND wp.slot_type=?",
                (vc, ship_id, module_key, slot_type)):
            dmg = a["alpha_damage"]
            if not dmg:
                continue
            alpha = float(dmg)
            if a["ammo_id"]:
                alpha_by_ammo[a["ammo_id"]] = max(alpha_by_ammo.get(a["ammo_id"], 0.0), alpha)
            label = (a["ammo_type"] or "").upper()
            if label:
                out[label] = max(out.get(label, 0.0), alpha)
        ammo_cache[module_key] = out
        return out

    # ── 炮位：射界（按配置字母筛选）+ 挂点安装朝向 → 可射方位 ──
    arc_rows = conn.execute(
        "SELECT hp_key, gun_name, num_barrels, horiz_sector_json, dead_zone_json, "
        "pitch_dead_zones_json, position_json, config_group "
        "FROM ship_turret_arcs WHERE version_code=? AND ship_id=? AND slot_type=?",
        (vc, ship_id, slot_type)).fetchall()
    if letter:
        arc_rows = [r for r in arc_rows if letter in (r["config_group"] or "")]

    turrets: list = []
    if arc_rows:
        mount_yaw_map = mount_yaw_map or {}
        guns = []
        for r in arc_rows:
            yaw, pos = mount_yaw_map.get(r["hp_key"], (None, None))
            guns.append({
                "hp_key": r["hp_key"],
                "horiz_sector": _as_list(r["horiz_sector_json"]),
                "dead_zones": _as_list(r["dead_zone_json"], []),
                "pitch_dead_zones": _as_list(r["pitch_dead_zones_json"], []),
                "position": _as_list(r["position_json"], None),
                "mount_yaw": yaw,
                "mount_pos": pos,
            })
        covers = gun_covers(guns)
        for r, cover in zip(arc_rows, covers):
            barrels = int(r["num_barrels"] or 0)
            if barrels <= 0:
                continue
            mod = mods.get(r["gun_name"] or "")
            turrets.append({
                "barrels": barrels,
                "cycle": float(mod["reload_time"] or 0.0) if mod else 0.0,
                "damage": _ammo_damage(r["gun_name"] or "") if mod else {},
                "cover": cover,
            })
    else:
        # 无射界数据：回退模块表（全向可射估算）
        for module_key, mod in mods.items():
            barrels = int(mod["num_barrels"] or 0) * int(mod["count"] or 0)
            if barrels <= 0:
                continue
            turrets.append({
                "barrels": barrels,
                "cycle": float(mod["reload_time"] or 0.0),
                "damage": _ammo_damage(module_key),
                "cover": None,
            })

    res = compute_dpm(turrets)
    if not res["barrels_total"]:
        return [], order

    # 模块表口径：count × num_barrels（同型配件可能被重复计入，仅供提示对比）
    mod_barrels = sum(int(m["num_barrels"] or 0) * int(m["count"] or 0) for m in mods.values())

    items: list = []
    salvo, total = res["barrels_salvo"], res["barrels_total"]
    #: 所有炮塔都能打到同一方位 ⇒ 全炮塔齐射（显示时不再区分单侧）
    full_salvo = salvo >= total
    #: 升级品/技能作用后按「显示值 / 基础值」比例同步 DPM 所需的基础数据
    meta = {
        "kind": "dpm_meta",
        "full": full_salvo,
        "reloads": [float(m["reload_time"]) for m in mods.values() if m["reload_time"]],
        "alpha_by_ammo": alpha_by_ammo,
    }
    barrel_details = []
    if full_salvo:
        barrel_details.append({"name": "全炮塔齐射（同一方位同时开火）", "value": f"{total}", "unit": "管"})
    else:
        barrel_details.append({"name": "单侧齐射（同一方位同时开火）", "value": f"{salvo}", "unit": "管"})
        barrel_details.append({"name": "全炮塔合计（两侧炮塔不能同时开火）", "value": f"{total}", "unit": "管"})
    if res["salvo_bearing"] is not None:
        barrel_details.append({"name": "取得最大齐射的方位", "value": f"{res['salvo_bearing']}",
                               "unit": "°（0=船首，90=右舷）"})
    else:
        barrel_details.append({"name": "说明", "value": "该舰无射界数据，单侧按全炮塔估算"})
    items.append(_kv(
        "齐射炮管数", _fmt_barrels(full_salvo, salvo, total), order,
        raw_value={**meta, "salvo": salvo, "total": total, "bearing": res["salvo_bearing"]},
        details=barrel_details))
    order += 1

    for label, dpm_salvo in res["dpm_salvo"].items():
        dpm_total = res["dpm_total"].get(label, 0.0)
        if dpm_salvo <= 0 and dpm_total <= 0:
            continue
        if full_salvo:
            details = [{"name": "全炮塔齐射 DPM", "value": f"{dpm_total:.0f}"}]
        else:
            details = [{"name": "单侧齐射 DPM", "value": f"{dpm_salvo:.0f}"},
                       {"name": "全炮塔合计 DPM（两侧不能同时开火，仅供参考）",
                        "value": f"{dpm_total:.0f}"}]
        items.append(_kv(
            f"DPM（{_ammo_label(label)}）", _fmt_dpm(full_salvo, dpm_salvo, dpm_total), order,
            raw_value={"kind": "dpm", "ammo": label, "full": full_salvo,
                       "salvo": round(dpm_salvo, 1), "total": round(dpm_total, 1)},
            details=details))
        order += 1
    if arc_rows and mod_barrels and mod_barrels != total:
        # 主炮模块可换（如 stock/top 两套炮）时，模块表会把两套配件叠加计数，
        # 这里明确炮管数取自真实炮位，避免与卡片里的炮塔行看起来矛盾
        items.append(_kv("炮管数口径", f"按炮位统计 {total} 管（模块表配件合计 {mod_barrels} 管）",
                         order, details=[{"name": "说明",
                                          "value": "模块表会将同型不同配件重复计入，炮位数据不重复"}]))
        order += 1
    return items, order
