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
        # 应用级后台任务句柄（提取/解析/本地化/刷新；主窗口关闭时取消）
        self._app_tasks: list = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # ── 操作按钮（中文）─
        self.btn_load = QPushButton("📦  加载数据")
        self.btn_lang = QPushButton("🌐  加载文本")
        self.btn_refresh = QPushButton("🔄  刷新界面")
        self.btn_ballistics = QPushButton("📊  穿深计算器")
        # 复制按钮：无下拉，点击 = 复制右下方信息面板的完整文本内容
        self.btn_copy = QPushButton("📋  复制当前信息")
        self.btn_copy.setToolTip("将右下方信息显示区的完整内容以文本复制到剪贴板")

        for b in (self.btn_load, self.btn_lang, self.btn_refresh, self.btn_ballistics, self.btn_copy):
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
        # WG 服按钮已启用（2026-08-21，wg 数据兼容开发中；切换后需保证 game_path 指向 WG 客户端）
        sg.addButton(self.rb_lesta)
        sg.addButton(self.rb_wg)
        layout.addWidget(self.rb_lesta)
        layout.addWidget(self.rb_wg)
        sg.buttonClicked.connect(self._on_server)

        layout.addSpacing(8)

        # ── 版本检测（状态标签 + 检查按钮） ─
        self.version_label = QLabel("")
        self.version_label.setToolTip("本地版本与 GitHub 最新版本同步状态")
        layout.addWidget(self.version_label)
        self.btn_check_update = QPushButton("🔍  检查更新")
        self.btn_check_update.setToolTip("检测 GitHub 仓库是否有新版本（含 pre-release 识别）")
        layout.addWidget(self.btn_check_update)
        self._update_task_running = False

        layout.addSpacing(8)

        # ── 信号 ──────────────────────────────────────────
        self.btn_load.clicked.connect(self._on_load)
        self.btn_lang.clicked.connect(self._on_lang)
        self.btn_refresh.clicked.connect(self._on_refresh)
        self.btn_ballistics.clicked.connect(self._on_ballistics)
        self.btn_copy.clicked.connect(lambda: bus.copy_ship_info.emit())
        self.btn_check_update.clicked.connect(lambda: self.check_update(force=True))
        bus.update_check_done.connect(self._on_update_check_done)
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
        self._track_app_task(run_extract())

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
        self._track_app_task(run_process())

    def _on_lang(self):
        from services.localization_service import run_localization
        self.btn_lang.setEnabled(False)
        bus.task_progress.emit(0, "开始加载文本")
        bus.log_message.emit("🌐 正在加载语言文件...")
        self._track_app_task(run_localization())

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
        self._track_app_task(run_async(_work, on_finished=_done, on_error=lambda e: (
            bus.log_message.emit(f"❌ 刷新出错: {e}"),
            self._enable_all()
        )))

    def _on_ballistics(self):
        """打开穿深/散布计算器（独立顶层窗口，懒创建单实例，复刻 assets 浏览器）。"""
        try:
            from ui.penetration_calculator import PenetrationCalculatorDialog
            from utils.window_utils import ensure_dialog_shown
            if not getattr(self, "_ballistics_dialog", None) or not getattr(self._ballistics_dialog, "_restored_geometry", False):
                ensure_dialog_shown(self, "_ballistics_dialog", PenetrationCalculatorDialog, self.window())
            else:
                self._ballistics_dialog.show()
                self._ballistics_dialog.raise_()
                self._ballistics_dialog.activateWindow()
        except Exception as exc:
            bus.log_message.emit(f"❌ 打开穿深计算器失败: {exc}")

    def _on_server(self, btn):
        server = btn.text()
        if server == app_ctx.ctx.wows_type:
            return  # 未变更
        app_ctx.set_wows_type(server)
        # 切换服务器提醒：需更换游戏路径（wows_type 已切换，game_path 需用户手动改）
        self._prompt_server_path(server)
        # 切换服务器时，先做一次只读 schema 版本检查（在 get_db/initialize 重建前），
        # 不匹配则弹出提示；再重置数据库单例刷新界面
        from services.database_service import check_schema_mismatches, reset_db, get_db
        try:
            mismatches = check_schema_mismatches(server)
            if mismatches:
                from utils.window_utils import prompt_schema_mismatch
                prompt_schema_mismatch(self.window(), server, mismatches)
        except Exception:  # noqa: BLE001
            pass
        reset_db()
        db = get_db(server)
        if db.exists and db.get_stats().get("total_entities", 0) > 0:
            bus.log_message.emit(f"🔄 已切换到 {server} 数据库")
            bus.folder_selected.emit("__REFRESH__")
            bus.can_process_data.emit(True)
        elif db.schema_rebuilt():
            bus.log_message.emit(f"⚠️ {server} 数据库结构已更新，需要重新加载数据")
            bus.folder_selected.emit("__REFRESH__")
        else:
            bus.log_message.emit(f"ℹ️ {server} 数据库为空，请加载数据")
            bus.folder_selected.emit("__REFRESH__")

    def _prompt_server_path(self, server: str) -> None:
        """切换服务器后提醒：需要更换游戏路径。

        服务器单选按钮切换后 game_path 不会自动变，用户需到「高级设置」手动指向
        对应客户端，再点「加载数据」；否则会用当前路径加载错误客户端的数据。
        """
        from PySide6.QtWidgets import QMessageBox
        cur = app_ctx.ctx.game_path
        if server == "Wargaming":
            hint = "Wargaming 客户端（如 D:\\World_of_Warships）"
        else:
            hint = "Lesta 客户端（如 D:\\World_of_Warships_RU\\Korabli_PT）"
        box = QMessageBox(self.window())
        box.setWindowTitle("切换服务器")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"已切换到 {server} 服务器")
        box.setInformativeText(
            "⚠️ 切换服务器后，请到「高级设置」把游戏路径指向对应客户端，再点「加载数据」。\n\n"
            f"当前游戏路径：{cur}\n目标：{hint}"
        )
        btn_ok = box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
        btn_go = box.addButton("打开高级设置", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is btn_go:
            w = self.window()
            if hasattr(w, "_on_advanced_settings"):
                w._on_advanced_settings()

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

    def _enable_all(self):
        self.btn_load.setEnabled(True)
        self.btn_lang.setEnabled(True)
        self.btn_ballistics.setEnabled(True)
        # 不隐藏进度条，由下个任务覆盖

    def _track_app_task(self, task):
        """记录应用级后台任务句柄（供主窗口关闭时取消）；顺带清理已结束的。"""
        self._app_tasks = [t for t in self._app_tasks
                           if t is not None and t.is_running()]
        if task is not None:
            self._app_tasks.append(task)

    def cancel_app_tasks(self):
        """取消所有应用级后台任务（主窗口关闭时调用；已取消任务不再回调）。"""
        for t in self._app_tasks:
            try:
                t.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._app_tasks = []

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

    # ── 版本检测 ──────────────────────────────────────────

    def check_update(self, force: bool = False):
        """后台检测 GitHub 最新版本（结果经 bus.update_check_done 回主线程）。

        force=True：手动触发，忽略缓存；False：自动检测，遵守 24h 缓存间隔。
        """
        if self._update_task_running:
            return
        self._update_task_running = True
        self.btn_check_update.setEnabled(False)
        self.version_label.setText("检查更新中...")

        include_pre = app_ctx.config.include_prerelease

        def _work():
            from services.update_service import check
            return check(force=force, include_prerelease=include_pre)

        def _done(result):
            self._update_task_running = False
            self.btn_check_update.setEnabled(True)
            bus.update_check_done.emit(result)

        def _err(e):
            self._update_task_running = False
            self.btn_check_update.setEnabled(True)
            self.version_label.setText("检查更新失败")
            bus.log_message.emit(f"⚠️ 版本检测出错: {e}")

        from utils.threading_utils import run_async
        self._track_app_task(run_async(_work, on_finished=_done, on_error=_err))

    def _on_update_check_done(self, result):
        """检测完成（主线程）：更新状态标签 + 有新版本时弹窗提示。"""
        if result is None:
            return
        if result.error:
            self.version_label.setText("检查更新失败")
            return
        cur = result.current or "?"
        if result.has_new_release:
            self.version_label.setText(f"发现新版本 {result.latest_release}")
            self._prompt_new_version(result)
        elif result.has_new_prerelease:
            self.version_label.setText(f"新预发布 {result.latest_prerelease}")
            self._prompt_new_version(result)
        else:
            self.version_label.setText(f"当前 v{cur}（最新）")

    def _prompt_new_version(self, result):
        """新版本提示弹窗：前往 GitHub / 忽略此版本 / 稍后。"""
        from PySide6.QtWidgets import QMessageBox
        new_tag = result.latest_release if result.has_new_release else result.latest_prerelease
        if not new_tag or new_tag in (result.ignored_versions or []):
            return
        url = result.release_url if result.has_new_release else result.prerelease_url
        kind = "正式版" if result.has_new_release else "预发布版"
        box = QMessageBox(self.window())
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"检测到新的{kind}：{new_tag}\n"
            f"当前版本：{result.current}\n\n"
            f"是否前往 GitHub 查看？")
        btn_go = box.addButton("前往 GitHub", QMessageBox.ButtonRole.AcceptRole)
        btn_ignore = box.addButton("忽略此版本", QMessageBox.ButtonRole.RejectRole)
        box.addButton("稍后", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() is btn_go and url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        elif box.clickedButton() is btn_ignore:
            from services.update_service import load_ignored_versions, save_ignored_versions
            ignored = list(result.ignored_versions or [])
            if new_tag not in ignored:
                ignored.append(new_tag)
                save_ignored_versions(ignored)
            bus.log_message.emit(f"ℹ️ 已忽略版本 {new_tag}")
            self.version_label.setText(f"当前 v{result.current}（最新）")
