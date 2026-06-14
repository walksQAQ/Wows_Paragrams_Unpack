"""
SidebarWidget —— 左侧边栏。

包含：
  - 应用 Logo / 标题
  - 功能按钮组（加载数据、解析数据、加载语言文件、刷新界面、设置游戏目录）
  - 服务器环境选择器（Wargaming / Lesta）
  - 日志输出面板
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QButtonGroup, QRadioButton,
    QSizePolicy, QFrame, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.signals import bus
from app.application import app as app_ctx


class SidebarWidget(QWidget):
    """应用左侧边栏"""

    BUTTON_STYLE = """
        QPushButton {
            background-color: #3a3a3a;
            color: #ffffff;
            border: 1px solid #555555;
            border-radius: 6px;
            padding: 10px 16px;
            font-size: 13px;
            text-align: left;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
            border-color: #0078d4;
        }
        QPushButton:disabled {
            background-color: #2a2a2a;
            color: #666666;
        }
        QPushButton:pressed {
            background-color: #0078d4;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarWidget")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 标题 ──────────────────────────────────────────
        title = QLabel("WOWS 数据工具")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; padding: 8px 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # ── 分隔线 ────────────────────────────────────────
        layout.addWidget(self._separator())

        # ── 按钮组 ────────────────────────────────────────
        self.btn_load_data = QPushButton("📦  加载数据文件")
        self.btn_load_data.setStyleSheet(self.BUTTON_STYLE)
        layout.addWidget(self.btn_load_data)

        self.btn_process_data = QPushButton("🔧  解析数据文件")
        self.btn_process_data.setStyleSheet(self.BUTTON_STYLE)
        self.btn_process_data.setEnabled(False)
        layout.addWidget(self.btn_process_data)

        self.btn_refresh = QPushButton("🔄  刷新界面")
        self.btn_refresh.setStyleSheet(self.BUTTON_STYLE)
        layout.addWidget(self.btn_refresh)

        self.btn_localization = QPushButton("🌐  加载语言文件")
        self.btn_localization.setStyleSheet(self.BUTTON_STYLE)
        layout.addWidget(self.btn_localization)

        self.btn_settings = QPushButton("⚙  设置游戏目录")
        self.btn_settings.setStyleSheet(self.BUTTON_STYLE + """
            QPushButton { background-color: #555555; }
        """)
        layout.addWidget(self.btn_settings)

        # ── 服务器选择 ────────────────────────────────────
        layout.addWidget(self._separator())
        server_label = QLabel("当前服务器环境:")
        server_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        layout.addWidget(server_label)

        server_layout = QHBoxLayout()
        self.server_group = QButtonGroup(self)
        self.rb_wg = QRadioButton("Wargaming")
        self.rb_lesta = QRadioButton("Lesta")
        for rb in (self.rb_wg, self.rb_lesta):
            rb.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.server_group.addButton(self.rb_wg)
        self.server_group.addButton(self.rb_lesta)
        server_layout.addWidget(self.rb_wg)
        server_layout.addWidget(self.rb_lesta)
        layout.addLayout(server_layout)

        # ── 进度条 ────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                background-color: #2a2a2a;
                color: #ffffff;
                font-size: 11px;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # ── 日志面板 ──────────────────────────────────────
        layout.addWidget(self._separator())
        log_label = QLabel("日志输出:")
        log_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        layout.addWidget(log_label)

        self.log_area = QTextEdit()
        self.log_area.setObjectName("LogArea")
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 10))
        self.log_area.setStyleSheet("""
            QTextEdit#LogArea {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.log_area, stretch=1)

        # ── 信号连接 ──────────────────────────────────────
        self._connect_signals()

        # ── 初始状态同步 ──────────────────────────────────
        self._sync_server_radio()

    # ── 连接信号 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        bus.log_message.connect(self._on_log)
        bus.can_process_data.connect(self.btn_process_data.setEnabled)
        bus.data_loaded.connect(lambda _: self._enable_buttons())
        bus.localization_ready.connect(self._enable_buttons)
        bus.task_progress.connect(self._on_progress)

        self.btn_load_data.clicked.connect(self._on_load_data)
        self.btn_process_data.clicked.connect(self._on_process_data)
        self.btn_refresh.clicked.connect(self._on_refresh)
        self.btn_localization.clicked.connect(self._on_localization)
        self.btn_settings.clicked.connect(self._on_settings)

        self.server_group.buttonClicked.connect(self._on_server_changed)

    # ── 信号槽 ────────────────────────────────────────────

    def _on_log(self, message: str) -> None:
        self.log_area.append(message)
        # 自动滚到底部
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_load_data(self) -> None:
        """加载游戏数据（从游戏目录提取 GameParams.data）"""
        ctx = app_ctx.ctx
        if ctx.wows_type == "未选择":
            bus.log_message.emit("❌ 请先选择服务器环境 (Wargaming / Lesta)")
            return
        if ctx.game_path == "未设置":
            bus.log_message.emit("❌ 请先设置游戏目录")
            return

        self.btn_load_data.setEnabled(False)
        bus.log_message.emit("正在加载游戏数据...")

        from services.extractor_service import run_extract
        run_extract()

    def _on_process_data(self) -> None:
        """解析并拆分游戏数据"""
        self.btn_process_data.setEnabled(False)
        bus.log_message.emit("正在解析数据文件...")

        from services.processor_service import run_process
        run_process()

    def _on_refresh(self) -> None:
        bus.log_message.emit("🔄 正在刷新...")
        # 通过信号触发 browser_panel 刷新
        bus.folder_selected.emit("__REFRESH__")

    def _on_localization(self) -> None:
        """加载语言文件"""
        ctx = app_ctx.ctx
        if ctx.wows_type == "未选择":
            bus.log_message.emit("❌ 请先选择服务器环境")
            return
        if ctx.game_path == "未设置":
            bus.log_message.emit("❌ 请先设置游戏目录")
            return

        self.btn_localization.setEnabled(False)
        bus.log_message.emit(f"正在加载 {ctx.wows_type} 客户端文本数据...")

        from services.localization_service import run_localization
        run_localization()

    def _on_settings(self) -> None:
        """打开游戏目录选择对话框"""
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            self, "选择游戏安装目录", app_ctx.ctx.game_path
        )
        if directory:
            app_ctx.set_game_path(directory)
            bus.log_message.emit(f"已选择游戏目录: {directory}")

    def _on_server_changed(self, button: QRadioButton) -> None:
        value = button.text()
        app_ctx.set_wows_type(value)

    def _on_progress(self, percent: int, message: str) -> None:
        """更新进度条"""
        if percent <= 0 or percent >= 100:
            self.progress_bar.setVisible(False)
        else:
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{message} ({percent}%)")
            self.progress_bar.setVisible(True)

    def _sync_server_radio(self) -> None:
        """根据当前配置同步单选按钮状态"""
        wows_type = app_ctx.ctx.wows_type
        if wows_type == "Wargaming":
            self.rb_wg.setChecked(True)
        elif wows_type == "Lesta":
            self.rb_lesta.setChecked(True)
        # "未选择" 时都不选中

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: #3c3c3c;")
        return sep

    def _enable_buttons(self) -> None:
        """统一恢复所有按钮"""
        self.btn_load_data.setEnabled(True)
        self.btn_process_data.setEnabled(app_ctx.ctx.game_data_state)
        self.btn_localization.setEnabled(True)
        self.progress_bar.setVisible(False)
