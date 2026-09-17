"""引擎增压（speedBoosters 消耗品）参数读取。

加速曲线弹窗要用"该舰的加力消耗品"参数（弹射区间 / 倍率 / 极速加成），
这些参数在游戏数据里是**消耗品档位**级别的（不是每条船一份），所以需要两步：

1. **舰船 → 增压档**：舰船配置里的 `AbilitySlot*` 给出 `(consumable_id, config_key)`，
   其中 `consumable_id` 形如 `PCY015_SpeedBoosterPremium`。三个来源按序尝试：
   `entity_snapshots.data_json` → `ship_consumable_slots` → 拆分 JSON `data/split/Ship/<ship_id>.json`
2. **档位 → 参数**：`consumable_configs.extra_json`（WG 服务器把参数嵌在 `logic` 下）
   → 拆分 JSON `data/split/Ability/<consumable_id>.json`

返回参数含义（与游戏数据同名）::

    forwardEngineForsag          弹射区间内推力倍率（作用于未加成的满推力）
    forwardEngineForsagMaxSpeed  弹射区间上限（节，绝对值）
    backwardEngineForsag / …MaxSpeed   倒船档同名字段
    boostCoeff                   极速加成（与信号旗/技能**相加**）

⚠️ 增压启用时，弹射区间与倍率是**覆盖**（不是叠加）升级品的同名字段。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

#: 消耗品 id 里出现这些片段即视为「引擎增压」
_BOOST_MARKERS = ("SpeedBooster", "ForsageBooster")

#: 解析结果的缓存：(version_code, ship_id) -> dict | None
_CACHE: dict[tuple[str, str], dict | None] = {}


def _num(v):
    """取数值（容忍字符串 / None / 缺失）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _params_from_json_obj(obj) -> dict | None:
    """从 Ability 档位对象里抽增压参数（兼容顶层 / logic 两种形状）。"""
    if not isinstance(obj, dict):
        return None
    src = obj
    if isinstance(obj.get("logic"), dict):
        src = obj["logic"]
    out = {
        "forward_forsag": _num(src.get("forwardEngineForsag")),
        "forward_zone": _num(src.get("forwardEngineForsagMaxSpeed")),
        "backward_forsag": _num(src.get("backwardEngineForsag")),
        "backward_zone": _num(src.get("backwardEngineForsagMaxSpeed")),
        "boost_coeff": _num(src.get("boostCoeff")),
    }
    if all(out[k] is None for k in ("forward_forsag", "forward_zone", "boost_coeff")):
        return None
    out["reload_time"] = _num(obj.get("reloadTime"))
    out["work_time"] = _num(obj.get("workTime"))
    out["charges"] = _num(obj.get("numConsumables"))
    return out


# ── 舰船 → 增压档 ─────────────────────────────────────────

def _slots_from_snapshot(conn, ship_id: str) -> list[tuple[str, str]]:
    try:
        row = conn.execute(
            "SELECT data_json FROM entity_snapshots WHERE entity_id=? LIMIT 1",
            (ship_id,)).fetchone()
    except sqlite3.Error:
        return []
    if not row:
        return []
    try:
        obj = json.loads(row["data_json"])
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return []
    out: list[tuple[str, str]] = []
    for ent in obj.values():
        if not isinstance(ent, dict):
            continue
        for key, val in ent.items():
            if not str(key).startswith("AbilitySlot") or not isinstance(val, dict):
                continue
            for pair in (val.get("abils") or []):
                if isinstance(pair, list) and len(pair) >= 2 and pair[0]:
                    out.append((str(pair[0]), str(pair[1] or "")))
    return out


def _slots_from_table(conn, ship_id: str) -> list[tuple[str, str]]:
    try:
        rows = conn.execute(
            "SELECT consumable_id, config_key FROM ship_consumable_slots WHERE ship_id=? "
            "GROUP BY consumable_id, config_key", (ship_id,)).fetchall()
    except sqlite3.Error:
        return []
    return [(str(r["consumable_id"]), str(r["config_key"] or "")) for r in rows]


def _slots_from_split(ship_id: str) -> list[tuple[str, str]]:
    try:
        from utils.path_utils import get_split_dir
        path = Path(get_split_dir()) / "Ship" / f"{ship_id}.json"
    except Exception:  # noqa: BLE001
        return []
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[tuple[str, str]] = []
    for ent in obj.values():
        if not isinstance(ent, dict):
            continue
        for key, val in ent.items():
            if not str(key).startswith("AbilitySlot") or not isinstance(val, dict):
                continue
            for pair in (val.get("abils") or []):
                if isinstance(pair, list) and len(pair) >= 2 and pair[0]:
                    out.append((str(pair[0]), str(pair[1] or "")))
    return out


def _is_boost(consumable_id: str) -> bool:
    return any(m in consumable_id for m in _BOOST_MARKERS)


# ── 档位 → 参数 ───────────────────────────────────────────

def _params_from_db(conn, consumable_id: str, config_key: str) -> dict | None:
    if not config_key:
        return None
    try:
        row = conn.execute(
            "SELECT extra_json FROM consumable_configs WHERE consumable_id=? AND config_key=? "
            "LIMIT 1", (consumable_id, config_key)).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row["extra_json"]:
        return None
    try:
        return _params_from_json_obj(json.loads(row["extra_json"]))
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return None


def _params_from_split(consumable_id: str, config_key: str) -> dict | None:
    try:
        from utils.path_utils import get_split_dir
        path = Path(get_split_dir()) / "Ability" / f"{consumable_id}.json"
    except Exception:  # noqa: BLE001
        return None
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    ent = obj.get(config_key)
    if ent is None:                       # 档名对不上时退回 Default
        ent = obj.get("Default")
    return _params_from_json_obj(ent)


def load(conn, ship_id: str, version_code: str = "") -> dict | None:
    """取该舰的引擎增压参数；该舰没有加力消耗品时返回 ``None``。

    Args:
        conn: sqlite3 连接（当前服务器数据库）
        ship_id: 舰船 ID
        version_code: 版本号（仅用于缓存键）
    """
    if not ship_id or conn is None:
        return None
    key = (str(version_code or ""), ship_id)
    if key in _CACHE:
        return _CACHE[key]

    slots = (_slots_from_snapshot(conn, ship_id) or _slots_from_table(conn, ship_id)
             or _slots_from_split(ship_id))
    result = None
    for consumable_id, config_key in slots:
        if not _is_boost(consumable_id):
            continue
        params = (_params_from_db(conn, consumable_id, config_key)
                  or _params_from_split(consumable_id, config_key)
                  or _params_from_db(conn, consumable_id, "Default")
                  or _params_from_split(consumable_id, "Default"))
        if params:
            result = {"consumable_id": consumable_id, "config_key": config_key, **params}
            break
    _CACHE[key] = result
    return result


def clear_cache() -> None:
    """清空缓存（切换服务器/重新载入数据后调用）。"""
    _CACHE.clear()
