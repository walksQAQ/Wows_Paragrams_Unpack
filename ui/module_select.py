"""
ModuleSelect —— 模块选择区（90px 窄栏）。

按钮样式：图标在上，文字在下（双行）。
匹配 CategoryBar 的图标+文字显示方式。
支持动态模块列表：
- 舰船数据按 section 分组显示（基础属性、船体、消耗品等）
- 非舰船数据使用默认的 详情/数据/原始 三页
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, Signal

import re

# 舰船专用模块图标（key=section标签, value=(图标, 简短显示名)）
SHIP_MODULE_MAP: dict[str, tuple[str, str]] = {
    "基础属性":    ("📋", "基础"),
    "消耗品数据":  ("💊", "消耗品"),
    "战斗指令":   ("⚡", "战斗指令"),
    # 各类型模块
    "船体":       ("🚢", "船体"),
    "主炮":       ("🔫", "主炮"),
    "副炮":       ("🔧", "副炮"),
    "次级主炮":   ("🔫", "次级主炮"),
    "鱼雷":       ("💣", "鱼雷"),
    "防空":       ("🎯", "防空"),
    "深水炸弹":   ("💥", "深弹"),
    "舰载机":     ("✈️", "飞机"),
    "支援":       ("💫", "支援"),
    # 舰长天赋
    "成就触发":   ("🏆", "成就"),
    "成就触发Ⅱ":  ("🏆", "成就Ⅱ"),
    "受击触发":   ("💥", "受击"),
    "友军阵亡":   ("💔", "友军"),
    "击沉触发":   ("⚓", "击沉"),
    "血量触发":   ("❤️", "血量"),
    "指令触发":   ("⚡", "指令"),
    "勋带触发":   ("🎖️", "勋带"),
    "勋带触发Ⅱ":  ("🎖️", "勋带Ⅱ"),
    "勋带触发Ⅲ":  ("🎖️", "勋带Ⅲ"),
    "勋带触发Ⅳ":  ("🎖️", "勋带Ⅳ"),
}
SHIP_MODULE_FALLBACK = ("📄", "模块")

# 字母模块正则：如 "A 模块" → 提取 "A"
_RE_LETTER_MOD = re.compile(r'^([A-Z])\s*模块$')


class ModuleSelect(QWidget):
    """模块选择区（90px），图标+文字双行按钮"""

    module_selected = Signal(str)
    modules_changed = Signal(list)

    BTN_STYLE = """
        QPushButton {
            background-color: transparent;
            color: #000000;
            border: none;
            border-radius: 8px;
            padding: 8px 2px;
        }
        QPushButton:hover {
            background-color: #3a3a3a;
            color: #cccccc;
        }
        QPushButton:checked {
            background-color: #0078d4;
            color: #ffffff;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModuleSelect")
        self.setFixedWidth(90)
        self.setStyleSheet("""
            #ModuleSelect {
                background-color: #2d2d2d;
                border-left: 1px solid #3c3c3c;
                border-right: 1px solid #3c3c3c;
            }
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 16, 6, 16)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._btns: list[QPushButton] = []
        self._module_ids: list[str] = []
        self._active: str = ""

        # 占位提示（无模块时显示）
        self._placeholder = QLabel("选择\n文件\n后\n显示")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #555; font-size: 11px; padding: 8px;")
        self._layout.addWidget(self._placeholder)

        # 启动时不显示任何模块按钮，等选中文件后由 modules_available 信号驱动
        # self.set_modules(None)  ← 不再默认初始化

        self._layout.addStretch()

    def _make_btn(self, icon: str, label: str, mod_id: str) -> QPushButton:
        """创建图标+文字双行按钮"""
        btn = QPushButton(f"{icon}\n{label}")
        btn.setToolTip(label)
        btn.setCheckable(True)
        btn.setStyleSheet(self.BTN_STYLE)
        btn.clicked.connect(lambda checked, m=mod_id: self._on_module(m))
        return btn

    def set_modules(self, section_labels: list[str] | None) -> None:
        """设置模块列表。None=清空；list=使用指定 section 标签"""
        # 隐藏占位文本
        self._placeholder.setVisible(False)

        # 清除旧按钮
        for btn in self._btns:
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._btns.clear()
        self._module_ids = []

        if section_labels is None:
            # 无模块数据，不添加任何按钮
            self._module_ids = []
        else:
            # 舰船/舰长动态模块
            self._module_ids = list(section_labels)
            for label in section_labels:
                # 检查是否是字母模块
                m = _RE_LETTER_MOD.match(label)
                if m:
                    icon, short = ("🔧", m.group(1))
                else:
                    icon, short = SHIP_MODULE_MAP.get(label, SHIP_MODULE_FALLBACK)
                btn = self._make_btn(icon, short, label)
                self._layout.insertWidget(self._layout.count() - 1, btn)
                self._btns.append(btn)

        # 默认选中第一个
        if self._module_ids:
            self._active = self._module_ids[0]
            if self._btns:
                self._btns[0].setChecked(True)

        self.modules_changed.emit(self._module_ids)

    def clear_selection(self) -> None:
        """取消所有模块按钮的选中状态"""
        self._active = None
        for btn in self._btns:
            btn.setChecked(False)

    def _on_module(self, mod_id: str) -> None:
        """模块按钮点击"""
        for btn, mid in zip(self._btns, self._module_ids):
            btn.setChecked(mid == mod_id)
        self._active = mod_id
        self.module_selected.emit(mod_id)
