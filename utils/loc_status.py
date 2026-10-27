"""本地化键状态：把「键不存在」与「键在但原值为空」分开表达。

两者在界面上必须区分开，否则「本地化缺失」筛选会把"只填了个空格"的条目也算成缺失：

- :data:`MISSING` 语言文件里**没有该键** → 真正的本地化缺失（列表回退文件名，被筛选命中）
- :data:`BLANK`   键存在、但原值为空（纯空白，或 msgstr 原样回填了 ``IDS_xxx``）
  → 只是未翻译（列表同样回退文件名，但追加 :data:`BLANK_MARK` 标记）

``name_mappings`` 里 ``lang_zh=''`` 的行即代表 BLANK（见
``DatabaseManager.import_name_mappings``），没有行才是 MISSING。
"""

from __future__ import annotations

import sqlite3

OK = "ok"
BLANK = "blank"
MISSING = "missing"

#: 键存在但原值为空时追加在名称后的标记（列表 / 详情共用同一套文案）
#: ``\u00a0`` 让「⚠ 未翻译」在列表换行时保持整块，不被断开
BLANK_MARK = "⚠\u00a0未翻译"

#: 悬浮提示里对该标记的完整解释
BLANK_HINT = "语言文件中该键存在，但原值为空（未翻译）"


def loc_state(conn, category: str, key: str = "", mapping_id: int | None = None) -> str:
    """判某条名称的本地化状态：``ok`` / ``blank`` / ``missing``。

    查找顺序与详情面板一致：先 ``mapping_id``，再 ``(category, key)``；
    任一行命中且有非空 ``lang_zh`` 即 ``ok``，命中但全为空即 ``blank``。
    """
    checks: list[tuple[str, tuple]] = []
    if mapping_id:
        checks.append(("id=?", (mapping_id,)))
    if category and key:
        checks.append(("category=? AND key_name IN (?,?)", (category, key, key.upper())))
    found = False
    try:
        for where, args in checks:
            row = conn.execute(
                f"SELECT lang_zh FROM name_mappings WHERE {where} LIMIT 1", args).fetchone()
            if row is None:
                continue
            found = True
            if (row[0] or "").strip():
                return OK
    except sqlite3.Error:
        return MISSING
    return BLANK if found else MISSING
