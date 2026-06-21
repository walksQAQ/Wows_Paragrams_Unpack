"""
BasePresenter —— 所有 Presenter 的公共基类。

提供：
  - 数据库连接管理
  - 名称映射解析（name_mappings 表、PO 翻译）
  - 公共辅助方法
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from models.name_mapping import Mapping as NM


class BasePresenter:
    """Presenter 基类"""

    # 飞机 key 前缀映射（新旧命名兼容）
    PLANE_PREFIX_MAP = {
        "PAUB": "PAAB", "PAUD": "PAAD", "PAUI": "PAAF",
        "PAMA": "PAAJ", "PAJA": "PAAJ", "PAFR": "PAAF",
        "PAGE": "PAAG", "PAIT": "PAAI", "PAPN": "PAAN",
    }

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── 名称解析 ──────────────────────────────────────────

    def resolve_name(self, category: str, key: str) -> str:
        """从 name_mappings 表解析中文名"""
        try:
            cur = self.conn.execute(
                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=?",
                (category, key.upper()))
            row = cur.fetchone()
            if row:
                return row[0]
        except sqlite3.OperationalError:
            pass
        return key

    def get_name_map(self, category: str) -> dict[str, str]:
        """获取某分类的全部名称映射"""
        try:
            cur = self.conn.execute(
                "SELECT key_name, lang_zh FROM name_mappings WHERE category=?",
                (category,))
            return {r[0]: r[1] for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return {}

    def resolve_plane(self, raw_key: str) -> str:
        """解析飞机名称（兼容新旧前缀）"""
        plane_mappings = self.get_name_map("plane")
        key = raw_key.upper()
        if key in plane_mappings:
            return plane_mappings[key]
        for old_pref, new_pref in self.PLANE_PREFIX_MAP.items():
            if key.startswith(old_pref):
                alt = new_pref + key[len(old_pref):]
                if alt in plane_mappings:
                    return plane_mappings[alt]
        base = key.split("_")[0]
        if base in plane_mappings:
            return plane_mappings[base]
        for old_pref, new_pref in self.PLANE_PREFIX_MAP.items():
            if base.startswith(old_pref):
                alt = base.replace(old_pref, new_pref, 1)
                if alt in plane_mappings:
                    return plane_mappings[alt]
        return raw_key

    def resolve_plane_id(self, raw_key: str) -> str:
        """解析飞机 ID，将旧前缀映射到新前缀（用于 plane_basic_info 查询）"""
        for old_pref, new_pref in self.PLANE_PREFIX_MAP.items():
            if raw_key.upper().startswith(old_pref):
                return new_pref + raw_key[len(old_pref):]
        return raw_key

    # ── 值格式化 ──────────────────────────────────────────

    @staticmethod
    def fmt(val: Any, default: str = "") -> str:
        return str(val) if val is not None else default

    @staticmethod
    def fmt_bool(val: Any) -> str:
        return "是" if val else "否"

    @staticmethod
    def fmt_pct(val: float, digits: int = 0) -> str:
        return f"{val * 100:.{digits}f}%"

    @staticmethod
    def make_item(name: str, value: str = "", order: int = 0) -> dict:
        return {"name": name, "value": value, "order": order}

    @staticmethod
    def make_section(label: str, items: list[dict]) -> dict:
        return {"label": label, "items": items}
