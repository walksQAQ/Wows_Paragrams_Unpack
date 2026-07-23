"""
PlanePresenter —— 从 plane_basic_info 表组装飞机显示数据。

参照 _archive/analyzers/plane_analyzer.py 的显示格式。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter, NM


class PlanePresenter(BasePresenter):
    """飞机显示 Presenter"""

    def build(self, plane_id: str, version_code: str = "") -> dict | None:
        # 新架构：飞机数据作为舰船模块存入 ship_module_aircraft，无独立 plane_basic_info 表
        return {
            "title": plane_id,
            "subtitle": f"ID: {plane_id}",
            "sections": [self.make_section("详情", [self.make_item("  飞机ID", plane_id, 0)])],
        }
