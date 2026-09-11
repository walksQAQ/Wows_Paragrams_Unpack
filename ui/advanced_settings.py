"""
AdvancedSettingsDialog —— 高级设置窗口。

从 config.json 读取/写入配置，包括：
  - 游戏目录路径
  - 解析后是否保留 split JSON 文件
  - 当前游戏版本（只读）
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QGroupBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from app.application import app as app_ctx
from app.signals import bus
from utils.theme import theme


class AdvancedSettingsDialog(QDialog):
    """高级设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级设置")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 游戏目录（按服务器分别保存） ───────────────
        grp_path = QGroupBox("游戏目录")
        glay = QVBoxLayout(grp_path)

        row_lesta, self._path_edit_lesta = self._make_path_row("Lesta 服：", "Lesta")
        glay.addLayout(row_lesta)

        row_wg, self._path_edit_wargaming = self._make_path_row("Wargaming 服：", "Wargaming")
        glay.addLayout(row_wg)

        lbl_hint = QLabel("两个服务器可分别指定各自的游戏安装目录；"
                          "切换服务器后会自动读取对应目录的数据")
        lbl_hint.setStyleSheet(theme.qss("color: @text_hint@; font-size: 11px;"))
        glay.addWidget(lbl_hint)
        layout.addWidget(grp_path)

        # ── 数据处理 ──────────────────────────────────
        grp_data = QGroupBox("数据处理")
        dlay = QVBoxLayout(grp_data)
        self._keep_split_cb = QCheckBox("解析数据后保留 split JSON 文件")
        self._keep_split_cb.setStyleSheet("font-size: 13px; spacing: 6px;")
        dlay.addWidget(self._keep_split_cb)
        dlay.addWidget(QLabel("勾选：解析完成后保留 data/split/ 目录下的 JSON 文件\n"
                              "取消勾选：解析完成后自动删除中间 JSON 文件以节省空间",
                              styleSheet=theme.qss("color: @text_hint@; font-size: 11px;")))
        layout.addWidget(grp_data)

        # ── 外观（主题模式） ──────────────────────────
        grp_theme = QGroupBox("外观")
        tlay = QVBoxLayout(grp_theme)
        trow = QHBoxLayout()
        trow.setSpacing(8)
        trow.addWidget(QLabel("主题模式："))
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("跟随系统", "auto")
        self._theme_combo.addItem("浅色", "light")
        self._theme_combo.addItem("深色", "dark")
        self._theme_combo.setMinimumWidth(140)
        trow.addWidget(self._theme_combo)
        trow.addStretch()
        tlay.addLayout(trow)
        tlay.addWidget(QLabel("选择「跟随系统」时，应用会随 Windows 深浅色主题自动切换。",
                              styleSheet=theme.qss("color: @text_hint@; font-size: 11px;")))
        layout.addWidget(grp_theme)

        # ── 游戏信息（只读） ──────────────────────────
        grp_info = QGroupBox("游戏信息")
        ilay = QFormLayout(grp_info)
        self._version_label = QLabel("未知")
        self._version_label.setStyleSheet(theme.qss("color: @text_muted@;"))
        self._data_state_label = QLabel("否")
        self._data_state_label.setStyleSheet(theme.qss("color: @text_muted@;"))
        ilay.addRow("当前游戏版本：", self._version_label)
        ilay.addRow("数据已加载：", self._data_state_label)
        layout.addWidget(grp_info)

        # ── 日志与诊断 ──────────────────────────────
        grp_log = QGroupBox("日志与诊断")
        llay = QVBoxLayout(grp_log)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        from utils.path_utils import get_app_dir
        self._log_dir_label = QLabel(str(get_app_dir() / "log"))
        self._log_dir_label.setStyleSheet(theme.qss("color: @text_muted@; font-size: 12px;"))
        self._log_dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_open_log = QPushButton("打开日志文件夹")
        btn_open_log.clicked.connect(self._on_open_log_dir)
        lrow.addWidget(self._log_dir_label, stretch=1)
        lrow.addWidget(btn_open_log)
        llay.addLayout(lrow)
        llay.addWidget(QLabel("程序运行日志按启动时间存为 log-*.log（保留最近 30 个），反馈 Bug 时可附上。",
                              styleSheet=theme.qss("color: @text_hint@; font-size: 11px;")))
        layout.addWidget(grp_log)

        # ── 版本检测 ──────────────────────────────────
        grp_update = QGroupBox("版本检测")
        ulay = QVBoxLayout(grp_update)
        self._auto_check_cb = QCheckBox("启动时自动检测 GitHub 新版本")
        self._auto_check_cb.setStyleSheet("font-size: 13px; spacing: 6px;")
        ulay.addWidget(self._auto_check_cb)
        self._include_pre_cb = QCheckBox("把预发布版本（pre-release）也视为可更新版本")
        self._include_pre_cb.setStyleSheet("font-size: 13px; spacing: 6px;")
        ulay.addWidget(self._include_pre_cb)
        ulay.addWidget(QLabel("自动检测每 24 小时至多请求一次 GitHub API；"
                              "「检查更新」按钮可随时手动强制刷新。",
                              styleSheet=theme.qss("color: @text_hint@; font-size: 11px;")))
        layout.addWidget(grp_update)

        # ── 按钮 ──────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── 加载/保存 ───────────────────────────────────────

    def _make_path_row(self, label: str, server: str) -> tuple:
        """创建一行路径编辑（标签 + 只读输入框 + 浏览按钮）。

        返回 (QHBoxLayout, QLineEdit)，调用方需保存 edit 引用以便读取/回填。
        """
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        edit = QLineEdit()
        edit.setPlaceholderText("请选择游戏安装目录...")
        edit.setReadOnly(True)
        edit.setStyleSheet(theme.qss("padding: 4px 8px; color: @text@; background-color: @input_bg@;"))
        btn = QPushButton("浏览...")
        btn.clicked.connect(lambda _=False, s=server: self._on_browse(s))
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        return row, edit

    def _load_settings(self) -> None:
        """从 app_ctx 加载当前配置到界面控件"""
        ctx = app_ctx.ctx
        self._path_edit_lesta.setText(ctx.config.game_path_lesta)
        self._path_edit_wargaming.setText(ctx.config.game_path_wargaming)
        self._keep_split_cb.setChecked(app_ctx.config.keep_split_json)
        # 主题模式
        _mode = app_ctx.config.theme_mode or "auto"
        _idx = self._theme_combo.findData(_mode)
        self._theme_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        # 版本检测
        self._auto_check_cb.setChecked(app_ctx.config.auto_check_update)
        self._include_pre_cb.setChecked(app_ctx.config.include_prerelease)
        self._version_label.setText(ctx.game_version or "未知")
        self._data_state_label.setText("是" if ctx.game_data_state else "否")

    def _on_browse(self, server: str) -> None:
        """浏览选择指定服务器的游戏目录"""
        from PySide6.QtWidgets import QFileDialog
        if server == "Wargaming":
            current = self._path_edit_wargaming.text()
        else:
            current = self._path_edit_lesta.text()
        d = QFileDialog.getExistingDirectory(
            self, "选择游戏目录", current or app_ctx.ctx.game_path)
        if d:
            if server == "Wargaming":
                self._path_edit_wargaming.setText(d)
            else:
                self._path_edit_lesta.setText(d)

    def _on_open_log_dir(self) -> None:
        """在系统文件管理器中打开日志文件夹（不存在则先创建）。"""
        import os
        from utils.path_utils import get_app_dir
        log_dir = get_app_dir() / "log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            bus.log_message.emit(f"⚠️ 无法打开日志文件夹: {exc}")

    def _on_ok(self) -> None:
        """点击确定：保存所有设置"""
        # 游戏目录（按服务器分别保存）
        lesta = self._path_edit_lesta.text().strip()
        if lesta and lesta != app_ctx.ctx.config.game_path_lesta:
            app_ctx.set_game_path_for_server("Lesta", lesta)
        wg = self._path_edit_wargaming.text().strip()
        if wg and wg != app_ctx.ctx.config.game_path_wargaming:
            app_ctx.set_game_path_for_server("Wargaming", wg)
        # 保留 split JSON
        app_ctx.config.keep_split_json = self._keep_split_cb.isChecked()
        # 主题模式（变更时立即刷新全局样式并广播信号）
        _new_mode = self._theme_combo.currentData() or "auto"
        if _new_mode != (app_ctx.config.theme_mode or "auto"):
            app_ctx.set_theme_mode(_new_mode)
        # 版本检测
        app_ctx.config.auto_check_update = self._auto_check_cb.isChecked()
        app_ctx.config.include_prerelease = self._include_pre_cb.isChecked()
        self.accept()
