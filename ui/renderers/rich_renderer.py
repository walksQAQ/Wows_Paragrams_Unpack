"""
SectionWidget —— 将 DataSection 渲染为 QFormLayout 的可滚动面板。

替代旧代码中纯文本 insert(tk.END) 的方式，
每个字段以 Key: Value 的形式展示在整洁的表单布局中。
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel,
    QScrollArea, QGroupBox, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from models.analysis_result import DataSection, DataItem


class SectionWidget(QScrollArea):
    """将单个 DataSection 渲染为一个带 GroupBox 的可滚动面板"""

    def __init__(self, section: DataSection, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(self.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── GroupBox 作为区段容器 ──────────────────────────
        group = QGroupBox(section.label)
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #1a1a1a;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 8px 8px 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                background-color: #ffffff;
            }
        """)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(6)
        form.setContentsMargins(8, 12, 8, 8)

        for item in section.sorted_items():
            self._add_item(form, item)

        layout.addWidget(group)
        layout.addStretch()
        self.setWidget(container)

    def _add_item(self, form: QFormLayout, item: DataItem) -> None:
        """向表单中添加一个条目"""
        label = QLabel(item.name)
        label.setStyleSheet("font-size: 13px; color: #555; font-weight: normal;")
        label.setMinimumWidth(140)

        value_text = f"{item.value}{item.unit}" if item.unit else item.value
        value_label = QLabel(value_text)
        value_label.setStyleSheet("font-size: 13px; color: #1a1a1a; font-weight: normal;")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        form.addRow(label, value_label)


class RichResultWidget(QWidget):
    """
    将 AnalysisResult 渲染为带 QTabWidget 的面板。
    每个 DataSection 作为一个 Tab。
    """

    def __init__(self, result, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题区 ────────────────────────────────────────
        header = QLabel(f"<h2>{result.title}</h2>")
        header.setStyleSheet("""
            QLabel {
                padding: 12px 16px 4px 16px;
                color: #1a1a1a;
            }
        """)
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        if result.subtitle:
            sub = QLabel(f"<p style='color:#888;margin:0 16px 8px 16px;'>{result.subtitle}</p>")
            sub.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(sub)

        if not result.sections:
            empty = QLabel("无数据")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #999; font-size: 14px; padding: 40px;")
            layout.addWidget(empty)
            return

        # ── Tab 切换（当只有一个区段时不显示 Tab）──────────
        if len(result.sections) == 1:
            scroll = SectionWidget(result.sections[0])
            layout.addWidget(scroll, stretch=1)
        else:
            from PyQt6.QtWidgets import QTabWidget
            tabs = QTabWidget()
            tabs.setDocumentMode(True)
            tabs.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background: #ffffff;
                }
                QTabBar::tab {
                    padding: 6px 16px;
                    font-size: 12px;
                }
                QTabBar::tab:selected {
                    font-weight: bold;
                }
            """)
            for section in result.sections:
                scroll = SectionWidget(section)
                tabs.addTab(scroll, section.label)
            layout.addWidget(tabs, stretch=1)
