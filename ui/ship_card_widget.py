"""
ShipCardWidget —— 卡片式舰船数据展示组件。

卡片 = 圆角卡面 + 卡内「水晶棱角」标题框（标题不再挂在卡片外）：

  ╭─────────────────────────────╮
  │ 📋 基础属性                  ╲│  ← 标题框：底边细线 + 45° 斜切接回顶边
  │──────────────────────────────│
  │ 血量                15,900   │  ← QTableWidget 键值行
  │ 鱼雷防护                1%   │
  │ 吨位               2,629吨   │
  │ DOT数量     0 1 2 3 4 5 6    │  ← 按钮组行
  ╰─────────────────────────────╯

支持响应式网格排列。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QHBoxLayout, QLabel, QButtonGroup,
    QSizePolicy, QScrollArea, QApplication, QToolTip, QFrame,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QFont, QColor, QCursor, QFontMetrics, QPainter, QPen, QPolygonF, QPainterPath,
)

from app.signals import bus
from utils.theme import theme


# ── 样式常量（动态求值，主题切换后生效） ─────────────────

#: 卡片圆角半径
CARD_RADIUS = 8
#: 卡片顶边框的 y（= QSS margin-top）：标题框横跨在这条线上
CARD_EDGE_Y = 14
#: 棱角标题框：左端起始 x / 顶边 y / 底边 y / 右下 45° 切角长度
CARD_PLATE_LEFT = 14
CARD_PLATE_TOP = 3
CARD_PLATE_BOTTOM = 25
CARD_PLATE_CHAMFER = 9
#: 标题文字左边距（QSS ::title 的 left）
CARD_TITLE_LEFT = 20


def card_style() -> str:
    # 卡面与边框全部由 CardFrame.paintEvent 自绘，这里只留排版内边距：
    #   · 标题框要「跨」在卡片顶边框上，并把那一段边框线遮掉——QSS 画不出缺口
    #   · 标题文字仍由 QSS 的 ::title 绘制（字体/度量交给 Qt），背景透明
    #   · margin-top 让出边框上方的标题框上半截，padding-top 让出下半截给内容
    return theme.qss(f"""
        QGroupBox {{
            background: transparent;
            border: none;
            margin-top: {CARD_EDGE_Y}px;
            padding: {(CARD_PLATE_BOTTOM - CARD_EDGE_Y) + 5}px 12px 6px 12px;
            font-size: 11px;
            font-weight: bold;
            color: @text@;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {CARD_TITLE_LEFT}px;
            padding: 6px 0px 0px 0px;
            background: transparent;
            color: @text@;
        }}
        /* 无标题卡片（作为父卡片的续行容器）：不画卡面、不占标题位 */
        QGroupBox[untitled="true"] {{
            background: transparent;
            border: none;
            margin-top: 0px;
            padding: 6px 0px 4px 0px;
        }}
    """)


CARD_STYLE = card_style()


def table_style() -> str:
    """卡片内键值表格样式（每次求值，主题切换后重新应用）。"""
    return theme.qss("""
    QTableWidget {
        border: none;
        background: transparent;
        font-size: 11px;
        gridline-color: transparent;
        /* 选中底色透明：::item:selected 只写 background 时 Qt 仍按调色板画系统蓝，
           必须显式关掉 selection-background-color（2026-10-09 修复点击复制后残留蓝框）*/
        selection-background-color: transparent;
    }
    QTableWidget::item {
        padding: 2px 0px;
        border-bottom: 1px solid @border@;
        min-height: 18px;
    }
    /* Windows11 样式会给悬停/按下态画一层底色（深色下偏蓝），一并关掉 */
    QTableWidget::item:hover {
        background: transparent;
    }
    QTableWidget::item:selected {
        background: transparent;
    }
    """)


# 右列数值「点击复制」的行：左列标签 → 命中即启用复制（如「舰船 ID」）
COPYABLE_LABELS: tuple[str, ...] = (
    "舰船 ID",
)


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
# 射界行文本（卡片与详情面板共用，避免两处显示规则各写一遍）
# ══════════════════════════════════════════════════════════

def firing_arc_label(fa: dict, wep_name: str) -> str:
    """射界行左列标签：多配置船体时附当前配置字母，便于确认跟随切换。"""
    letter = fa.get("config_group") or ""
    return f"{wep_name} 射界（{letter}）" if letter else f"{wep_name} 射界"


def firing_arc_value_text(fa: dict) -> str:
    """射界行数值文本。

    鱼雷等左右分列武器：显示「单侧发射窗口」的最前端／最后端
    （该舷各发射器可射范围的**并集**，与游戏内鱼雷扇区两条边界一致）；
    其它武器：显示前向／后向齐射角。
    """
    sides = fa.get("sides") or []
    if sides:
        s0 = sides[0]
        return f"最前 {s0['front']:g}°／最后 {s0['rear']:g}°"
    return f"{fa.get('front', 0)}°（前）/{fa.get('back', 0)}°（后）"


def firing_arc_tooltip(fa: dict) -> str:
    """射界行按钮提示：列出各舷窗口与各组发射器自身窗口。"""
    sides = fa.get("sides") or []
    if not sides:
        return "点击查看该武器系统的射界图（总览 + 单炮塔详情）"
    tips = ["点击查看该武器系统的射界图（总览 + 单发射器详情）",
            "单侧发射窗口（该舷各发射器可射范围的并集）："]
    for s in sides:
        tips.append(f"　{s['label']}：最前 {s['front']:g}°／最后 {s['rear']:g}°")
    groups = [(s, g) for s in sides for g in (s.get("groups") or [])]
    if groups:
        tips.append("各组发射器自身窗口：")
        for s, g in groups:
            tag = g.get("hp_key") or g.get("gun_name") or ""
            tips.append(f"　{s['label']} {tag}：{g['front']:g}°~{g['rear']:g}°")
    return "\n".join(tips)


class CardFrame(QGroupBox):
    """卡片基座：圆角卡面 + 横跨顶边框的「水晶棱角」标题框。

    标题框不是贴在卡内，而是**跨在卡片顶边框上**（一截在卡外、一截在卡内），
    底边是卡内的一条细线，右端 45° 切角，左端不贴卡片左边框而是内缩一段：
    · 卡面/边框由本控件自绘，顶边框在标题框范围内留出缺口（QSS 画不出缺口）
    · 标题文字仍交给 QSS 的 ::title，字体与度量由 Qt 负责
    · 卡内那半个标题框铺一层极淡信号色，读作棱晶片的折射面
    · 底边左端一小段信号色锚点，与全息面板的左缘锚点同一套语言
    """

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("class", "ShipCardWidget")
        text = (title or "").strip()
        self.setTitle(text)
        if not text:
            # 属性必须在 setStyleSheet 之前设好，QSS 属性选择器才会命中
            self.setProperty("untitled", True)
        self.setStyleSheet(card_style())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    # ── 标题框几何 ──────────────────────────────────────

    def _plate_end(self) -> float:
        """标题框右端 x：文字右缘 + 余量，并保证切角后仍在卡内。"""
        fm = QFontMetrics(self.font())
        return min(CARD_TITLE_LEFT + fm.horizontalAdvance(self.title()) + 9,
                   self.width() - CARD_RADIUS - CARD_PLATE_CHAMFER - 6)

    def _body_path(self) -> QPainterPath:
        rect = QRectF(0.5, CARD_EDGE_Y + 0.5,
                      self.width() - 1.0, self.height() - CARD_EDGE_Y - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        return path

    def paintEvent(self, event):
        titled = bool(self.title().strip())
        if not titled:
            super().paintEvent(event)
            return

        x_end = self._plate_end()
        pl = CARD_PLATE_LEFT
        if x_end <= pl + 20 or self.height() <= CARD_PLATE_BOTTOM + 4:
            super().paintEvent(event)
            return

        # 1) 卡面（半透明皮肤也能透出背景）+ 标题框在卡内的折射底面
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.qcolor("card_bg")))
        p.drawPath(self._body_path())

        y0 = CARD_EDGE_Y + 0.5
        pb = CARD_PLATE_BOTTOM
        ch = CARD_PLATE_CHAMFER
        facet = QColor(theme.qcolor("accent"))
        facet.setAlphaF(0.10 if theme.dark else 0.05)
        p.setBrush(facet)
        p.drawPolygon(QPolygonF([
            QPointF(pl, y0), QPointF(x_end, y0),
            QPointF(x_end, pb - ch), QPointF(x_end - ch, pb), QPointF(pl, pb),
        ]))
        p.end()

        # 2) 交给 QGroupBox 画标题文字（QSS 里卡面与边框已设为 transparent/none）
        super().paintEvent(event)

        # 3) 描边：卡片边框（顶边在标题框处断开）+ 棱角标题框
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(theme.qcolor("border")), 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        r = CARD_RADIUS
        right, bottom = self.width() - 0.5, self.height() - 0.5
        border = QPainterPath()
        # 顶边左段（卡片左边框 → 标题框左端）
        border.moveTo(0.5, y0 + r)
        border.arcTo(QRectF(0.5, y0, 2 * r, 2 * r), 180, -90)
        border.lineTo(pl, y0)
        # 顶边右段（标题框右端 → 卡片右边框）
        border.moveTo(x_end, y0)
        border.lineTo(right - r, y0)
        border.arcTo(QRectF(right - 2 * r, y0, 2 * r, 2 * r), 90, -90)
        border.lineTo(right, bottom - r)
        border.arcTo(QRectF(right - 2 * r, bottom - 2 * r, 2 * r, 2 * r), 0, -90)
        border.lineTo(0.5 + r, bottom)
        border.arcTo(QRectF(0.5, bottom - 2 * r, 2 * r, 2 * r), 270, -90)
        border.lineTo(0.5, y0 + r)
        p.drawPath(border)

        # 标题框：闭合的棱晶片，右下斜切 45°
        plate = QPainterPath()
        plate.moveTo(pl, CARD_PLATE_TOP)
        plate.lineTo(x_end, CARD_PLATE_TOP)
        plate.lineTo(x_end, pb - ch)
        plate.lineTo(x_end - ch, pb)
        plate.lineTo(pl, pb)
        plate.closeSubpath()
        p.drawPath(plate)

        # 斜切内侧再画一条平行棱线，窄窄一道斜面才像晶体而不是普通切角
        bevel = QPen(pen.color(), 1.0)
        c = QColor(pen.color())
        c.setAlphaF(0.55)
        bevel.setColor(c)
        p.setPen(bevel)
        p.drawLine(QPointF(x_end - 4, pb - ch), QPointF(x_end - ch - 4, pb))

        # 底边左端信号色锚点
        anchor = QPen(QColor(theme.qcolor("accent")), 2.0)
        anchor.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(anchor)
        p.drawLine(QPointF(pl + 4, pb), QPointF(max(pl + 4, min(pl + 20, x_end - ch - 6)), pb))
        p.end()


class ShipCardWidget(CardFrame):
    """单张数据卡片，包含标题和键值表格"""

    firing_arc_clicked = Signal(dict)
    #: 卡片底部动作按钮点击（data 为构造时传入的任意载荷，如 ship_id）
    action_clicked = Signal(object)

    def __init__(self, section: dict, parent=None, firing_arc: dict | None = None,
                 action: dict | None = None):
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
            action: 卡片最下方动作行（{"label": 左列标题, "text": 按钮文字,
                    "tooltip", "data"}），点击发射 action_clicked(data)
        """
        label = section.get("label", "")
        icon = section.get("icon", "") or SECTION_ICONS.get(label, "")
        super().__init__(f"{icon} {label}".strip() if icon else label, parent)
        self._adjusting = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget()
        self._table.setStyleSheet(table_style())
        self._table.setColumnCount(2)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 表头隐藏
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 列宽：名称按内容（_fit_columns 定宽，分隔线行不参与），数值填满剩余
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setStretchLastSection(True)
        # 行高自适应文字换行
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # 启用文字换行
        self._table.setWordWrap(True)
        # 单元格文本不省略号截断（setTextElideMode 属于视图，而非 QTableWidgetItem）
        self._table.setTextElideMode(Qt.TextElideMode.ElideNone)

        #: 行号 → 可复制的文本（点击右列数值即写入剪贴板）
        self._copy_cells: dict[int, str] = {}
        # 悬停可复制行时显示手型光标（cellEntered 需要开启鼠标跟踪）
        self._table.setMouseTracking(True)
        self._table.cellEntered.connect(self._on_cell_entered)
        self._table.cellClicked.connect(self._on_cell_clicked)

        self._populate_items(section.get("items", []))

        # 射界入口：卡片底部追加可点击按钮（不显示炮塔数量）
        if firing_arc and firing_arc.get("mode") == "front_back":
            self._add_firing_arc_row(firing_arc)

        # 左列宽度由 _fit_columns 按标签内容定，右列填满剩余
        self._table.horizontalHeader().setMaximumSectionSize(300)

        layout.addWidget(self._table)

        # 卡片最下方动作按钮（如「3D 模型查看」）
        if action:
            self._add_action_row(action)

        # 延迟自适应高度，等布局完成后再计算
        QTimer.singleShot(0, self._adjust_height)

    def _add_action_row(self, action: dict) -> None:
        """在卡片最下方添加动作行：左列标题 + 右列（数据区）按钮。

        与表格内其它行保持同一格式；点击发射 action_clicked(data)。
        action: {"label": 左列标题, "text": 按钮文字, "button": 按钮文字（优先）, "tooltip", "data"}
                为兼容旧调用：未给 label 时用 text 作左列标题；未给 text/button 时按钮显示「打开」。
        """
        row = self._table.rowCount()
        self._table.insertRow(row)

        label = action.get("label") or action.get("text", "")
        name_item = QTableWidgetItem(label)
        name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)

        # 按钮文字：button > text > 「打开」
        # （曾写成“给了 label 就强制显示『打开』”，导致调用方传的 text「查看/详情」被吞掉）
        btn_text = action.get("button") or action.get("text") or "打开"
        btn = QPushButton(btn_text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumWidth(76)
        tip = action.get("tooltip", "")
        if tip:
            btn.setToolTip(tip)
        theme.bind(btn, "QPushButton { border-radius: 4px; padding: 4px 10px; font-size: 12px; }")
        data = action.get("data")
        btn.clicked.connect(lambda _=False: self.action_clicked.emit(data))

        holder = QWidget()
        holder_lay = QHBoxLayout(holder)
        holder_lay.setContentsMargins(0, 0, 0, 0)
        holder_lay.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        holder_lay.addWidget(btn)
        self._table.setCellWidget(row, 1, holder)

    def _add_firing_arc_row(self, fa: dict) -> None:
        """在卡片底部添加射界行：左列标签 + 右列可点击的值按钮（齐射角）"""
        row = self._table.rowCount()
        self._table.insertRow(row)
        wep_name = "鱼雷发射器" if fa.get("slot_type") == "torpedoes" else "炮塔"
        # 左列：标签
        name_item = QTableWidgetItem(firing_arc_label(fa, wep_name))
        name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)
        # 右列：值按钮（可点击弹出射界弹窗）
        # 鱼雷：单侧发射窗口「最前/最后」（该舷各发射器并集，同游戏内扇区）；
        # 其它武器：前向/后向齐射角
        value_text = firing_arc_value_text(fa)
        btn = QPushButton()
        btn.setText(value_text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(firing_arc_tooltip(fa))
        theme.bind(btn, "QPushButton { border-radius: 4px; padding: 4px 8px;"
                        " font-size: 12px; text-align: center; }")
        btn.clicked.connect(lambda _=False: self.firing_arc_clicked.emit(fa))
        self._table.setCellWidget(row, 1, btn)

    def set_firing_arc(self, fa: dict) -> None:
        """动态为已渲染的卡片追加射界按钮行（供 weapon widget 在最后一座炮卡片上调用）"""
        if fa and fa.get("mode") == "front_back":
            self._add_firing_arc_row(fa)

    def resizeEvent(self, event):
        """窗口缩放时重新调整高度与列宽"""
        if not self._adjusting:
            self._adjusting = True
            super().resizeEvent(event)
            self._adjust_height()
            self._adjusting = False
        # resizeEvent 阶段表格视口还是旧宽度，等布局落定后再定列宽
        QTimer.singleShot(0, self._fit_columns)

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

        # 显式颜色优先（value 空时的描述行：颜色作用于左列名称，如布尔状态词条）
        color = item.get("color", "")

        # 左列：名称
        name_item = QTableWidgetItem(name)
        if color and not (value or unit):
            name_item.setForeground(QColor(color))
        else:
            name_item.setForeground(QColor(label_color()))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, 0, name_item)

        # 右列：数值 + 单位
        display_value = f"{value} {unit}" if unit and value else (value or unit or "")
        value_item = QTableWidgetItem(display_value)
        if color:
            value_item.setForeground(QColor(color))
        else:
            stripped = display_value.strip()
            # 仅对含数字的正负值自动着色（纯文本 +/− 不处理）
            has_sign = stripped.startswith("+") or stripped.startswith("-")
            has_digit = any(c.isdigit() for c in stripped)
            if has_sign and has_digit:
                if stripped.startswith("+"):
                    value_item.setForeground(QColor(theme["value_pos"]))
                else:
                    value_item.setForeground(QColor(theme["value_neg"]))
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

        # 可点击复制：默认「舰船 ID」等行，或 item 里显式给 copyable=True
        # 注意：**不要**给数值格子加 ItemIsSelectable。选中态会画出系统蓝框
        # （紧跟在左列标题后面），而 cellClicked 对不可选中的格子同样会触发。
        _copy_text = display_value.strip()
        if _copy_text and (item.get("copyable") or name in COPYABLE_LABELS):
            self._copy_cells[row] = _copy_text
            _tip = value_item.toolTip()
            _copy_tip = f"点击复制：{_copy_text}"
            value_item.setToolTip(f"{_copy_tip}\n{_tip}" if _tip else _copy_tip)

    # ── 点击复制 ─────────────────────────────────────────

    def _on_cell_entered(self, row: int, col: int) -> None:
        """鼠标进入单元格：可复制行的数值列显示手型光标。"""
        try:
            if col == 1 and row in self._copy_cells:
                self._table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self._table.viewport().unsetCursor()
        except (RuntimeError, AttributeError):
            pass

    def _on_cell_clicked(self, row: int, col: int) -> None:
        """点击可复制行的数值单元格 → 写入系统剪贴板。"""
        if col != 1:
            return
        text = self._copy_cells.get(row)
        if not text:
            return
        QApplication.clipboard().setText(text)
        QToolTip.showText(QCursor.pos(), f"已复制：{text}")
        try:
            bus.log_message.emit(f"📋 已复制：{text}")
        except Exception:  # noqa: BLE001
            pass

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
        """添加分隔线行。

        用跨两列的 1px 横线，而不是「─」×30 的文本：文本宽度固定（约 230px），
        既会把左列撑宽、又会越过列边界压到右列数值上。
        """
        row = self._table.rowCount()
        self._table.insertRow(row)

        for col in range(self._table.columnCount()):
            empty = QTableWidgetItem("")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, col, empty)
        self._table.setSpan(row, 0, 1, self._table.columnCount())

        line = QFrame()
        line.setFixedHeight(1)
        theme.bind(line, "QFrame { background: @border_soft@; border: none; }")
        holder = QWidget()
        holder_lay = QHBoxLayout(holder)
        holder_lay.setContentsMargins(0, 5, 0, 4)
        holder_lay.addWidget(line)
        self._table.setCellWidget(row, 0, holder)

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
                        background: @icon_btn_bg@; border: 1px solid @icon_btn_border@;
                        border-radius: 3px; font-size: 9px; color: @icon_btn_text@;
                    }
                    QPushButton:hover { background: @icon_btn_bg_hover@; border-color: @icon_btn_border_hi@; }
                    QPushButton:checked {
                        background: @icon_btn_checked@; color: @icon_btn_text_hi@;
                        border-color: @icon_btn_border_hi@;
                    }
                """))
                group.addButton(btn, v)
                btn_layout.addWidget(btn)
                if v == current:
                    btn.setChecked(True)

        btn_layout.addStretch()
        self._table.setCellWidget(row, 1, btn_widget)
        self._table.setRowHeight(row, 24)

    # ── 列宽 / 行高 ──────────────────────────────────────

    def _fit_columns(self) -> None:
        """左列宽度按标签实际文字定，右列吃掉剩余宽度。

        以前用 ResizeToContents：分隔线行铺的是「─」×30，会把左列直接撑到
        300px 上限，右列被挤出视口——数值就会紧贴右边框甚至被裁掉。
        """
        try:
            vw = self._table.viewport().width()
            rows = self._table.rowCount()
        except (RuntimeError, AttributeError):
            return
        if vw <= 0 or rows <= 0:
            return
        widest = 0
        for r in range(rows):
            item = self._table.item(r, 0)
            text = item.text() if item is not None else ""
            if not text or text.startswith("─"):
                continue
            font = item.font()
            fm = QFontMetrics(font) if font.pointSize() > 0 or font.pixelSize() > 0 \
                else self._table.fontMetrics()
            widest = max(widest, fm.horizontalAdvance(text))
        # 右列至少留 110px（其最小宽度），左列最多占视口 60%
        w0 = max(40, min(widest + 8, int(vw * 0.6), vw - 110))
        self._table.setColumnWidth(0, w0)

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
        self._fit_columns()
        self._table.resizeRowsToContents()
        rows = self._table.rowCount()
        height = 4
        for r in range(rows):
            height += self._table.rowHeight(r) + 2
        self._table.setFixedHeight(height)
        # 卡片最下方动作按钮（若有）的高度也需计入
        extra_h = 0
        for child in self.children():
            if isinstance(child, QPushButton):
                extra_h += child.sizeHint().height() + 6
        # 38 = 顶边框上方标题框上半截(14) + 卡内标题带(16) + 布局上边距 2 + 下内边距 6
        # 无标题卡片 QSS 没有标题位，只留 12（上 6 + 布局 2 + 下 4）
        card_height = height + (12 if self.property("untitled") else 38) + extra_h
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
