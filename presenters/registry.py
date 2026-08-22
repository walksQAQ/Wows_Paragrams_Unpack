"""
PresenterRegistry —— 按服务器分发到 Lesta / Wargaming 两套平级展示树。

对外接口保持向后兼容（调用方无需改动）：
    data = PresenterRegistry.build("ship", "PASA002", conn)

内部按当前服务器（app.ctx.wows_type）分发：
  - Lesta → presenters.lesta.registry.LestaPresenterRegistry
  - Wargaming → presenters.wargaming.registry.WargamingPresenterRegistry
检修：Lesta 展示看 presenters/lesta/，WG 展示看 presenters/wargaming/。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from services import wg_compat
from presenters.lesta.registry import LestaPresenterRegistry
from presenters.wargaming.registry import WargamingPresenterRegistry


# ── 类型映射（对外兼容：detail_panel 等 import CATEGORY_TO_ETYPE） ──
CATEGORY_TO_ETYPE: dict[str, str] = {
    "Ship": "ship",
}


class PresenterRegistry:
    """Presenter 注册中心（按服务器分发）"""

    @classmethod
    def _impl(cls):
        """按当前服务器返回对应子 registry 类"""
        if wg_compat.is_wg():
            return WargamingPresenterRegistry
        return LestaPresenterRegistry

    @classmethod
    def get_presenter(cls, entity_type: str,
                      conn: sqlite3.Connection) -> Optional[object]:
        """获取对应类型的 Presenter 实例（按服务器分发）"""
        return cls._impl().get_presenter(entity_type, conn)

    @classmethod
    def build(cls, entity_type_or_category: str,
              entity_id: str, conn: sqlite3.Connection,
              version_code: str = "") -> Optional[dict]:
        """统一入口：根据实体类型构建显示数据（按服务器分发）"""
        return cls._impl().build(entity_type_or_category, entity_id, conn,
                                 version_code=version_code)

    @classmethod
    def clear_cache(cls) -> None:
        """清空两套树的实例缓存（切服时调用）"""
        LestaPresenterRegistry.clear_cache()
        WargamingPresenterRegistry.clear_cache()
