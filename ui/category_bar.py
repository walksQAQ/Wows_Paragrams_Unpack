"""
CategoryBar —— 左侧分类按钮栏。

图标在上，文字在下，每行显示一个分类。
一级菜单只显示 舰船 和 舰长 两类。
点击后触发文件列表切换。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal

from app.signals import bus


class CategoryBar(QWidget):
    """左侧分类按钮栏"""

    category_selected = Signal(str)  # 参数: 分类名

    # 分类定义：(图标, 显示名, 文件夹名)
    CATEGORIES = [
        ("🚢", "舰船", "Ship"),
        ("👤", "舰长", "Crew"),
    ]

    BTN_STYLE = """
        QPushButton {
            background-color: transparent;
            color: #000000;
            border: none;
            border-radius: 8px;
            padding: 10px 4px;
        }
        QPushButton:hover {
            background-color: #3a3a3a;
            color: #ffffff;
        }
        QPushButton:checked {
            background-color: #0078d4;
            color: #ffffff;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CategoryBar")
        self.setFixedWidth(80)
        self.setStyleSheet("""
            #CategoryBar {
                background-color: #252526;
                border-right: 1px solid #3c3c3c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._btns: list[QPushButton] = []
        self._active: str | None = None

        for icon, label, folder in self.CATEGORIES:
            btn = QPushButton(f"{icon}\n{label}")
            btn.setToolTip(label)
            btn.setCheckable(True)
            btn.setStyleSheet(self.BTN_STYLE)
            # 图标大号，文字小号
            btn.setFont(self.font())
            btn.clicked.connect(lambda checked, f=folder: self._on_category(f))
            layout.addWidget(btn)
            self._btns.append(btn)

        # 启动时不选中任何分类，由用户点击触发

        layout.addStretch()

    def _on_category(self, folder: str) -> None:
        """分类按钮点击"""
        for btn, (_, _, cat_folder) in zip(self._btns, self.CATEGORIES):
            btn.setChecked(cat_folder == folder)
        self._active = folder
        self.category_selected.emit(folder)
        bus.folder_selected.emit(folder)
