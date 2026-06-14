"""
TopToolbar —— 顶部工具栏。

包含：操作按钮 + 服务器选择 + 进度条
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel,
    QButtonGroup, QRadioButton, QProgressBar, QFrame,
)
from PySide6.QtCore import Qt

from app.signals import bus
from app.application import app as app_ctx


class TopToolbar(QWidget):
    """顶部工具栏"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopToolbar")
        self.setStyleSheet("""
            #TopToolbar {
                background-color: #2b2b2b;
                border-bottom: 1px solid #3c3c3c;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # ── 操作按钮 ──────────────────────────────────────
        btn_style = """
            QPushButton {
                background-color: #3a3a3a; color: #fff;
                border: 1px solid #555; border-radius: 4px;
                padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #4a4a4a; border-color: #0078d4; }
            QPushButton:disabled { background-color: #2a2a2a; color: #666; }
        """
        self.btn_load = QPushButton("📦 加载数据")
        self.btn_process = QPushButton("🔧 解析数据")
        self.btn_lang = QPushButton("🌐 语言文件")
        self.btn_refresh = QPushButton("🔄 刷新界面")
        self.btn_settings = QPushButton("⚙ 设置游戏目录")
        for b in (self.btn_load, self.btn_process, self.btn_lang, self.btn_refresh, self.btn_settings):
            b.setStyleSheet(btn_style)
            layout.addWidget(b)
        self.btn_process.setEnabled(False)

        layout.addStretch()

        # ── 服务器选择 ────────────────────────────────────
        self.addWidget(QLabel("服务器:"), layout)
        sg = QButtonGroup(self)
        self.rb_wg = QRadioButton("Wargaming")
        self.rb_lesta = QRadioButton("Lesta")
        for rb in (self.rb_wg, self.rb_lesta):
            rb.setStyleSheet("color: #ccc; font-size: 12px;")
            sg.addButton(rb)
            layout.addWidget(rb)
        sg.buttonClicked.connect(self._on_server)

        layout.addSpacing(16)

        # ── 进度条 ────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedWidth(160)
        self.progress.setFixedHeight(18)
        self.progress.setStyleSheet("""
            QProgressBar { border: 1px solid #555; border-radius: 3px;
                background: #2a2a2a; color: #fff; font-size: 10px; text-align: center; }
            QProgressBar::chunk { background: #0078d4; border-radius: 2px; }
        """)
        layout.addWidget(self.progress)

        # ── 信号 ──────────────────────────────────────────
        self.btn_load.clicked.connect(self._on_load)
        self.btn_process.clicked.connect(self._on_process)
        self.btn_lang.clicked.connect(self._on_lang)
        self.btn_refresh.clicked.connect(lambda: bus.folder_selected.emit("__REFRESH__"))
        self.btn_settings.clicked.connect(self._on_settings)
        bus.can_process_data.connect(self.btn_process.setEnabled)
        bus.task_progress.connect(self._on_progress)
        bus.data_loaded.connect(lambda _: self._enable_all())
        bus.localization_ready.connect(self._enable_all)
        bus.data_processed.connect(lambda _: self._enable_all())

        self._sync_server()

    # ── 信号处理 ──────────────────────────────────────────

    def _on_load(self):
        from services.extractor_service import run_extract
        self._disable_all()
        bus.log_message.emit("正在加载游戏数据...")
        run_extract()

    def _on_process(self):
        from services.processor_service import run_process
        self.btn_process.setEnabled(False)
        bus.log_message.emit("正在解析数据文件...")
        run_process()

    def _on_lang(self):
        from services.localization_service import run_localization
        self.btn_lang.setEnabled(False)
        bus.log_message.emit("正在加载语言文件...")
        run_localization()

    def _on_settings(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择游戏目录", app_ctx.ctx.game_path)
        if d:
            app_ctx.set_game_path(d)
            bus.log_message.emit(f"已选择: {d}")

    def _on_server(self, btn):
        app_ctx.set_wows_type(btn.text())

    def _on_progress(self, pct, msg):
        if pct <= 0 or pct >= 100:
            self.progress.setVisible(False)
        else:
            self.progress.setValue(pct)
            self.progress.setFormat(f"{msg} ({pct}%)")
            self.progress.setVisible(True)

    def _disable_all(self):
        self.btn_load.setEnabled(False)
        self.btn_process.setEnabled(False)
        self.btn_lang.setEnabled(False)

    def _enable_all(self):
        self.btn_load.setEnabled(True)
        self.btn_process.setEnabled(app_ctx.ctx.game_data_state)
        self.btn_lang.setEnabled(True)
        self.progress.setVisible(False)

    def _sync_server(self):
        t = app_ctx.ctx.wows_type
        if t == "Wargaming":
            self.rb_wg.setChecked(True)
        elif t == "Lesta":
            self.rb_lesta.setChecked(True)

    @staticmethod
    def addWidget(w, layout):
        w.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(w)
