"""
ShipCardWidget —— 卡片式舰船数据展示组件。

仿照 iwarship.net 的卡片+表格设计：
  ┌─────────────────────────────┐
  │  存活性                     │  ← QGroupBox 标题
  ├─────────────────────────────┤
  │  血量                15,900 │  ← QTableWidget 键值行
  │  鱼雷防护               1%  │
  │  吨位              2,629吨  │
  │  DOT数量      0 1 2 3 4 5 6│  ← 按钮组行
  └─────────────────────────────┘

支持响应式网格排列。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QHBoxLayout, QLabel, QButtonGroup,
    QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from utils.theme import theme


# ── 样式常量（动态求值，主题切换后生效） ─────────────────

def card_style() -> str:
    return theme.qss("""
        ShipCardWidget QGroupBox {
            background: @panel_bg@;
            border: 1px solid @border@;
            border-radius: 8px;
            margin-top: 8px;
            padding: 8px 0px 2px 0px;
            font-size: 12px;
            font-weight: bold;
            color: @text@;
        }
        ShipCardWidget QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 4px;
            color: @text@;
        }
    """)


CARD_STYLE = card_style()

TABLE_STYLE = """
    QTableWidget {
        border: none;
        background: transparent;
        font-size: 11px;
        gridline-color: transparent;
    }
    QTableWidget::item {
        padding: 2px 12px;
        border-bottom: 1px solid rgba(0,0,0,0.06);
        min-height: 18px;
    }
    QTableWidget::item:selected {
        background: transparent;
        color: inherit;
    }
