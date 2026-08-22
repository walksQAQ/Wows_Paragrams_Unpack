"""
presenters —— 数据显示层（Presenter Pattern）。

职责：
  1. 从结构化数据库表读取数据
  2. 组装成 UI 可消费的显示结构（sections + items）
  3. 完全与 UI 层解耦，返回纯 dict 数据

与 analysis_service 的分工：
  - analysis_service（AnalysisStore）负责 写入 数据库
  - presenters 负责 读取 并格式化显示

服务器分离：展示实现按服务器分为两套平级目录
  - presenters/lesta/     （LestaBasePresenter / LestaShipPresenter / LestaPresenterRegistry）
  - presenters/wargaming/ （WargamingBasePresenter / WargamingShipPresenter / WargamingPresenterRegistry）
顶层 PresenterRegistry 按 is_wg() 分发到对应树；顶层 base_presenter / ship_presenter
保留 Lesta 兼容转发。检修：Lesta 展示看 presenters/lesta/，WG 看 presenters/wargaming/。

使用方式：
  from presenters.registry import PresenterRegistry
  data = PresenterRegistry.build("ship", "PASA002", db_connection)
"""

from presenters.registry import PresenterRegistry, CATEGORY_TO_ETYPE
from presenters.ship_presenter import ShipPresenter

__all__ = [
    "PresenterRegistry",
    "CATEGORY_TO_ETYPE",
    "ShipPresenter",
]
