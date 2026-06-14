"""
CategoryBar —— 左侧分类按钮栏。

每个按钮对应 data/split/ 下的一个分类文件夹。
点击后触发文件列表切换。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

from app.signals import bus
from utils.path_utils import get_split_dir


class CategoryBar(QWidget):
    """左侧分类按钮栏"""

    category_selected = pyqtSignal(str)  # 参数: 分类名

    # 分类定义：(显示名, 图标, 文件夹名)
    CATEGORIES = [
        ("🚢  舰船", "Ship"),
        ("🔫  火炮", "Gun"),
        ("💥  弹药", "Projectile"),
        ("⚡  升级品", "Modernization"),
        ("✈️  飞机", "Aircraft"),
        ("💊  消耗品", "Ability"),
        ("👤  舰长", "Crew"),
    ]

    BTN_STYLE = """
        QPushButton {
            background-color: transparent;
            color: #ccc;
            border: none;
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 12px;
            text-align: left;
        }
        QPushButton:hover {
            background-color: #3a3a3a;
            color: #fff;
        }
        QPushButton:checked {
            background-color: #0078d4;
            color: #fff;
            font-weight: bold;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CategoryBar")
        self.setFixedWidth(140)
        self.setStyleSheet("""
            #CategoryBar {
                background-color: #1e1e1e;
                border-right: 1px solid #3c3c3c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        title = QLabel("数据分类")
        title.setStyleSheet("color: #888; font-size: 11px; padding: 4px 8px;")
        layout.addWidget(title)

        self._btns: list[QPushButton] = []
        self._group = None  # 用于互斥

        for display_name, folder in self.CATEGORIES:
            btn = QPushButton(display_name)
            btn.setCheckable(True)
            btn.setStyleSheet(self.BTN_STYLE)
            btn.clicked.connect(lambda checked, f=folder: self._on_category(f))
            layout.addWidget(btn)
            self._btns.append(btn)

        layout.addStretch()

        # 日志输出（精简版）
        self.log_label = QLabel("日志")
        self.log_label.setStyleSheet("color: #666; font-size: 10px; padding: 4px 8px;")
        layout.addWidget(self.log_label)

        self._active = None

    def _on_category(self, folder: str) -> None:
        """分类按钮点击"""
        for btn in self._btns:
            btn.setChecked(btn.text().endswith(folder) or
                           any(folder in btn.text() for _ in [0]))
        # 用文本匹配找到对应按钮
        for display, fld in self.CATEGORIES:
            if fld == folder:
                for btn in self._btns:
                    btn.setChecked(display in btn.text())
                break
        self._active = folder
        self.category_selected.emit(folder)
        bus.folder_selected.emit(folder)
