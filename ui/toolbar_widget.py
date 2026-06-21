"""
TopToolbar —— 顶部工具栏。

按钮（中文，合并加载+解析）：
  [📦 加载数据] [🌐 加载文本] [🔄 刷新界面]   [Lesta] [Wargaming]
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel,
    QButtonGroup, QRadioButton, QProgressBar,
)
from PySide6.QtCore import Qt

from app.signals import bus
from app.application import app as app_ctx


class TopToolbar(QWidget):
    """顶部工具栏"""

    BTN_STYLE = """
        QPushButton {
            background-color: #3a3a3a; color: #ffffff;
            border: 1px solid #555555; border-radius: 4px;
            padding: 6px 14px; font-size: 12px;
        }
        QPushButton:hover { background-color: #4a4a4a; border-color: #0078d4; }
        QPushButton:disabled { background-color: #2a2a2a; color: #666666; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopToolbar")
        self.setStyleSheet("""
            #TopToolbar {
                background-color: #2b2b2b;
                border-bottom: 1px solid #3c3c3c;
            }
        """)

        # 标记：是否正在执行加载→解析串联流程
        self._pending_process: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # ── 操作按钮（中文）─
        self.btn_load = QPushButton("📦  加载数据")
        self.btn_lang = QPushButton("🌐  加载文本")
        self.btn_refresh = QPushButton("🔄  刷新界面")

        for b in (self.btn_load, self.btn_lang, self.btn_refresh):
            b.setStyleSheet(self.BTN_STYLE)
            layout.addWidget(b)

        layout.addStretch()

        # ── 进度条（服务器选择左侧） ─
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedWidth(200)
        self.progress.setFixedHeight(22)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #0078d4; border-radius: 4px;
                background: #1a1a1a; color: #ffffff;
                font-size: 11px; font-weight: bold;
                text-align: center;
                padding: 0 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0078d4, stop:1 #00a0ff);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress)

        # ── 服务器选择 ─
        lbl_server = QLabel("服务器选项：")
        lbl_server.setStyleSheet("color: #cccccc; font-size: 12px;")
        layout.addWidget(lbl_server)

        sg = QButtonGroup(self)
        self.rb_lesta = QRadioButton("Lesta")
        self.rb_wg = QRadioButton("Wargaming")
        for rb in (self.rb_lesta, self.rb_wg):
            rb.setStyleSheet("color: #cccccc; font-size: 12px; spacing: 4px;")
            sg.addButton(rb)
            layout.addWidget(rb)
        sg.buttonClicked.connect(self._on_server)

        layout.addSpacing(8)

        layout.addSpacing(8)

        # ── 信号 ──────────────────────────────────────────
        self.btn_load.clicked.connect(self._on_load)
        self.btn_lang.clicked.connect(self._on_lang)
        self.btn_refresh.clicked.connect(self._on_refresh)
        bus.task_progress.connect(self._on_progress)
        bus.localization_ready.connect(self._enable_all)
        bus.data_loaded.connect(self._on_extract_done)
        bus.data_processed.connect(lambda _: self._enable_all())

        self._sync_server()

    # ── 信号处理 ──────────────────────────────────────────

    def _on_load(self):
        """提取 → 解析 → 写入数据库（合并流程）"""
        from services.extractor_service import run_extract

        self._disable_all()
        self._pending_process = True
        bus.task_progress.emit(0, "开始提取")
        bus.log_message.emit("📦 步骤 1/2: 正在提取游戏数据...")
        run_extract()

    def _on_extract_done(self, version: str) -> None:
        """提取完成 → 自动启动解析入库"""
        if not self._pending_process:
            return
        self._pending_process = False
        if not version:
            self._enable_all()
            return
        from services.processor_service import run_process
        bus.task_progress.emit(30, "解析数据")
        bus.log_message.emit("📦 步骤 2/2: 正在解析数据并写入数据库...")
        run_process()

    def _on_lang(self):
        from services.localization_service import run_localization
        self.btn_lang.setEnabled(False)
        bus.task_progress.emit(0, "开始加载文本")
        bus.log_message.emit("🌐 正在加载语言文件...")
        run_localization()

    def _on_refresh(self):
        """刷新界面：清空缓存 → 重新分析 → 刷新显示"""
        self._disable_all()
        bus.task_progress.emit(0, "刷新中")

        def _work():
            # 1. 清空 Presenter 缓存
            from presenters.registry import PresenterRegistry
            PresenterRegistry.clear_cache()

            # 2. 重新从 split JSON 分析（如果 split 目录存在）
            from utils.path_utils import get_split_dir
            split_dir = get_split_dir()
            if split_dir.exists() and any(split_dir.iterdir()):
                bus.log_message.emit("🔄 正在重新分析数据文件...")
                from services.database_service import get_db
                from services.analysis_service import AnalysisService
                db = get_db()
                if db.exists:
                    svc = AnalysisService()
                    svc.initialize()
                    if svc.is_ready:
                        svc.precompute_all(db)
                        bus.log_message.emit("✅ 数据分析完成")
            else:
                bus.log_message.emit("🔄 split 目录不存在，跳过重新分析")

            # 3. 通知界面刷新
            bus.folder_selected.emit("__REFRESH__")

        def _done(_result=None):
            self._enable_all()
            bus.task_progress.emit(100, "刷新完成")

        from utils.threading_utils import run_async
        run_async(_work, on_finished=_done, on_error=lambda e: (
            bus.log_message.emit(f"❌ 刷新出错: {e}"),
            self._enable_all()
        ))

    def _on_server(self, btn):
        app_ctx.set_wows_type(btn.text())

    def _on_progress(self, pct, msg):
        pct = max(0, min(100, pct))
        self.progress.setValue(pct)
        self.progress.setFormat(f"{msg}  {pct}%")
        self.progress.setVisible(True)
        if pct >= 100:
            # 完成后保留显示，由下次任务自动更新
            pass

    def _disable_all(self):
        self.btn_load.setEnabled(False)
        self.btn_lang.setEnabled(False)

    def _enable_all(self):
        self.btn_load.setEnabled(True)
        self.btn_lang.setEnabled(True)
        # 不隐藏进度条，由下个任务覆盖

    def _sync_server(self):
        t = app_ctx.ctx.wows_type
        if t == "Wargaming":
            self.rb_wg.setChecked(True)
        elif t == "Lesta":
            self.rb_lesta.setChecked(True)
