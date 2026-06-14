"""
BrowserPanel —— 文件列表面板。

不再自带分类列表，分类由主窗口 CategoryBar 提供。
通过 bus.folder_selected 信号接收分类切换指令。
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from app.signals import bus
from utils.path_utils import get_split_dir


class BrowserPanel(QWidget):
    """文件列表面板"""

    file_selected = pyqtSignal(str, str)  # 分类名, 文件名(不含.json)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 4, 8)
        layout.setSpacing(6)

        # ── 搜索框 ────────────────────────────────────────
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 搜索文件名...")
        self.search_box.setStyleSheet("""
            QLineEdit { padding: 6px 8px; border: 1px solid #d0d0d0;
                border-radius: 4px; font-size: 12px; }
            QLineEdit:focus { border-color: #0078d4; }
        """)
        layout.addWidget(self.search_box)

        # ── 文件列表 ──────────────────────────────────────
        self.file_list = QListWidget()
        self.file_list.setFont(QFont("Microsoft YaHei", 10))
        self.file_list.setStyleSheet("""
            QListWidget { background-color: #fff; border: 1px solid #d0d0d0;
                border-radius: 4px; }
            QListWidget::item { padding: 6px 8px; }
            QListWidget::item:selected { background-color: #0078d4; color: #fff; }
            QListWidget::item:hover { background-color: #e5f1fb; }
        """)
        layout.addWidget(self.file_list, stretch=1)

        # ── 状态 ──────────────────────────────────────────
        self._current_folder = ""
        self._all_files: list[str] = []
        self._split_dir: Path = get_split_dir()

        # ── 信号连接 ──────────────────────────────────────
        self.file_list.currentTextChanged.connect(self._on_file_changed)
        self.search_box.textChanged.connect(self._apply_filter)
        bus.folder_selected.connect(self._on_category_selected)

    # ── 公共方法 ──────────────────────────────────────────

    def show_category(self, folder: str) -> None:
        """显示指定分类下的文件"""
        self._current_folder = folder
        self.file_list.clear()
        self._all_files = []

        target = self._split_dir / folder
        if not target.exists():
            return

        self._all_files = sorted(
            f.stem for f in target.iterdir() if f.suffix.lower() == ".json"
        )
        self._apply_filter(self.search_box.text())

    def refresh(self) -> None:
        """刷新当前分类"""
        if self._current_folder:
            self.show_category(self._current_folder)

    # ── 内部槽 ────────────────────────────────────────────

    def _on_category_selected(self, folder: str) -> None:
        if folder == "__REFRESH__":
            self.refresh()
        else:
            self.show_category(folder)

    def _on_file_changed(self, text: str) -> None:
        if not text or not self._current_folder:
            return
        filename = text.replace("📄 ", "").strip()
        self.file_selected.emit(self._current_folder, filename)

    def _apply_filter(self, keyword: str) -> None:
        self.file_list.clear()
        keyword = keyword.strip().lower()
        for fname in self._all_files:
            if not keyword or keyword in fname.lower():
                self.file_list.addItem(f"📄 {fname}")
