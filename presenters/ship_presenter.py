"""
ShipPresenter —— 兼容转发层（Lesta 版）。

实现已迁移到 presenters/lesta/ship.py（LestaShipPresenter）。
本文件保留旧类名 ShipPresenter 供既有 import（detail_panel 等）使用。
检修：Lesta 展示看 presenters/lesta/，WG 展示看 presenters/wargaming/。
"""

from presenters.lesta.ship import LestaShipPresenter as ShipPresenter

__all__ = ["ShipPresenter"]
