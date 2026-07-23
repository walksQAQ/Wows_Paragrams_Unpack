"""
GunPresenter —— 从 ship_module_artillery 表组装火炮显示数据（新架构）。
"""

from __future__ import annotations

from presenters.base_presenter import BasePresenter


class GunPresenter(BasePresenter):
    """火炮显示 Presenter（新架构：火炮数据通过舰船模块查询）"""

    def build(self, gun_id: str, version_code: str = "") -> dict | None:
        # 新架构：火炮数据存入 ship_module_artillery，不再有独立 gun_basic_info 表
        # 返回基础信息供实体注册查询
        return {
            "title": gun_id,
            "subtitle": f"ID: {gun_id}",
            "sections": [self.make_section("详情", [self.make_item("  武器ID", gun_id, 0)])],
        }
