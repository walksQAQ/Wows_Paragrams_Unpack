"""SciFiButton —— 斜切全息按钮。

科幻 HUD 的按钮不是圆角矩形，而是**带 45° 切角的薄片**：左上与右下各切一刀，
外轮廓由「蓝色光晕 → 银色金属 → 蓝色光线芯」三层描边构成，选中时左侧亮起一道
信号色光条。

继承 QPushButton，因此 clicked / setEnabled / setToolTip / setCheckable 等行为
与原按钮完全一致，只重写绘制。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from utils.theme import theme
from ui.widgets.scifi_panel import _LIVE, _with_alpha


class SciFiButton(QPushButton):
    """斜切薄片按钮（左上 / 右下 45° 切角）。"""

    CHAMFER = 9
    HEIGHT = 28

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = False

        f = QFont(self.font())
        f.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
        f.setPointSize(9)
        self.setFont(f)
        _LIVE.add(self)

    # ── 状态 ─────────────────────────────────────────────
    def _on_style_changed(self) -> None:
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):  # noqa: N802
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.text()) + 34
        return QSize(max(w, self.minimumWidth()), self.HEIGHT)

    # ── 几何 ─────────────────────────────────────────────
    def _shape_path(self) -> QPainterPath:
        w, h = float(self.width()), float(self.height())
        c = float(min(self.CHAMFER, h / 2.0))
        p = QPainterPath()
        p.moveTo(c, 0.5)
        p.lineTo(w - 0.5, 0.5)
        p.lineTo(w - 0.5, h - c)
        p.lineTo(w - c, h - 0.5)
        p.lineTo(0.5, h - 0.5)
        p.lineTo(0.5, c)
        p.closeSubpath()
        return p

    def _frame_strokes(self) -> list[list[QPointF]]:
        """按钮用完整闭合轮廓：左上 / 右下 45° 切角，保证「这是个按钮」。"""
        w, h = float(self.width()), float(self.height())
        c = float(min(self.CHAMFER, h / 2.0))
        return [[
            QPointF(c, 0.5), QPointF(w - 0.5, 0.5), QPointF(w - 0.5, h - c),
            QPointF(w - c, h - 0.5), QPointF(0.5, h - 0.5), QPointF(0.5, c),
            QPointF(c, 0.5),
        ]]

    # ── 绘制 ─────────────────────────────────────────────
    def paintEvent(self, e) -> None:  # noqa: N802
        from ui.widgets.scifi_panel import paint_chamfer_frame

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._shape_path()

        enabled = self.isEnabled()
        active = self.isChecked() or self.isDown()
        hovered = self._hover and enabled

        # 1) 底：深蓝薄片（上亮下暗），选中时换成冰蓝调
        if not enabled:
            base = QColor(theme["panel_bg"])
            base.setAlphaF(0.40)
            p.fillPath(path, base)
        else:
            if active:
                top_c = QColor(theme.qcolor("accent"))
                top_c.setAlphaF(0.30)
                bot_c = QColor(theme.qcolor("accent"))
                bot_c.setAlphaF(0.12)
            elif hovered:
                top_c = QColor(theme["hover_bg"])
                bot_c = QColor(theme["hover_bg"])
                bot_c.setAlphaF(0.60)
            else:
                top_c = QColor(theme.qcolor("metal_hi"))
                top_c.setAlphaF(0.10 if theme.dark else 0.55)
                bot_c = QColor(theme.qcolor("metal_lo"))
                bot_c.setAlphaF(0.04 if theme.dark else 0.16)
            grad = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
            grad.setColorAt(0.0, top_c)
            grad.setColorAt(1.0, bot_c)
            p.fillPath(path, QBrush(grad))

        # 2) 边：切角细线 + 微弱辉光
        if enabled:
            paint_chamfer_frame(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                float(self.CHAMFER), glow=hovered or active)
        else:
            dull = QColor(theme["border"])
            p.setPen(QPen(dull, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # 3) 左侧信号光条：悬停 / 选中时亮起
        if enabled and (hovered or active):
            bar = QColor(theme.qcolor("accent"))
            bar.setAlphaF(1.0 if active else 0.8)
            p.setPen(QPen(bar, 2))
            p.drawLine(QPointF(1.5, 7), QPointF(1.5, self.height() - 7))

        # 4) 文字
        if not enabled:
            p.setPen(QColor(theme["text_hint"]))
        elif active:
            p.setPen(QColor(theme.qcolor("accent_hi")))
        elif hovered:
            p.setPen(QColor(theme.qcolor("accent")))
        else:
            p.setPen(QColor(theme["text"]))
        p.setFont(self.font())
        p.drawText(QRectF(path.boundingRect()), int(Qt.AlignmentFlag.AlignCenter), self.text())
        p.end()
