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
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QGroupBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from app.application import app as app_ctx
from app.signals import bus


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

        # ── 游戏目录 ──────────────────────────────────
        grp_path = QGroupBox("游戏目录")
        glay = QVBoxLayout(grp_path)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("请选择游戏安装目录...")
        self._path_edit.setReadOnly(True)
        self._path_edit.setStyleSheet("padding: 4px 8px; color: #1a1a1a; background-color: #ffffff;")
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(self._path_edit, stretch=1)
        path_row.addWidget(btn_browse)
        glay.addLayout(path_row)

        lbl_hint = QLabel("提示：选择 World_of_Warships 或 Korabli 的安装根目录")
        lbl_hint.setStyleSheet("color: #888; font-size: 11px;")
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
                              styleSheet="color: #888; font-size: 11px;"))
        layout.addWidget(grp_data)

        # ── 游戏信息（只读） ──────────────────────────
        grp_info = QGroupBox("游戏信息")
        ilay = QFormLayout(grp_info)
        self._version_label = QLabel("未知")
        self._version_label.setStyleSheet("color: #555;")
        self._data_state_label = QLabel("否")
        self._data_state_label.setStyleSheet("color: #555;")
        ilay.addRow("当前游戏版本：", self._version_label)
        ilay.addRow("数据已加载：", self._data_state_label)
        layout.addWidget(grp_info)

        # ── 按钮 ──────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── 加载/保存 ───────────────────────────────────────

    def _load_settings(self) -> None:
        """从 app_ctx 加载当前配置到界面控件"""
        ctx = app_ctx.ctx
        self._path_edit.setText(ctx.game_path)
        self._keep_split_cb.setChecked(app_ctx.config.keep_split_json)
        self._version_label.setText(ctx.game_version or "未知")
        self._data_state_label.setText("是" if ctx.game_data_state else "否")

    def _on_browse(self) -> None:
        """浏览选择游戏目录"""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "选择游戏目录", self._path_edit.text() or app_ctx.ctx.game_path)
        if d:
            self._path_edit.setText(d)

    def _on_ok(self) -> None:
        """点击确定：保存所有设置"""
        # 游戏目录
        path = self._path_edit.text().strip()
        if path and path != app_ctx.ctx.game_path:
            app_ctx.set_game_path(path)
        # 保留 split JSON
        app_ctx.config.keep_split_json = self._keep_split_cb.isChecked()
        self.accept()