"""

# 左列（标签）/右列（数值）字体颜色 —— 跟随主题（函数动态求值）
def label_color() -> str:
    return theme["text_muted"]


def value_color() -> str:
    return theme["text"]


# 兼容旧引用（导入时求值，供不重建的场景回退）
LABEL_COLOR = label_color()
VALUE_COLOR = value_color()

# ── 图标映射 ──────────────────────────────────────────────

SECTION_ICONS: dict[str, str] = {
    "基础属性": "📋",
    "消耗品数据": "💊",
    "战斗指令": "⚡",
    "船体": "🚢",
    "主炮": "🔫",
    "副炮": "🔧",
    "次级主炮": "🔫",
    "鱼雷": "💣",
    "防空": "🎯",
    "深水炸弹": "💥",
    "舰载机": "✈️",
    "支援": "💫",
}


# ══════════════════════════════════════════════════════════
#  卡片组件
# ══════════════════════════════════════════════════════════

class ShipCardWidget(QGroupBox):
    """单张数据卡片，包含标题和键值表格"""

    firing_arc_clicked = Signal(dict)

    def __init__(self, section: dict, parent=None, firing_arc: dict | None = None):
        """
        Args:
            section: 数据分区，格式：
                {"label": "存活性", "icon": "", "items": [
                    {"name": "血量", "value": "15900", "unit": "",
                     "row_type": "kv", "details": [...]},
                    ...
                ]}
            firing_arc: 射界入口信息（{"ship_id", "slot_type", "summary"}），
                        非空时在卡片底部追加可点击的射界按钮行
        """
        super().__init__(parent)
        self.setProperty("class", "ShipCardWidget")
        self._adjusting = False

        # 标题（含图标）
        label = section.get("label", "")
        icon = section.get("icon", "") or SECTION_ICONS.get(label, "")
        title = f"  {icon} {label}" if icon else f"  {label}"
        self.setTitle(title)
        self.setStyleSheet(card_style())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget()
        self._table.setStyleSheet(TABLE_STYLE)
        self._table.setColumnCount(2)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 表头隐藏
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 列宽：名称按内容，数值填满剩余
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setStretchLastSection(True)
        # 行高自适应文字换行
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # 启用文字换行
        self._table.setWordWrap(True)
        # 单元格文本不省略号截断（setTextElideMode 属于视图，而非 QTableWidgetItem）
        self._table.setTextElideMode(Qt.TextElideMode.ElideNone)

        self._populate_items(section.get("items", []))

        # 射界入口：卡片底部追加可点击按钮（不显示炮塔数量）
        if firing_arc and firing_arc.get("mode") == "front_back":
            self._add_firing_arc_row(firing_arc)

        # 左列宽度按内容，右列填满剩余；通过 ResizeToContents 保持紧凑
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        # 避免左列太宽，设最大宽度为表格预计宽度的 30%
        self._table.horizontalHeader().setMaximumSectionSize(300)

        layout.addWidget(self._table)

        # 延迟自适应高度，等布局完成后再计算
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._adjust_height)

    def _add_firing_arc_row(self, fa: dict) -> None:
        """在卡片底部添加射界行：左列标签 + 右列可点击的值按钮（齐射角）"""
        row = self._table.rowCount()
        self._table.insertRow(row)
        wep_name = "鱼雷发射器" if fa.get("slot_type") == "torpedoes" else "炮塔"
        # 左列：标签
        name_item = QTableWidgetItem(f"{wep_name} 射界")
        name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)
        # 右列：值按钮（可点击弹出射界弹窗）
        # 齐射角：前向/后向（主炮为全炮塔，鱼雷/副炮分两侧时取对应一侧）
        value_text = f"{fa.get('front', 0)}°（前）/{fa.get('back', 0)}°（后）"
        btn = QPushButton()
        btn.setText(value_text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("点击查看该武器系统的射界图（总览 + 单炮塔详情）")
        btn.setStyleSheet(theme.qss("""
            QPushButton {
                background: @panel_alt@; color: @text@;
                border: 1px solid @border@; border-radius: 4px;
                padding: 4px 8px; font-size: 12px; text-align: center;
            }
            QPushButton:hover { background: @hover_bg@; border-color: @selected_bg@; }
        """))
        btn.clicked.connect(lambda _=False: self.firing_arc_clicked.emit(fa))
        self._table.setCellWidget(row, 1, btn)

    def set_firing_arc(self, fa: dict) -> None:
        """动态为已渲染的卡片追加射界按钮行（供 weapon widget 在最后一座炮卡片上调用）"""
        if fa and fa.get("mode") == "front_back":
            self._add_firing_arc_row(fa)

    def resizeEvent(self, event):
        """窗口缩放时重新调整高度"""
        if not self._adjusting:
            self._adjusting = True
            super().resizeEvent(event)
            self._adjust_height()
            self._adjusting = False

    def _populate_items(self, items: list[dict]) -> None:
        """填充所有数据行"""
        for item in items:
            row_type = item.get("row_type", "kv")

            if row_type == "header":
                self._add_header_row(item)
            elif row_type == "sub_header":
                self._add_sub_header_row(item)
            elif row_type == "separator":
                self._add_separator_row()
            elif row_type == "button_group":
                self._add_button_group_row(item)
            else:  # "kv" 默认
                self._add_kv_row(item)

    def _add_kv_row(self, item: dict) -> None:
        """添加一条键值对行"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        name = item.get("name", "")
        value = item.get("value", "")
        unit = item.get("unit", "")
        details = item.get("details", [])

        # 左列：名称
        name_item = QTableWidgetItem(name)
        name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)

        # 右列：数值 + 单位
        display_value = f"{value} {unit}" if unit and value else (value or unit or "")
        value_item = QTableWidgetItem(display_value)
        # 显式颜色优先
        color = item.get("color", "")
        if color:
            value_item.setForeground(QColor(color))
        else:
            stripped = display_value.strip()
            # 仅对含数字的正负值自动着色（纯文本 +/− 不处理）
            has_sign = stripped.startswith("+") or stripped.startswith("-")
            has_digit = any(c.isdigit() for c in stripped)
            if has_sign and has_digit:
                if stripped.startswith("+"):
                    value_item.setForeground(QColor("#1b8a1b"))
                else:
                    value_item.setForeground(QColor("#d32f2f"))
            else:
                value_item.setForeground(QColor(value_color()))
        value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._table.setItem(row, 1, value_item)

        # 如果有二级详情，设置 tooltip
        if details:
            tip_lines = []
            for d in details:
                dv = d.get("value", "")
                du = d.get("unit", "")
                dn = d.get("name", "")
                dd = f"{dv} {du}" if du and dv else (dv or du or "")
                tip_lines.append(f"{dn}: {dd}" if dn else dd)
            if tip_lines:
                name_item.setToolTip("\n".join(tip_lines))
                value_item.setToolTip("\n".join(tip_lines))

    def _add_header_row(self, item: dict) -> None:
        """添加分段标题行"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        name = item.get("name", "")
        cell = QTableWidgetItem(name)
        cell.setForeground(QColor(theme["text_muted"]))
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(10)
        cell.setFont(bold_font)
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, cell)

        # 占位
        empty = QTableWidgetItem("")
        empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 1, empty)

    def _add_sub_header_row(self, item: dict) -> None:
        """添加次标题行，仅略微加粗，介于 header 与 kv 之间"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        name = item.get("name", "")
        cell = QTableWidgetItem(name)
        cell.setForeground(QColor(theme["text_muted"]))
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(10)
        cell.setFont(bold_font)
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, cell)

        empty = QTableWidgetItem("")
        empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 1, empty)

    def _add_separator_row(self) -> None:
        """添加分隔线行"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        sep = QTableWidgetItem("─" * 30)
        sep.setForeground(QColor(theme["border_soft"]))
        sep.setFlags(sep.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, sep)

        empty = QTableWidgetItem("")
        empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 1, empty)

    def _add_button_group_row(self, item: dict) -> None:
        """添加按钮组行（如 DOT 数量选择）"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        name = item.get("name", "")
        name_item = QTableWidgetItem(name)
        name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)

        # 右列放按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(3)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        raw = item.get("raw_value", {})
        if isinstance(raw, dict):
            min_v = raw.get("min", 0)
            max_v = raw.get("max", 6)
            current = raw.get("current", min_v)
            group = QButtonGroup(btn_widget)
            for v in range(min_v, max_v + 1):
                btn = QPushButton(str(v))
                btn.setFixedSize(22, 20)
                btn.setCheckable(True)
                btn.setStyleSheet(theme.qss("""
                    QPushButton {
                        background: @panel_alt@; border: 1px solid @border@;
                        border-radius: 3px; font-size: 9px; color: @text@;
                    }
                    QPushButton:hover { background: @hover_bg@; border-color: #aaa; }
                    QPushButton:checked {
                        background: #0078d4; color: #fff; border-color: #0078d4;
                    }
                """))
                group.addButton(btn, v)
                btn_layout.addWidget(btn)
                if v == current:
                    btn.setChecked(True)

        btn_layout.addStretch()
        self._table.setCellWidget(row, 1, btn_widget)
        self._table.setRowHeight(row, 24)

    def _adjust_height(self) -> None:
        """根据行数自动调整卡片高度"""
        if self._adjusting:
            return
        # 检查 self._table 是否仍有效（可能在重建时已被销毁）
        try:
            _ = self._table.rowCount()
        except (RuntimeError, AttributeError):
            self._adjusting = False
            return
        self._adjusting = True
        self._table.resizeRowsToContents()
        rows = self._table.rowCount()
        height = 4
        for r in range(rows):
            height += self._table.rowHeight(r) + 2
        self._table.setFixedHeight(height)
        card_height = height + 22
        self.setFixedHeight(card_height)
        self._adjusting = False


