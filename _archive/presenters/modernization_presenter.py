"""
ModernizationPresenter —— 从 modernization 表组装升级品显示数据。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class ModernizationPresenter(BasePresenter):
    """升级品显示 Presenter"""

    def build(self, mod_id: str, version_code: str = "") -> dict | None:
        # 新架构：升级品数据暂不独立存储
        return {
            "title": mod_id,
            "subtitle": f"ID: {mod_id}",
            "sections": [self.make_section("详情", [self.make_item("  升级品ID", mod_id, 0)])],
        }
