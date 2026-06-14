"""
MainWindow —— 应用主窗口。

布局：
  ┌────────────────────────────────────────────┐
  │  TopToolbar (操作按钮 + 服务器 + 进度条)    │
  ├──────┬─────────────────────────────────────┤
  │      │  ┌──────────┬────────────────────┐  │
  │ 分类  │  │ 文件列表  │    详情面板        │  │
  │ 按钮  │  │          │                    │  │
  │      │  └──────────┴────────────────────┘  │
  ├──────┴─────────────────────────────────────┤
  │  状态栏                                     │
  └────────────────────────────────────────────┘
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QLabel, QMenuBar, QMenu,
    QTextEdit,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from app.signals import bus
from app.application import app
from ui.toolbar_widget import TopToolbar
from ui.category_bar import CategoryBar
from ui.browser_panel import BrowserPanel
from ui.detail_panel import DetailPanel


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mir Korabley / World of Warships — 游戏数据分析工具")
        self.resize(1400, 850)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 顶部工具栏 ──────────────────────────────────
        self.toolbar = TopToolbar()
        main_layout.addWidget(self.toolbar)

        # ── 中间区域：分类栏 + 内容区 ────────────────────
        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        self.category_bar = CategoryBar()
        middle_layout.addWidget(self.category_bar)

        # 内容区：文件列表 + 详情面板（可拖拽分割）
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setHandleWidth(1)
        content_splitter.setStyleSheet("QSplitter::handle { background-color: #d0d0d0; }")

        self.browser = BrowserPanel()
        self.detail = DetailPanel()
        content_splitter.addWidget(self.browser)
        content_splitter.addWidget(self.detail)
        content_splitter.setSizes([300, 800])

        middle_layout.addWidget(content_splitter, stretch=1)
        main_layout.addWidget(middle, stretch=1)

        # ── 日志面板（右下角）────────────────────────────
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFont(QFont("Microsoft YaHei", 9))
        self.log_panel.setFixedHeight(80)
        self.log_panel.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e; color: #ccc;
                border: none; border-top: 1px solid #3c3c3c;
                padding: 4px 8px;
            }
        """)
        self.log_panel.setVisible(False)
        main_layout.addWidget(self.log_panel)

        # ── 状态栏 ──────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addPermanentWidget(self.status_label)

        # ── 菜单栏 ──────────────────────────────────────
        self._setup_menu()

        # ── 信号连接 ────────────────────────────────────
        bus.log_message.connect(self._on_log)
        self.browser.file_selected.connect(bus.file_selected.emit)

        # ── 窗口居中 ────────────────────────────────────
        QTimer.singleShot(0, self._center_window)

    # ── 菜单 ──────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("高级选项")
        reset_action = settings_menu.addAction("重置软件设置")
        reset_action.triggered.connect(self._on_reset)

    def _on_reset(self) -> None:
        app.reset_all()
        bus.log_message.emit("配置已重置")

    # ── 信号槽 ────────────────────────────────────────────

    def _on_log(self, message: str) -> None:
        self.status_label.setText(message)
        self.log_panel.append(message)
        if not self.log_panel.isVisible():
            self.log_panel.setVisible(True)

    # ── 窗口管理 ──────────────────────────────────────────

    def _center_window(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = (geo.width() - self.width()) // 2
        y = (geo.height() - self.height()) // 2
        self.move(x, y)
