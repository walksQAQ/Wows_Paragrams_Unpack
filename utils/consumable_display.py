"""消耗品显示字段解析 —— iconIDs / titleIDs。

部分消耗品条目本身没有独立美术与词条（典型如 ``PCY055_AbilityClones`` 这类"克隆/容器"：
其自带的 ``consumable_<id>_0.png`` 是一张纯白占位图，名称词条也不存在），
游戏内显示的是配置里 ``iconIDs`` / ``titleIDs`` 指向的那个消耗品的**图片与名称**
（如 ``SMOKE_IT_Oil_8_10_CLONE`` → ``PCY014_SmokeGeneratorOil_Premium`` =「高速发烟器」）。

本模块负责从 ``consumable_configs.extra_json`` 取出这两个键，供 Presenter 写入
``icon_id`` / ``title_id``、UI 据此加载图片与名称。两键为空表示不覆盖，
沿用消耗品自身 ID 对应的图片与词条。
"""
from __future__ import annotations

import json

#: 兼容可能的键名写法（游戏内为 iconIDs / titleIDs）
_ICON_KEYS = ("iconIDs", "iconIds", "icon_ids")
_TITLE_KEYS = ("titleIDs", "titleIds", "title_ids")


def _key_from_extra(extra: dict | str | None, keys: tuple[str, ...]) -> str:
    """从配置取指定键的值（列表取第一个非空项）。

    extra 可以直接是已解析的 dict，也可以是 ``extra_json`` 原始字符串。
    无法解析时返回 ``""``。
    """
    if not extra:
        return ""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (ValueError, TypeError):
            return ""
    if not isinstance(extra, dict):
        return ""
    val = None
    for key in keys:
        if extra.get(key):
            val = extra[key]
            break
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        val = next((x for x in val if x), "")
    return str(val or "").strip()


def icon_key_from_extra(extra: dict | str | None) -> str:
    """取 iconIDs 图标键（显示图片跟随的消耗品 ID）。"""
    return _key_from_extra(extra, _ICON_KEYS)


def title_key_from_extra(extra: dict | str | None) -> str:
    """取 titleIDs 标题键（显示名称跟随的消耗品 ID）。"""
    return _key_from_extra(extra, _TITLE_KEYS)


def consumable_display_refs(conn, version_code: str, consumable_id: str,
                            config_key: str) -> dict[str, str]:
    """查 ``consumable_configs`` 取该槽位配置的显示引用。

    返回 ``{"icon_id": ..., "title_id": ...}``（缺失为 ``""``）。
    找不到该 config_key 时回退 ``Default`` 配置；任何异常一律返回空值
    （UI 会退回消耗品自身 ID 的图片与词条）。
    """
    empty = {"icon_id": "", "title_id": ""}
    if conn is None or not consumable_id:
        return empty
    try:
        row = conn.execute(
            "SELECT extra_json FROM consumable_configs "
            "WHERE version_code=? AND consumable_id=? AND config_key=?",
            (version_code, consumable_id, config_key or 'Default')).fetchone()
        if not row:
            row = conn.execute(
                "SELECT extra_json FROM consumable_configs "
                "WHERE version_code=? AND consumable_id=? AND config_key='Default'",
                (version_code, consumable_id)).fetchone()
    except Exception:  # noqa: BLE001
        return empty
    if not row:
        return empty
    try:
        extra = row['extra_json']
    except (TypeError, IndexError, KeyError):
        extra = row[0] if len(row) else None
    return {"icon_id": icon_key_from_extra(extra), "title_id": title_key_from_extra(extra)}
