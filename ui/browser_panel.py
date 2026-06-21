"""
BrowserPanel —— 文件列表面板（200px 固定宽度）。

匹配 main_window.ui 中 scrollArea / item_select 区域。
不再自带分类列表，分类由主窗口 CategoryBar 提供。
通过 bus.folder_selected 信号接收分类切换指令。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout,
    QListWidget, QLineEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from app.signals import bus
from utils.path_utils import get_split_dir
from services.database_service import get_db


class BrowserPanel(QWidget):
    """文件列表面板（200px 固定宽度）"""

    file_selected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowserPanel")
        self.setFixedWidth(200)
        self.setStyleSheet("""
            #BrowserPanel {
                background-color: #f0f0f0;
                border-right: 1px solid #d0d0d0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 搜索文件名...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                padding: 4px 6px;
                border: 1px solid #c0c0c0;
                border-radius: 3px;
                font-size: 11px;
                background-color: #ffffff;
            }
            QLineEdit:focus { border-color: #0078d4; }
        """)
        layout.addWidget(self.search_box)

        self.file_list = QListWidget()
        self.file_list.setFont(QFont("Microsoft YaHei", 10))
        self.file_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 3px 6px;
                font-size: 12px;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #e5f1fb;
            }
        """)
        layout.addWidget(self.file_list, stretch=1)

        self._current_folder = ""
        self._all_files: list[str] = []
        self._split_dir = get_split_dir()

        self.file_list.currentTextChanged.connect(self._on_file_changed)
        self.search_box.textChanged.connect(self._apply_filter)
        bus.folder_selected.connect(self._on_category_selected)

    def show_category(self, folder: str) -> None:
        self._current_folder = folder
        self.file_list.clear()
        self._all_files = []

        # 优先使用数据库
        db = get_db()
        if db.exists:
            try:
                rows = db.list_entities(folder)
                self._all_files = [r["id"] for r in rows]
                self._apply_filter(self.search_box.text())
                return
            except Exception:
                pass

        # 降级到文件系统
        target = self._split_dir / folder
        if not target.exists():
            return
        self._all_files = sorted(f.stem for f in target.iterdir() if f.suffix.lower() == ".json")
        self._apply_filter(self.search_box.text())

    def refresh(self) -> None:
        if self._current_folder:
            self.show_category(self._current_folder)

    def _on_category_selected(self, folder: str) -> None:
        if folder == "__REFRESH__":
            self.refresh()
        else:
            self.show_category(folder)

    def _on_file_changed(self, text: str) -> None:
        if not text or not self._current_folder:
            return
        self.file_selected.emit(self._current_folder, text.replace("📄 ", "").strip())

    def _apply_filter(self, keyword: str) -> None:
        self.file_list.clear()
        keyword = keyword.strip().lower()
        if not keyword:
            for fname in self._all_files:
                self.file_list.addItem(f"📄 {fname}")
            return

        # 数据库全文搜索
        db = get_db()
        if db.exists and self._current_folder:
            try:
                for r in db.search_entities(self._current_folder, keyword):
                    self.file_list.addItem(f"📄 {r['id']}")
                return
            except Exception:
                pass

        # 内存过滤
        for fname in self._all_files:
            if keyword in fname.lower():
                self.file_list.addItem(f"📄 {fname}")
