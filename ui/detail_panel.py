"""
DetailPanel —— 右侧详情展示面板。

使用 QStackedWidget 在三种展示模式间切换：
  0: 空状态（提示）
  1: 富文本（QTabWidget + QFormLayout 分栏展示）
  2: 纯文本/JSON 兜底
"""

from __future__ import annotations

import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QStackedWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from app.signals import bus
from models.analysis_result import AnalysisResult
from utils.path_utils import get_split_dir
from analyzers.base_analyzer import BaseAnalyzer
from ui.renderers.rich_renderer import RichResultWidget


class DetailPanel(QWidget):
    """右侧详情面板"""

    # QStackedWidget 的页面索引
    _PAGE_EMPTY = 0
    _PAGE_RICH = 1
    _PAGE_FALLBACK = 2

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 注册分析器 ────────────────────────────────────
        self._analyzers: dict[str, BaseAnalyzer] = {}
        self._init_analyzers()

        # ── QStackedWidget 管理三种展示模式 ──────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()

        # Page 0: 空状态提示
        self._empty_page = QLabel(
            "👈 请在左侧选择一个数据分类和文件\n\n"
            "提示：\n"
            "  1. 先点击「设置游戏目录」选择游戏路径\n"
            "  2. 点击「加载数据文件」提取游戏数据\n"
            "  3. 点击「解析数据文件」拆分数据\n"
            "  4. 点击「加载语言文件」获取中文翻译\n"
            "  5. 然后在中间浏览面板选择要查看的数据"
        )
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_page.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        self.stack.addWidget(self._empty_page)  # index 0

        # Page 1: 富文本展示（运行时动态填充）
        self._rich_container = QWidget()
        self._rich_layout = QVBoxLayout(self._rich_container)
        self._rich_layout.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self._rich_container)  # index 1

        # Page 2: 纯文本/JSON 兜底
        self._fallback_text = QTextEdit()
        self._fallback_text.setReadOnly(True)
        self._fallback_text.setFont(QFont("Consolas", 11))
        self._fallback_text.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #1a1a1a;
                border: none;
                padding: 8px;
            }
        """)
        self.stack.addWidget(self._fallback_text)  # index 2

        layout.addWidget(self.stack)

        # ── 默认显示空状态 ────────────────────────────────
        self.stack.setCurrentIndex(self._PAGE_EMPTY)

        # ── 信号连接 ──────────────────────────────────────
        bus.file_selected.connect(self._on_file_selected)
        bus.localization_ready.connect(self._reload_analyzer_mappings)

    # ── 分析器管理 ────────────────────────────────────────

    def _init_analyzers(self) -> None:
        from analyzers.ship_analyzer import ShipAnalyzer
        from analyzers.gun_analyzer import GunAnalyzer
        from analyzers.projectile_analyzer import ProjectileAnalyzer
        from analyzers.modernization_analyzer import ModernizationAnalyzer
        from analyzers.plane_analyzer import PlaneAnalyzer
        from analyzers.consumable_analyzer import ConsumableAnalyzer
        from analyzers.crew_analyzer import CrewAnalyzer

        registry: list[tuple[str, BaseAnalyzer]] = [
            ("Ship", ShipAnalyzer()),
            ("Gun", GunAnalyzer()),
            ("Projectile", ProjectileAnalyzer()),
            ("Modernization", ModernizationAnalyzer()),
            ("Aircraft", PlaneAnalyzer()),
            ("Ability", ConsumableAnalyzer()),
            ("Crew", CrewAnalyzer()),
        ]
        for name, analyzer in registry:
            try:
                analyzer.initialize_mapping()
                self._analyzers[name] = analyzer
            except Exception as e:
                print(f"{name}Analyzer 初始化失败: {e}")

    def _reload_analyzer_mappings(self) -> None:
        for name, analyzer in self._analyzers.items():
            try:
                analyzer.initialize_mapping()
            except Exception as e:
                print(f"分析器 {name} 重载映射表失败: {e}")
        bus.log_message.emit("✅ 所有分析器映射表已重载")

    # ── 信号槽 ────────────────────────────────────────────

    def _on_file_selected(self, category: str, filename: str) -> None:
        file_path = get_split_dir() / category / f"{filename}.json"
        if not file_path.exists():
            self._show_fallback(f"文件不存在: {file_path}")
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            self._show_fallback(f"读取文件失败: {e}")
            return

        result = self._try_analyze(category, raw_data)
        if result is not None:
            self._show_rich(result)
        else:
            self._show_fallback(json.dumps(raw_data, indent=4, ensure_ascii=False))

    # ── 分析路由 ──────────────────────────────────────────

    def _try_analyze(self, category: str, raw_data: dict) -> AnalysisResult | None:
        analyzer = self._analyzers.get(category)
        if analyzer is not None:
            try:
                return analyzer.analyze(raw_data)
            except Exception as e:
                bus.log_message.emit(f"分析器({category})执行失败: {e}")
        return None

    # ── 页面切换 ──────────────────────────────────────────

    def _show_rich(self, result: AnalysisResult) -> None:
        """切换到富文本模式，展示 AnalysisResult"""
        # 清除旧的富文本内容
        self._clear_layout(self._rich_layout)
        widget = RichResultWidget(result)
        self._rich_layout.addWidget(widget)
        self.stack.setCurrentIndex(self._PAGE_RICH)

    def _show_fallback(self, text: str) -> None:
        """切换到兜底纯文本模式"""
        self._fallback_text.setPlainText(text)
        self.stack.setCurrentIndex(self._PAGE_FALLBACK)

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _clear_layout(layout) -> None:
        """清空布局中的所有子控件"""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

