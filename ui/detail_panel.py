"""
DetailPanel —— 右侧详情展示面板。

纯文本模式。
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
from analyzers.base_analyzer import BaseAnalyzer


class DetailPanel(QWidget):
    """右侧详情面板"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._analyzers: dict[str, BaseAnalyzer] = {}
        self._init_analyzers()

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
        bus.localization_ready.connect(self._reload_analyzer_mappings)

    def _init_analyzers(self) -> None:
        from analyzers.ship_analyzer import ShipAnalyzer
        from analyzers.gun_analyzer import GunAnalyzer
        from analyzers.projectile_analyzer import ProjectileAnalyzer
        from analyzers.modernization_analyzer import ModernizationAnalyzer
        from analyzers.plane_analyzer import PlaneAnalyzer
        from analyzers.consumable_analyzer import ConsumableAnalyzer
        from analyzers.crew_analyzer import CrewAnalyzer
        for name, cls in [
            ("Ship", ShipAnalyzer), ("Gun", GunAnalyzer),
            ("Projectile", ProjectileAnalyzer), ("Modernization", ModernizationAnalyzer),
            ("Aircraft", PlaneAnalyzer), ("Ability", ConsumableAnalyzer),
            ("Crew", CrewAnalyzer),
        ]:
            try:
                a = cls(); a.initialize_mapping(); self._analyzers[name] = a
            except Exception as e:
                print(f"{name}Analyzer 初始化失败: {e}")

    def _reload_analyzer_mappings(self) -> None:
        for name, a in self._analyzers.items():
            try:
                a.initialize_mapping()
            except Exception as e:
                print(f"映射表重载失败 {name}: {e}")
        bus.log_message.emit("✅ 所有分析器映射表已重载")

    def _on_file_selected(self, category: str, filename: str) -> None:
        fp = get_split_dir() / category / f"{filename}.json"
        if not fp.exists():
            self.text_area.setPlainText(f"文件不存在: {fp}"); return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self.text_area.setPlainText(f"读取失败: {e}"); return
        result = self._try_analyze(category, raw)
        if result:
            self._render(result)
        else:
            self.text_area.setPlainText(json.dumps(raw, indent=4, ensure_ascii=False))

    def _try_analyze(self, category: str, raw: dict) -> AnalysisResult | None:
        a = self._analyzers.get(category)
        if a:
            try:
                return a.analyze(raw)
            except Exception as e:
                bus.log_message.emit(f"分析器({category})失败: {e}")
        return None

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

    def _show_hint(self) -> None:
        self.text_area.setPlainText(
            "👈 左侧选择分类和文件\n\n"
            "1. ⚙ 设置游戏目录\n"
            "2. 📦 加载数据\n"
            "3. 🔧 解析数据\n"
            "4. 🌐 语言文件\n"
            "5. 点击分类 → 选择文件"
        )

