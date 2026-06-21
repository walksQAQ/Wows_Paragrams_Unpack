"""
presenters —— 数据显示层（Presenter Pattern）。

职责：
  1. 从结构化数据库表读取数据
  2. 组装成 UI 可消费的显示结构（sections + items）
  3. 完全与 UI 层解耦，返回纯 dict 数据

与 analysis_service 的分工：
  - analysis_service（AnalysisStore）负责 写入 数据库
  - presenters 负责 读取 并格式化显示

使用方式：
  from presenters.registry import PresenterRegistry
  data = PresenterRegistry.build("ship", "PASA002", db_connection)
"""

from presenters.registry import PresenterRegistry
from presenters.ship_presenter import ShipPresenter
from presenters.gun_presenter import GunPresenter
from presenters.projectile_presenter import ProjectilePresenter
from presenters.plane_presenter import PlanePresenter
from presenters.consumable_presenter import ConsumablePresenter
from presenters.modernization_presenter import ModernizationPresenter
from presenters.crew_presenter import CrewPresenter

__all__ = [
    "PresenterRegistry",
    "ShipPresenter",
    "GunPresenter",
    "ProjectilePresenter",
    "PlanePresenter",
    "ConsumablePresenter",
    "ModernizationPresenter",
    "CrewPresenter",
]
