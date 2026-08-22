"""
BasePresenter —— 兼容转发层（Lesta 版）。

实现已迁移到 presenters/lesta/base.py（LestaBasePresenter）。
本文件保留旧类名 BasePresenter 供既有 import（detail_panel 等）使用。
检修：Lesta 展示看 presenters/lesta/，WG 展示看 presenters/wargaming/。
"""

from presenters.lesta.base import LestaBasePresenter as BasePresenter
from presenters.lesta.base import NM

__all__ = ["BasePresenter", "NM"]
