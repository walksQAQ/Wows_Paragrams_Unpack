"""
MainWindow —— 应用主窗口。

布局（基于 main_window.ui）：
  ┌──────────────────────────────────────────────────────┐
  │ [load data] [load lang] [set path] [refresh]  [Lesta] [WG] │
  ├────┬─────────────────────────────────────────────────┤
  │    │  ┌──────────────┬────────┬─────────────────┐    │
  │ 80 │  │  文件列表     │ 模块   │   详情面板       │    │
  │ px │  │  (200px)     │ (80px) │   (Stacked)     │    │
  │    │  └──────────────┴────────┴─────────────────┘    │
  ├────┴─────────────────────────────────────────────────┤
  │  QTextBrowser (日志, 固定高度)                       │
  └──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStatusBar, QLabel, QTextBrowser,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.signals import bus
from app.application import app
from ui.toolbar_widget import TopToolbar
from ui.category_bar import CategoryBar
from ui.browser_panel import BrowserPanel
from ui.module_select import ModuleSelect
from ui.detail_panel import DetailPanel


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mir Korabley/World of Warships — 游戏数据分析工具")
        self.resize(1440, 900)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 顶部工具栏（horizontalFrame）─────────────────
        self.toolbar = TopToolbar()
        main_layout.addWidget(self.toolbar)

        # ── 中间区域：分类栏 + 内容区（main_widget）───────
        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        # 左侧分类按钮栏（80px 固定）
        self.category_bar = CategoryBar()
        middle_layout.addWidget(self.category_bar)

        # 右侧内容区（widget_2, 展开）
        content_area = QWidget()
        content_layout = QHBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 文件列表面板（200px 固定）
        self.browser = BrowserPanel()
        self.browser.setVisible(False)  # 默认隐藏，选择分类后显示
        content_layout.addWidget(self.browser)

        # 模块选择区（80px 固定）
        self.module_select = ModuleSelect()
        self.module_select.setVisible(False)  # 默认隐藏，有模块数据时再显示
        content_layout.addWidget(self.module_select)

        # 详情面板（StackedWidget, 展开）
        self.detail = DetailPanel()
        content_layout.addWidget(self.detail, stretch=1)

        middle_layout.addWidget(content_area, stretch=1)
        main_layout.addWidget(middle, stretch=1)

        # ── 底部区域（日志面板）─────────────────────────
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.log_panel = QTextBrowser()
        self.log_panel.setReadOnly(True)
        _fnt = QFont()
        _fnt.setFamilies(["Microsoft YaHei", "Segoe UI", "sans-serif"])
        _fnt.setPointSize(9)
        self.log_panel.setFont(_fnt)
        self.log_panel.setFixedHeight(100)
        self.log_panel.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e1e;
                color: #cccccc;
                border: none;
                border-top: 1px solid #3c3c3c;
                padding: 4px 8px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
            }
        """)
        bottom_layout.addWidget(self.log_panel, stretch=1)

        main_layout.addWidget(bottom_widget)

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
        # 动态模块：DetailPanel 通知 ModuleSelect 更新按钮并控制显隐
        self.detail.modules_available.connect(self._on_modules_available)
        # 模块选择 → 详情页切换
        self.module_select.module_selected.connect(self.detail.switch_page)
        # 分类切换 → 显示/隐藏模块选择区（舰长类不显示三级菜单）
        bus.folder_selected.connect(self._on_category_changed)

        # 重置 UI 状态时取消所有选中项
        bus.data_loaded.connect(lambda _: self.clear_all_selections())
        bus.localization_ready.connect(self.clear_all_selections)

        # ── 窗口居中 ────────────────────────────────────
        QTimer.singleShot(0, self._center_window)

    # ── 菜单 ──────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")

        adv_action = settings_menu.addAction("高级设置...")
        adv_action.triggered.connect(self._on_advanced_settings)

        reset_action = settings_menu.addAction("重置软件设置")
        reset_action.triggered.connect(self._on_reset)

        menubar.addSeparator()

        about_action = menubar.addAction("关于")
        about_action.triggered.connect(self._on_about)

    def _on_advanced_settings(self) -> None:
        from ui.advanced_settings import AdvancedSettingsDialog
        dlg = AdvancedSettingsDialog(self)
        dlg.exec()

    def _on_reset(self) -> None:
        app.reset_all()
        bus.log_message.emit("配置已重置")

    def _on_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QCoreApplication

        import __about__

        ver = QCoreApplication.applicationVersion()

        QMessageBox.about(
            self,
            f"关于 {__about__.__title__}",
            (
                f"<h3>{__about__.__description__}</h3>"
                "<hr>"
                f"<p><b>版本：</b>{ver}</p>"
                f"<p><b>作者：</b>{__about__.__author__}</p>"
                f"<p><b>仓库：</b><a href='{__about__.__url__}'>{__about__.__url__}</a></p>"
                f"<p><b>许可证：</b>{__about__.__license__}</p>"
                "<hr>"
                "<p style='color: #888888; font-size: 11px;'>"
                "本工具仅供学习与研究使用，数据版权归原游戏厂商所有。"
                "</p>"
            ),
        )

    # ── 信号槽 ────────────────────────────────────────────

    def _on_log(self, message: str) -> None:
        self.status_label.setText(message)
        self.log_panel.append(message)

    def _on_category_changed(self, folder: str) -> None:
        """分类切换时控制各面板显隐并重置详情"""
        if folder != "__REFRESH__":
            self.browser.setVisible(True)
            self.detail.reset_to_default()
        else:
            # 刷新完成时取消所有选中
            self.clear_all_selections()
            return
        # 切换分类时隐藏模块选择栏，由 _on_modules_available 决定是否显示
        self.module_select.setVisible(False)

    def _on_modules_available(self, section_labels: object) -> None:
        """模块列表可用时更新 ModuleSelect 并控制显隐"""
        self.module_select.set_modules(section_labels)
        self.module_select.setVisible(section_labels is not None)

    def clear_all_selections(self) -> None:
        """取消界面上所有选中项"""
        self.category_bar.clear_selection()
        self.browser.file_list.clearSelection()
        self.module_select.clear_selection()
        self.detail.reset_to_default()
        self.module_select.setVisible(False)

    # ── 窗口管理 ──────────────────────────────────────────

    def _center_window(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = (geo.width() - self.width()) // 2
        y = (geo.height() - self.height()) // 2
        self.move(x, y)
