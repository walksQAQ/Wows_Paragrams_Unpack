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

    def build(self, entity_id: str, version_code: str = "") -> dict | None:
        """子类覆盖此方法"""
        raise NotImplementedError

    # ── 名称解析 ──────────────────────────────────────────

    def _ensure_version(self, version_code: str) -> str:
        """获取有效的 version_code，为空时自动取最新"""
        if version_code:
            return version_code
        try:
            cur = self.conn.execute(
                "SELECT version_code FROM data_version_registry ORDER BY version_id DESC LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else ""
        except Exception:
            return ""

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

    def resolve_name_by_id(self, mapping_id: int | None,
                            category: str = "", key: str = "") -> str | None:
        """按 id 解析名称，失败时按 (category, key) 兜底"""
        if mapping_id:
            try:
                cur = self.conn.execute(
                    "SELECT lang_zh FROM name_mappings WHERE id=?", (mapping_id,))
                row = cur.fetchone()
                if row:
                    return row[0]
            except Exception:
                pass
        if category and key:
            return self.resolve_name(category, key)
        return None

    def resolve_enum(self, enum_type: str, enum_key: str) -> str:
        """从 enum_translations 表中查找枚举翻译"""
        if not enum_key:
            return enum_key
        try:
            cur = self.conn.execute(
                "SELECT lang_zh FROM enum_translations WHERE enum_type=? AND enum_key=?",
                (enum_type, enum_key))
            row = cur.fetchone()
            if row:
                return row[0]
        except sqlite3.OperationalError:
            pass
        return enum_key

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
