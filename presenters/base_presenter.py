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
        """解析飞机名称（查找 name_mappings 表）"""
        plane_mappings = self.get_name_map("plane")
        key = raw_key.upper()
        if key in plane_mappings:
            return plane_mappings[key]
        base = key.split("_")[0]
        if base in plane_mappings:
            return plane_mappings[base]
        return raw_key

    def resolve_plane_id(self, raw_key: str) -> str:
        """解析飞机 ID（用于 plane_basic_info 查询）"""
        return raw_key

    # ── 武器名解析 ──────────────────────────────────────

    @staticmethod
    def resolve_weapon_name(row: dict | sqlite3.Row, default_key: str = "") -> str:
        """从 DB 行中提取用于显示名解析的 key，优先 launcher_name 再 module_key"""
        try:
            ln = row['launcher_name']
            if ln:
                return ln
        except (KeyError, IndexError, TypeError):
            pass
        try:
            mk = row['module_key']
            if mk:
                return mk
        except (KeyError, IndexError, TypeError):
            pass
        return default_key

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
    def make_item(name: str, value: str = "", order: int = 0,
                  row_type: str = "kv",
                  unit: str = "",
                  raw_value=None,
                  details: list[dict] = None,
                  color: str = "",
                  ) -> dict:
        """创建一个展示项

        Args:
            name: 标签名（左列）
            value: 值文本（右列）
            order: 排序序号
            row_type: 行类型
                "kv"        - 普通键值对
                "header"    - 分段标题
                "separator" - 分隔线
                "button_group" - 按钮组（如 DOT 数量选择）
            unit: 单位（如 "节", "公里", "%"），渲染时与 value 分开显示
            raw_value: 原始数值（用于计算/交互）
            details: 二级详细数据列表，格式 [{name, value, unit}...]
            color: 值文本颜色（如 "#1b8a1b" 绿色），为空则自动判断
        """
        return {
            "name": name, "value": value, "order": order,
            "row_type": row_type, "unit": unit,
            "raw_value": raw_value,
            "details": details or [],
            "color": color,
        }

    @staticmethod
    def make_section(label: str, items: list[dict],
                     icon: str = "") -> dict:
        """创建一个数据分区

        Args:
            label: 分区标题
            items: 展示项列表
            icon: 分区图标（如 "🚢", "🔫"）
        """
        return {"label": label, "items": items, "icon": icon}

    @staticmethod
    def append_props(items: list[dict], row,
                     props: list[tuple[str, str, str]],
                     start_order: int = 0) -> int:
        """从数据库行中批量添加属性到 items 列表

        Args:
            items: 目标 items 列表
            row: sqlite3.Row 对象
            props: [(列名, 显示标签, 单位), ...]
            start_order: 起始排序序号

        Returns:
            下一个可用序号
        """
        o = start_order
        for col, label, unit in props:
            val = row[col] if col in row.keys() else None
            if val is not None:
                items.append(BasePresenter.make_item(label, str(val), o, unit=unit))
                o += 1
        return o
