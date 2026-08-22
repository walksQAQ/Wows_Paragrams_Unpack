"""
analysis_service —— 兼容转发层（Lesta 版）。

实现已迁移到 services/lesta/analysis.py（LestaAnalysisStore / LestaAnalysisService）
与 services/wargaming/analysis.py（WargamingAnalysisStore / WargamingAnalysisService）。
本文件保留旧类名 AnalysisStore / AnalysisService 供既有 import 使用（默认 Lesta 版）。
按服务器分发由 processor_service 负责（is_wg() 时用 wargaming 版）。
检修：Lesta 写入层看 services/lesta/，WG 写入层看 services/wargaming/。
"""

from services.lesta.analysis import LestaAnalysisStore as AnalysisStore
from services.lesta.analysis import LestaAnalysisService as AnalysisService

__all__ = ["AnalysisStore", "AnalysisService"]
