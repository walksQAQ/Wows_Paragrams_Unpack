"""
PresenterRegistry —— 实体类型 → Presenter 的注册与路由。

允许外部代码按实体类型统一调用：
    data = PresenterRegistry.build("ship", "PASA002", conn)
而不需要关心具体使用哪个 Presenter 类。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from presenters.base_presenter import BasePresenter
from presenters.ship_presenter import ShipPresenter
from presenters.gun_presenter import GunPresenter
from presenters.projectile_presenter import ProjectilePresenter
from presenters.plane_presenter import PlanePresenter
from presenters.consumable_presenter import ConsumablePresenter
from presenters.modernization_presenter import ModernizationPresenter
from presenters.crew_presenter import CrewPresenter


# ── 类型映射 ──────────────────────────────────────────────

# entity_type → Presenter 类
PRESENTER_MAP: dict[str, type[BasePresenter]] = {
    "ship": ShipPresenter,
    "gun": GunPresenter,
    "projectile": ProjectilePresenter,
    "plane": PlanePresenter,
    "consumable": ConsumablePresenter,
    "modernization": ModernizationPresenter,
    "crew": CrewPresenter,
}

# 外部 category 名（如 "Ship", "Aircraft"）→ entity_type 映射
CATEGORY_TO_ETYPE: dict[str, str] = {
    "Ship": "ship",
    "Gun": "gun",
    "Projectile": "projectile",
    "Aircraft": "plane",
    "Ability": "consumable",
    "Modernization": "modernization",
    "Crew": "crew",
}


class PresenterRegistry:
    """Presenter 注册中心"""

    _instances: dict[str, BasePresenter] = {}

    @classmethod
    def get_presenter(cls, entity_type: str,
                      conn: sqlite3.Connection) -> Optional[BasePresenter]:
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
              entity_id: str, conn: sqlite3.Connection) -> Optional[dict]:
        """统一入口：根据实体类型构建显示数据"""
        # 兼容 category 名称（如 "Ship" → "ship"）
        etype = CATEGORY_TO_ETYPE.get(entity_type_or_category, entity_type_or_category)
        presenter = cls.get_presenter(etype, conn)
        if not presenter:
            return None
        return presenter.build(entity_id)

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances = {}