# ══════════════════════════════════════════════════════════
#  响应式网格容器
# ══════════════════════════════════════════════════════════

class ShipDetailGrid(QScrollArea):
    """响应式卡片网格容器

    将多个 ShipCardWidget 排列成网格，根据容器宽度自动调整列数。
    """

    def __init__(self, sections: list[dict], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(theme.qss("""
            ShipDetailGrid {
                border: none;
                background-color: @window_bg@;
            }
        """))

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setSpacing(6)
        self.setWidget(self._container)

        self._sections = sections
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        """清空并重建网格布局"""
        # 清除旧卡片
        while self._grid.count() > 0:
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not self._sections:
            return

        # 估算列数（根据卡片宽度 280px）
        container_width = self.viewport().width() or 800
        cols = max(1, min(len(self._sections), container_width // 300))

        for i, sec in enumerate(self._sections):
            card = ShipCardWidget(sec)
            row = i // cols
            col = i % cols
            self._grid.addWidget(card, row, col)

        # 填充空位
        if self._sections:
            last_row = (len(self._sections) - 1) // cols
            for c in range(cols):
                if self._grid.itemAtPosition(last_row, c) is None:
                    self._grid.addWidget(QWidget(), last_row, c)

    def resizeEvent(self, event) -> None:
        """窗口大小变化时重建网格"""
        super().resizeEvent(event)
        self._rebuild_grid()
