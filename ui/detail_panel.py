"""
DetailPanel —— 右侧详情展示面板。

完全基于数据库：优先读取预分析的 analyzed_result，
数据库不存在时降级到 JSON 文件 + 按需加载分析器。
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.signals import bus
from models.analysis_result import AnalysisResult
from utils.path_utils import get_split_dir
from services.database_service import get_db


class DetailPanel(QWidget):
    """右侧详情面板——数据库驱动"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 不预加载分析器——完全依赖数据库
        self._analyzers: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(QFont("Microsoft YaHei", 11))
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #1a1a1a;
                border: none;
                padding: 8px;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.text_area)

        self._show_hint()
        bus.file_selected.connect(self._on_file_selected)

    # ── 按需加载分析器（仅降级路径使用）──────────────────

    def _get_analyzer(self, category: str):
        """按需初始化分析器（仅当数据库无预分析结果时）"""
        if self._analyzers is None:
            self._analyzers = {}
        if category not in self._analyzers:
            cls_map = {
                "Ship": ("analyzers.ship_analyzer", "ShipAnalyzer"),
                "Gun": ("analyzers.gun_analyzer", "GunAnalyzer"),
                "Projectile": ("analyzers.projectile_analyzer", "ProjectileAnalyzer"),
                "Modernization": ("analyzers.modernization_analyzer", "ModernizationAnalyzer"),
                "Aircraft": ("analyzers.plane_analyzer", "PlaneAnalyzer"),
                "Ability": ("analyzers.consumable_analyzer", "ConsumableAnalyzer"),
                "Crew": ("analyzers.crew_analyzer", "CrewAnalyzer"),
            }
            entry = cls_map.get(category)
            if entry:
                try:
                    import importlib
                    mod = importlib.import_module(entry[0])
                    cls = getattr(mod, entry[1])
                    a = cls()
                    a.initialize_mapping()
                    self._analyzers[category] = a
                except Exception as e:
                    bus.log_message.emit(f"分析器({category})加载失败: {e}")
                    return None
        return self._analyzers.get(category)

    # ── 文件选择 ──────────────────────────────────────────

    def _on_file_selected(self, category: str, filename: str) -> None:
        # 1. 优先从数据库读取预分析结果
        db = get_db()
        if db.exists:
            try:
                entity = db.get_entity(category, filename)
                if entity:
                    pre = entity.get("analyzed_result")
                    if pre:
                        self._render_dict(pre)
                        return
                    # 有 raw_json 无预分析 → 实时分析并缓存
                    raw = entity["raw_json"]
                    result = self._run_and_cache(category, filename, raw, db)
                    if result:
                        self._render_dict(result)
                        return
                    # 兜底：直接显示原始 JSON
                    self.text_area.setPlainText(json.dumps(raw, indent=4, ensure_ascii=False))
                    return
            except Exception:
                pass

        # 2. 降级到文件系统
        fp = get_split_dir() / category / f"{filename}.json"
        if not fp.exists():
            self.text_area.setPlainText(f"文件不存在: {fp}")
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self.text_area.setPlainText(f"读取失败: {e}")
            return

        # 3. 按需分析并显示原始 JSON
        a = self._get_analyzer(category)
        if a:
            try:
                result = a.analyze(raw)
                self._render(result)
                return
            except Exception as e:
                bus.log_message.emit(f"分析({category})失败: {e}")
        self.text_area.setPlainText(json.dumps(raw, indent=4, ensure_ascii=False))

    def _run_and_cache(self, category: str, key: str, raw: dict, db) -> dict | None:
        """实时运行分析器并缓存到数据库"""
        a = self._get_analyzer(category)
        if not a:
            return None
        try:
            result = a.analyze(raw)
            analyzed = {
                "title": result.title, "subtitle": result.subtitle,
                "sections": [{"label": s.label, "items": [
                    {"name": i.name, "value": i.value, "raw_value": i.raw_value,
                     "unit": i.unit, "order": i.order} for i in s.items]}
                    for s in result.sections],
                "extra": result.extra,
            }
            db.update_analyzed_json(category, key, json.dumps(analyzed, ensure_ascii=False))
            return analyzed
        except Exception as e:
            bus.log_message.emit(f"实时分析({category})失败: {e}")
            return None

    # ── 渲染 ──────────────────────────────────────────────

    def _render(self, r: AnalysisResult) -> None:
        lines = []
        for sec in r.sections:
            for item in sec.sorted_items():
                if not item.name and not item.value:
                    lines.append("")
                elif item.value:
                    v = f"{item.value}{item.unit}" if item.unit else item.value
                    lines.append(f"  {item.name}: {v}")
                else:
                    lines.append(f"{item.name}")
            lines.append("")
        self.text_area.setPlainText("\n".join(lines))

    def _render_dict(self, analyzed: dict) -> None:
        lines = []
        for sec in analyzed.get("sections", []):
            for item in sorted(sec.get("items", []), key=lambda x: x.get("order", 0)):
                name, value, unit = item.get("name", ""), item.get("value", ""), item.get("unit", "")
                if not name and not value:
                    lines.append("")
                elif value:
                    lines.append(f"  {name}: {value}{unit}" if unit else f"  {name}: {value}")
                else:
                    lines.append(f"{name}")
            lines.append("")
        self.text_area.setPlainText("\n".join(lines))

    def _show_hint(self) -> None:
        self.text_area.setPlainText(
            "👈 左侧选择分类和文件\n\n"
            "1. ⚙ 设置游戏目录\n"
            "2. 📦 加载数据\n"
            "3. 🔧 解析数据\n"
            "4. 🌐 语言文件\n"
            "5. 点击分类 → 选择文件"
        )

