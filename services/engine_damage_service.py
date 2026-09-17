"""引擎受损（瘫痪）/ 进水的降速参数 —— 纯 DB 列，缺失时回退拆分 JSON。

数据来源：
  · `ship_module_engine.damaged_engine_power_multiplier`（-0.6 ⇒ 出力 ×0.4）、
    `ship_module_engine.damaged_engine_power_time_multiplier`（5.5 / 6.5 / 7.0）
  · 进水惩罚在引擎行的 `forward_speed_on_flood` / `backward_speed_on_flood`（如 -0.3）
  · 旧库（未重新提取）这两列为空 ⇒ 回退读拆分 JSON `data/split/Ship/<id>.json`
    的引擎块（键以 `_Engine` 结尾）里的同名字段；结果按舰船缓存。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: 全库多数的缺省值（仅在两处都读不到时使用）
DEFAULT_POWER_MULTIPLIER = -0.6
DEFAULT_TIME_MULTIPLIER = 5.5

_CACHE: dict[str, dict] = {}


def _num(v: Any):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _from_split(ship_id: str) -> dict:
    """从拆分 JSON 的引擎块里取受损参数（旧库回退用）。"""
    try:
        from utils.path_utils import get_split_dir
    except Exception:  # noqa: BLE001
        return {}
    path = Path(get_split_dir()) / "Ship" / f"{ship_id}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    for key, obj in (data.items() if isinstance(data, dict) else ()):
        if not str(key).endswith("_Engine") or not isinstance(obj, dict):
            continue
        pm = _num(obj.get("damagedEnginePowerMultiplier"))
        tm = _num(obj.get("damagedEnginePowerTimeMultiplier"))
        if pm is not None or tm is not None:
            return {"power_multiplier": pm, "time_multiplier": tm, "source": "split"}
    return {}


def load(conn, ship_id: str, version_code: str = "") -> dict:
    """该舰的引擎受损参数。

    Returns:
        ``{"power_multiplier": float, "time_multiplier": float, "source": str}``
        —— ``source`` ∈ ``"db" / "split" / "default"``（便于排查）。
    """
    if not ship_id:
        return {}
    if ship_id in _CACHE:
        return _CACHE[ship_id]
    out: dict = {}
    try:
        row = conn.execute(
            "SELECT damaged_engine_power_multiplier AS pm, "
            "       damaged_engine_power_time_multiplier AS tm "
            "FROM ship_module_engine WHERE ship_id=? "
            "  AND (damaged_engine_power_multiplier IS NOT NULL "
            "       OR damaged_engine_power_time_multiplier IS NOT NULL) "
            "ORDER BY version_code DESC LIMIT 1", (ship_id,)).fetchone()
    except Exception:  # noqa: BLE001  （旧库没这两列）
        row = None
    if row is not None:
        out = {"power_multiplier": _num(row["pm"]), "time_multiplier": _num(row["tm"]),
               "source": "db"}
    if not out or (out.get("power_multiplier") is None and out.get("time_multiplier") is None):
        out = _from_split(ship_id) or {}
    pm = out.get("power_multiplier")
    tm = out.get("time_multiplier")
    res = {"power_multiplier": DEFAULT_POWER_MULTIPLIER if pm is None else pm,
           "time_multiplier": DEFAULT_TIME_MULTIPLIER if tm is None else tm,
           "source": out.get("source") or "default"}
    _CACHE[ship_id] = res
    return res


def clear_cache() -> None:
    """清空缓存（切换服务器/版本或测试用）。"""
    _CACHE.clear()
    _SKILL_CACHE.clear()


# ── 「背水一战」（引擎/舵机瘫痪后保留部分出力）────────────────────────────
#: 技能键：两服同名，`crew_skill_definitions.skill_key`
KEEP_SKILL_KEY = "Maneuverability"
#: 本地化查表用的键（`name_mappings.key_name`）
KEEP_SKILL_LOCALE_KEY = "maneuverability"
#: 技能缺失时缺省的**损失系数**（当前版本两服都是 0.2167）
DEFAULT_LOSS_COEFF = 0.2167

_SKILL_CACHE: dict[str, dict] = {}


def load_keep_skill(conn, version_code: str = "") -> dict:
    """「背水一战」技能参数（按版本缓存；1 点常规技能，两服同值）。

    技能描述（游戏本地化原文）：在引擎和操舵装置**瘫痪**后，战舰还能保持部分航速和机动性。
    数据：`crew_skill_definitions.modifiers_json` 的 `damagedEngineCoeff`（当前 0.2167）
    + `softCriticalEnabled`（开启“软”损管状态，而不是彻底断掉）。
    口径（已确认）：`damagedEngineCoeff` 是**点技能后剩下的损失**。
    无技能时瘫痪 = 损失 1.0（完全没有推进力）；点后只损失 0.2167 ⇒ **惩罚幅度减少 78.33%**，
    即**保留出力 = 1 − 0.2167 = 0.7833**。所以这里是 ``keep = 1 - coeff``、``loss = coeff``。

    Returns:
        ``{"key", "name", "desc", "keep", "loss", "soft_critical", "source"}``：
        · ``keep`` —— 保留的**引擎出力**比例 = ``1 - damagedEngineCoeff``（0.7833）
        · ``loss`` —— 点技能后的损失 = `damagedEngineCoeff`（0.2167；无技能时为 1.0）
        读不到技能时 ``source = "default"``。
    """
    vc = str(version_code or "")
    if vc in _SKILL_CACHE:
        return _SKILL_CACHE[vc]
    out: dict = {"key": KEEP_SKILL_KEY, "name": "背水一战", "desc": "",
                 "keep": 1.0 - DEFAULT_LOSS_COEFF, "loss": DEFAULT_LOSS_COEFF,
                 "soft_critical": True, "source": "default"}
    try:
        row = conn.execute(
            "SELECT modifiers_json FROM crew_skill_definitions "
            "WHERE (version_code=? OR ?='') AND skill_key=? AND rarity='REGULAR' "
            "ORDER BY version_code DESC LIMIT 1",
            (vc, vc, KEEP_SKILL_KEY)).fetchone()
    except Exception:  # noqa: BLE001
        row = None
    if row is not None:
        try:
            mods = json.loads(row["modifiers_json"] or "{}")
        except Exception:  # noqa: BLE001
            mods = {}
        coeff = _num(mods.get("damagedEngineCoeff"))
        if coeff is not None and 0.0 <= coeff < 1.0:
            out.update(keep=1.0 - coeff, loss=coeff, source="db",
                       soft_critical=bool(mods.get("softCriticalEnabled", True)))
    # 名字/描述走本地化表（UI 里技能 tooltip 也是这么取的）
    try:
        for cat, fld in (("skill_title", "name"), ("skill_desc", "desc")):
            r = conn.execute(
                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=?",
                (cat, KEEP_SKILL_LOCALE_KEY)).fetchone()
            if r and r["lang_zh"]:
                out[fld] = str(r["lang_zh"])
    except Exception:  # noqa: BLE001
        pass
    _SKILL_CACHE[vc] = out
    return out
