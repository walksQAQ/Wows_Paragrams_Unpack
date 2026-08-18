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
from utils.theme import theme


class TopToolbar(QWidget):
    """顶部工具栏"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopToolbar")
        # 工具栏整体样式：背景/按钮/进度条/服务器文字全部跟随主题（浅色主题=浅色工具栏）
        theme.bind(self, """
            #TopToolbar {
                background-color: @toolbar_bg@;
                border-bottom: 1px solid @border@;
            }
            #TopToolbar QPushButton {
                background-color: @toolbar_btn_bg@;
                color: @toolbar_btn_text@;
                border: 1px solid @toolbar_btn_border@;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
            }
            #TopToolbar QPushButton:hover {
                background-color: @toolbar_btn_hover@;
                border-color: #0078d4;
            }
            #TopToolbar QPushButton:disabled {
                background-color: @toolbar_btn_disabled@;
                color: @toolbar_text_muted@;
                border-color: @toolbar_btn_border@;
            }
            #TopToolbar QLabel {
                color: @toolbar_text@;
                font-size: 12px;
            }
            /* 服务器单选按钮：对齐 v3.2.2-test1 —— 不自定义 ::indicator，
               圆点使用 Qt 原生渲染（灰环 + 选中蓝色内点），只控制文字颜色/间距 */
            #TopToolbar QRadioButton {
                color: @toolbar_text@;
                font-size: 12px;
                spacing: 4px;
            }
            #TopToolbar QRadioButton:disabled {
                color: @toolbar_text_muted@;
            }
            #TopToolbar QProgressBar {
                border: 1px solid #0078d4; border-radius: 4px;
                background: @toolbar_bg@; color: @toolbar_btn_text@;
                font-size: 11px; font-weight: bold;
                text-align: center;
                padding: 0;
            }
            #TopToolbar QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0078d4, stop:1 #00a0ff);
                border-radius: 3px;
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
        self.btn_ballistics = QPushButton("📊  穿深计算器")
        self.btn_3d = QPushButton("⛵  3D 查看")
        self.btn_3d.setToolTip("打开舰船 3D 模型 / 装甲查看器")
        # 复制按钮：无下拉，点击 = 复制右下方信息面板的完整文本内容
        self.btn_copy = QPushButton("📋  复制当前信息")
        self.btn_copy.setToolTip("将右下方信息显示区的完整内容以文本复制到剪贴板")

        for b in (self.btn_load, self.btn_lang, self.btn_refresh, self.btn_ballistics, self.btn_3d, self.btn_copy):
            layout.addWidget(b)

        layout.addStretch()

        # ── 进度条（服务器选择左侧） ─
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedWidth(200)
        self.progress.setFixedHeight(22)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        # ── 服务器选择 ─
        lbl_server = QLabel("服务器选项：")
        layout.addWidget(lbl_server)

        sg = QButtonGroup(self)
        self.rb_lesta = QRadioButton("Lesta")
        self.rb_wg = QRadioButton("Wargaming")
        # Wargaming 暂时禁用
        self.rb_wg.setEnabled(False)
        sg.addButton(self.rb_lesta)
        sg.addButton(self.rb_wg)
        layout.addWidget(self.rb_lesta)
        layout.addWidget(self.rb_wg)
        sg.buttonClicked.connect(self._on_server)

        layout.addSpacing(8)

        layout.addSpacing(8)

        # ── 信号 ──────────────────────────────────────────
        self.btn_load.clicked.connect(self._on_load)
        self.btn_lang.clicked.connect(self._on_lang)
        self.btn_refresh.clicked.connect(self._on_refresh)
        self.btn_ballistics.clicked.connect(self._on_ballistics)
        self.btn_3d.clicked.connect(self._on_3d_viewer)
        self.btn_copy.clicked.connect(lambda: bus.copy_ship_info.emit())
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
        bus.log_message.emit("📦 步骤 1/3: 提取游戏数据...")
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
        bus.task_progress.emit(30, "步骤 2/3: 解析拆分数据")
        bus.log_message.emit("📦 步骤 2/3: 正在解析拆分数据...")
        run_process()

    def _on_lang(self):
        from services.localization_service import run_localization
        self.btn_lang.setEnabled(False)
        bus.task_progress.emit(0, "开始加载文本")
        bus.log_message.emit("🌐 正在加载语言文件...")
        run_localization()

    def _on_refresh(self):
        """刷新界面：清空缓存 → 刷新显示（不触发重新分析）"""
        self._disable_all()
        bus.task_progress.emit(0, "刷新中")

        def _work():
            # 1. 清空 Presenter 缓存
            from presenters.registry import PresenterRegistry
            PresenterRegistry.clear_cache()

            # 2. 通知界面刷新
            bus.folder_selected.emit("__REFRESH__")

        def _done(_result=None):
            self._enable_all()
            bus.task_progress.emit(100, "刷新完成")

        from utils.threading_utils import run_async
        run_async(_work, on_finished=_done, on_error=lambda e: (
            bus.log_message.emit(f"❌ 刷新出错: {e}"),
            self._enable_all()
        ))

    def _on_ballistics(self):
        """打开穿深/散布计算器（独立顶层窗口，懒创建单实例，复刻 assets 浏览器）。"""
        try:
            from ui.penetration_calculator import PenetrationCalculatorDialog
            if not hasattr(self, "_ballistics_dialog") or self._ballistics_dialog is None:
                self._ballistics_dialog = PenetrationCalculatorDialog()
                if not getattr(self._ballistics_dialog, "_restored_geometry", False):
                    self._ballistics_dialog.center_on_screen(self.window())
            self._ballistics_dialog.show()
            self._ballistics_dialog.raise_()
            self._ballistics_dialog.activateWindow()
        except Exception as exc:
            bus.log_message.emit(f"❌ 打开穿深计算器失败: {exc}")

    def _on_3d_viewer(self):
        """打开舰船 3D 模型查看器（独立顶层窗口，懒创建单实例）。

        不传 parent：传主窗口为父会让 QOpenGLWidget 作为主窗口子窗口创建，
        Windows 上 GL 上下文创建触发主窗口重绘闪烁。关闭联动由
        MainWindow.closeEvent 显式关闭 _geometry_viewer 保证。
        """
        try:
            from ui.geometry_viewer import GeometryViewerDialog
            if not hasattr(self, "_geometry_viewer") or self._geometry_viewer is None:
                self._geometry_viewer = GeometryViewerDialog()
                if not getattr(self._geometry_viewer, "_restored_geometry", False):
                    self._geometry_viewer.center_on_screen(self.window())
            self._geometry_viewer.show()
            self._geometry_viewer.raise_()
            self._geometry_viewer.activateWindow()
        except Exception as exc:
            bus.log_message.emit(f"❌ 打开 3D 查看器失败: {exc}")

    def _on_server(self, btn):
        server = btn.text()
        if server == app_ctx.ctx.wows_type:
            return  # 未变更
        app_ctx.set_wows_type(server)
        # 切换服务器时重置数据库单例，刷新界面
        from services.database_service import reset_db, get_db
        reset_db()
        db = get_db(server)
        if db.exists and db.get_stats().get("total_entities", 0) > 0:
            bus.log_message.emit(f"🔄 已切换到 {server} 数据库")
            bus.folder_selected.emit("__REFRESH__")
            bus.can_process_data.emit(True)
        else:
            bus.log_message.emit(f"ℹ️ {server} 数据库为空，请加载数据")
            bus.folder_selected.emit("__REFRESH__")

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
        self.btn_ballistics.setEnabled(False)
        self.btn_3d.setEnabled(False)

    def _enable_all(self):
        self.btn_load.setEnabled(True)
        self.btn_lang.setEnabled(True)
        self.btn_ballistics.setEnabled(True)
        self.btn_3d.setEnabled(True)
        # 不隐藏进度条，由下个任务覆盖

    def _sync_server(self):
        t = app_ctx.ctx.wows_type
        if t == "Wargaming":
            self.rb_wg.setChecked(True)
        elif t == "Lesta":
            self.rb_lesta.setChecked(True)
        else:
            # "未选择" 时取消所有选中
            self.rb_lesta.setChecked(False)
            self.rb_wg.setChecked(False)
