"""
wg_compat.py —— Wargaming（WG）服数据格式差异预留模块。

背景
----
WG 服的 GameParams.data 经 ``processor_service`` 拆分后，JSON 结构（TypeInfo 的 type
集合、字段名/嵌套、信号旗/舰长技能/消耗品等机制字段）与 Lesta（Korabli）存在差异。
为避免在 analysis_service / presenters 里散落 ``if wows_type``，WG 特有的差异统一
收拢到本模块，由解析/展示逻辑按服务器查询。

⚠️ 当前为**预留骨架**
--------------------
所有差异内容为占位（None / 空），由人工按 WG 实测数据**手动填充**（见各 ``TODO(手动)``
标注）。在填充完成前：
  - ``get_type_category_map`` / ``get_categories`` 返回 None → 调用方回退 Lesta 默认；
  - ``normalize_entity`` 对 WG 原样返回 → 走 Lesta 读取路径（字段可能缺失，但不崩溃）。

数据流（与 Lesta 共用拆分，差异在"解析/显示"层）::

    GameParams.data → processor_service 拆分(split/*.json + entity_snapshots)
        → analysis_service 分析(结构化表) → presenters 展示

填充示例（替换 None 即可生效）
--------------------------------
WG 实体 type → 类别（若 WG 的 type 集合/命名与 Lesta 不同）::

    WG_TYPE_CATEGORY_MAP = {
        "Ship": "Ship", "Gun": "Gun", "Projectile": "Projectile",
        "Aircraft": "Aircraft", "Ability": "Ability",
        "Modernization": "Modernization", "Crew": "Crew",
        "Other": "Other", "Exterior": "Exterior",
    }

WG 分析类别列表 / 类别中文标签（若类别增删）::

    WG_CATEGORIES = ["Projectile", "Aircraft", "Ability", "Ship",
                     "Modernization", "Crew", "Exterior", "Other"]
    WG_CAT_LABELS = {"Projectile": "弹药", "Aircraft": "飞机", "Ability": "消耗品",
                     "Ship": "舰船", "Modernization": "配件", "Crew": "舰长",
                     "Exterior": "信号旗", "Other": "其他"}

WG 实体 JSON 规范化函数（把 WG 字段对齐到内部统一结构）::

    def _wg_normalize(raw: dict) -> dict:
        # TODO(手动): 按 WG 实测 JSON 字段重命名/结构对齐
        return raw
    WG_NORMALIZE_ENTITY = _wg_normalize
"""

from __future__ import annotations


# ══════════════════════════════════════════════════════════
# 以下均为 WG 差异占位 —— 由人工按 WG 实测数据手动填充
# ══════════════════════════════════════════════════════════

#: WG 实体 type → 分析类别 映射（processor_service.TYPE_CATEGORY_MAP 的 WG 版）
#: None = 未填充 → 调用方回退 Lesta 默认。填充示例见模块 docstring。
WG_TYPE_CATEGORY_MAP: dict[str, str] | None = None

#: WG 分析类别列表（analysis_service.precompute_all 的 categories 的 WG 版）
#: None = 未填充 → 回退 Lesta 默认类别列表。
WG_CATEGORIES: list[str] | None = None

#: WG 类别中文标签（analysis_service.precompute_all 的 cat_labels 的 WG 版）
#: None = 未填充 → 回退 Lesta 默认标签。
WG_CAT_LABELS: dict[str, str] | None = None

#: WG 实体 JSON 规范化函数占位：签名 ``(raw: dict) -> dict``。
#: 由人工按 WG 实测 JSON 结构实现（字段重命名/结构对齐）；
#: 未实现（None）时 normalize_entity 对 WG 原样返回。
WG_NORMALIZE_ENTITY = None


# ── 查询接口（供 processor_service / analysis_service 调用） ──

def get_type_category_map(wows_type: str) -> dict[str, str] | None:
    """返回实体类型→类别映射；WG 已填充则用 WG 版，否则 None（调用方回退 Lesta 默认）。"""
    if wows_type == "Wargaming":
        return WG_TYPE_CATEGORY_MAP
    return None


def get_categories(wows_type: str) -> list[str] | None:
    """返回分析类别列表；WG 已填充则用 WG 版，否则 None。"""
    if wows_type == "Wargaming":
        return WG_CATEGORIES
    return None


def get_cat_labels(wows_type: str) -> dict[str, str] | None:
    """返回类别中文标签；WG 已填充则用 WG 版，否则 None。"""
    if wows_type == "Wargaming":
        return WG_CAT_LABELS
    return None


def normalize_entity(wows_type: str, raw: dict) -> dict:
    """把某服务器实体的拆分 JSON 规范化为内部统一结构。

    - Lesta：原样返回（现有逻辑直接消费）；
    - WG：若 WG_NORMALIZE_ENTITY 已实现则调用，否则原样返回（待人工填充）。
    """
    if wows_type == "Wargaming" and WG_NORMALIZE_ENTITY is not None:
        return WG_NORMALIZE_ENTITY(raw)
    return raw
