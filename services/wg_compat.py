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

检修指南
--------
WG 兼容的所有差异 / 适配 / 占位都收拢在本模块，**检修 WG 兼容只看本文件**。
现有接入点（按服务器查询，Lesta 回退默认）：
  - ``processor_service``：拆分时 ``_cat_map = wg_compat.get_type_category_map(...) or TYPE_CATEGORY_MAP``
  - ``analysis_service``：``analyze_one`` 先 ``normalize_entity``；``precompute_all`` 用 ``get_categories`` / ``get_cat_labels``；
    弹夹炮识别用 ``recognize_burst_gun(module_data, wows_type)``（双分支，WG 版复制 Lesta 版待调）
  - ``ui/detail_panel``：信号旗 / 舰长技能占位文案用 ``signal_flag_placeholder()`` / ``commander_placeholder()``
数据分库 / 提取 exe / 本地化 / 图片目录 等服务器分流机制不在本模块（分属 database_service /
extractor_service / localization_service / image_paths，天然双服分流，检修时无需改动）。
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


# ── 判断辅助 ──────────────────────────────────────────────

def is_wg(wows_type: str = "") -> bool:
    """当前/指定服务器是否为 Wargaming。"""
    if not wows_type:
        from app.application import app as app_ctx
        wows_type = app_ctx.ctx.wows_type
    return wows_type == "Wargaming"


# ── WG 展示占位（检修 WG 时在此调整文案） ────────────────

#: WG 信号旗 / 舰长技能占位文案（detail_panel 使用；实现 WG 系统后改为真实展示）
SIGNAL_FLAG_PLACEHOLDER = "Wargaming 服务器\n暂不支持信号旗系统"
COMMANDER_PLACEHOLDER = "Wargaming 服务器\n暂不支持舰长技能系统"


def signal_flag_placeholder() -> str:
    """WG 信号旗占位文案（detail_panel 调用）。"""
    return SIGNAL_FLAG_PLACEHOLDER


def commander_placeholder() -> str:
    """WG 舰长技能占位文案（detail_panel 调用）。"""
    return COMMANDER_PLACEHOLDER


# ── 弹夹炮数据识别（双分支：Lesta / WG） ─────────────────
# 由 analysis_service 按服务器分发调用；WG 差异只需调 _recognize_burst_wg。
# Lesta 版勿动，WG 版当前复制 Lesta 版，人工逐点调整（见 _recognize_burst_wg 的 TODO 标注）。


def _scalar(v, default=0):
    """取标量；list/dict/None → default（analysis_service._v 的本地版，避免循环依赖）。"""
    if v is None or isinstance(v, (list, dict)):
        return default
    return v


def recognize_burst_gun(module_data: dict, wows_type: str = "") -> dict | None:
    """从 Artillery 模块数据识别弹夹/弹鼓炮配置（双分支）。

    返回统一结构（None = 非弹夹炮）::

        {"name": "连发射击模式"|"弹鼓炮",
         "shots_count": int, "shot_delay": float, "full_reload_time": float,
         "is_switchable": bool, "is_chargeable": bool,
         "charge_time_min": float, "charge_time_max": float, "charge_mode": int,
         "modifiers": dict}

    - Lesta → ``_recognize_burst_lesta``（原 analysis_service 逻辑迁移，勿动）；
    - WG → ``_recognize_burst_wg``（当前复制 Lesta，逐点调整）。
    """
    if is_wg(wows_type):
        return _recognize_burst_wg(module_data)
    return _recognize_burst_lesta(module_data)


def _recognize_burst_lesta(module_data: dict) -> dict | None:
    """Lesta 版弹夹炮识别（原 analysis_service 逻辑迁移，勿动）。"""
    for ck in ("SwitchableModeArtilleryModule", "DrumArtilleryModule"):
        conf = module_data.get(ck)
        if not conf:
            continue
        is_switchable = "Switchable" in ck
        ctp = conf.get("chargeTimeParams")
        if not isinstance(ctp, (list, tuple)):
            ctp = [0, 0, 0]
        return {
            "name": "连发射击模式" if is_switchable else "弹鼓炮",
            "shots_count": _scalar(conf.get("shotsCount")),
            # 连发间隔：Lesta DrumArtilleryModule 用 shotDelay；SwitchableMode 用 burstReloadTime
            "shot_delay": _scalar(conf.get("shotDelay")) or _scalar(conf.get("burstReloadTime")),
            "full_reload_time": _scalar(conf.get("fullReloadTime")),
            "is_switchable": is_switchable,
            "is_chargeable": bool(conf.get("isChargeable")),
            "charge_time_min": ctp[0] if len(ctp) > 0 else 0,
            "charge_time_max": ctp[1] if len(ctp) > 1 else 0,
            "charge_mode": ctp[2] if len(ctp) > 2 else 0,
            "modifiers": conf.get("modifiers", {}),
        }
    return None


def _recognize_burst_wg(module_data: dict) -> dict | None:
    """WG 版弹夹炮识别 —— **当前复制 Lesta 版**，人工逐点调整（TODO(手动) 标注）。

    待 WG 实测后在此修正的区别点：
      - 模块键：WG 是否仍有 SwitchableModeArtilleryModule / DrumArtilleryModule 同名子结构？
      - 连发间隔字段：WG 用 shotDelay 还是 burstReloadTime？（当前与 Lesta 同为 shotDelay→burstReloadTime 兜底）
      - shotsCount / fullReloadTime / chargeTimeParams / isChargeable 等字段名与语义。
    """
    for ck in ("SwitchableModeArtilleryModule", "DrumArtilleryModule"):
        conf = module_data.get(ck)
        if not conf:
            continue
        is_switchable = "Switchable" in ck
        ctp = conf.get("chargeTimeParams")
        if not isinstance(ctp, (list, tuple)):
            ctp = [0, 0, 0]
        return {
            "name": "连发射击模式" if is_switchable else "弹鼓炮",
            "shots_count": _scalar(conf.get("shotsCount")),
            # TODO(手动): WG 连发间隔字段确认后在此调整
            "shot_delay": _scalar(conf.get("shotDelay")) or _scalar(conf.get("burstReloadTime")),
            "full_reload_time": _scalar(conf.get("fullReloadTime")),
            "is_switchable": is_switchable,
            "is_chargeable": bool(conf.get("isChargeable")),
            "charge_time_min": ctp[0] if len(ctp) > 0 else 0,
            "charge_time_max": ctp[1] if len(ctp) > 1 else 0,
            "charge_mode": ctp[2] if len(ctp) > 2 else 0,
            "modifiers": conf.get("modifiers", {}),
        }
    return None


# ── WG 机制适配预留（待 M2 填充，见计划文档 4.x） ──────────
# 信号旗槽位 / 舰长技能布局 / 连发模式词条（shotIntensity、secondaryAmmoList）等
# WG 特有机制的适配逻辑，后续集中实现于此，避免散落 detail_panel / analysis_service。
