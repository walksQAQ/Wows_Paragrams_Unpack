"""
LestaPresenterRegistry —— Lesta 服务器实体类型 → Presenter 的注册与路由。

与 presenters/wargaming/registry.py（WargamingPresenterRegistry）平级独立，
各自路由本服务器展示实现。顶层 presenters/registry.py 按 is_wg() 分发到本类。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from presenters.lesta.base import LestaBasePresenter
from presenters.lesta.ship import LestaShipPresenter


# ── 类型映射 ──────────────────────────────────────────────

# entity_type → Presenter 类
PRESENTER_MAP: dict[str, type[LestaBasePresenter]] = {
    "ship": LestaShipPresenter,
}

# 外部 category 名（如 "Ship", "Aircraft"）→ entity_type 映射
CATEGORY_TO_ETYPE: dict[str, str] = {
    "Ship": "ship",
}


class LestaPresenterRegistry:
    """Lesta Presenter 注册中心"""

    _instances: dict[str, LestaBasePresenter] = {}

    @classmethod
    def get_presenter(cls, entity_type: str,
                      conn: sqlite3.Connection) -> Optional[LestaBasePresenter]:
        """获取对应类型的 Presenter 实例"""
        presenter_cls = PRESENTER_MAP.get(entity_type)
        if not presenter_cls:
            return None
        # 缓存实例（每个连接每个类型一个）
        cache_key = f"{entity_type}_{id(conn)}"
        if cache_key not in cls._instances:
            cls._instances[cache_key] = presenter_cls(conn)
        return cls._instances[cache_key]

    @classmethod
    def build(cls, entity_type_or_category: str,
              entity_id: str, conn: sqlite3.Connection,
              version_code: str = "") -> Optional[dict]:
        """统一入口：根据实体类型构建显示数据"""
        etype = CATEGORY_TO_ETYPE.get(entity_type_or_category, entity_type_or_category)
        presenter = cls.get_presenter(etype, conn)
        if not presenter:
            return None
        return presenter.build(entity_id, version_code=version_code)

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances = {}
