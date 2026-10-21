"""二次元皮肤的装饰位（预留空间，不含任何业务控件）。

设计意图
--------
「白 + 浅粉」这套皮肤需要一块可以放插画／立绘的地方，但主窗口的每一寸
横向空间都归功能面板所有。所以这里**显式预留一根装饰列**：

  * 只在 ``theme.mode == "anime"`` 且全息效果开启时出现，其余主题宽度为 0；
  * 窗口过窄时自动隐藏，避免挤压详情面板；
  * 里面没有任何可交互控件，纯绘制，不含业务逻辑；
  * 目前画的是占位纹样 + 「立绘预留区」字样，后续把图交给
    :meth:`AnimeArtSlot.set_art` 即可直接替换成正式插画，无需再动布局。

这样「二次元主题设计版本」的可用空间是提前就位、可验证的，而不是等到
真的做插画时才发现没地方放。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from utils.theme import theme

#: 装饰列宽度（px）
ART_WIDTH = 176
#: 窗口窄于此宽度时自动收起：装饰列不能把详情面板挤到裁切
#: （1440 默认宽度下保持隐藏，最大化到 1080p 及以上才会出现）
MIN_WINDOW_WIDTH = 1660


class AnimeArtSlot(QWidget):
    """二次元皮肤专属的装饰列：预留插画 / 立绘空间。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._art: QPixmap | None = None
        self.setObjectName("AnimeArtSlot")
        self.setFixedWidth(ART_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # 纯装饰：不吃鼠标事件，不抢焦点，不进 Tab 链
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("")

    # ── 供后续接入正式插画 ──────────────────────────────
    def set_art(self, pixmap: QPixmap | None) -> None:
        """替换占位纹样为正式插画（None 表示回到占位状态）。"""
        self._art = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self.update()

    @property
    def has_art(self) -> bool:
        return self._art is not None

    def refresh_theme(self) -> None:
        self.update()

    # ── 绘制 ────────────────────────────────────────────
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        w, h = r.width(), r.height()
        if w < 8 or h < 8:
            return

        # 1) 极淡的竖向樱粉渐变底：只做空间感，不抢正文
        grad = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
        base = QColor(theme.qcolor("accent"))
        base.setAlphaF(0.055 if theme.holo_enabled else 0.03)
        clear = QColor(theme.qcolor("accent"))
        clear.setAlpha(0)
        grad.setColorAt(0.0, clear)
        grad.setColorAt(0.35, base)
        grad.setColorAt(1.0, clear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(r)

        if self._art is not None:
            self._paint_art(p, r)
            return

        # 2) 预留区：1px 樱粉细线 + 四角定位短线
        frame = QColor(theme.qcolor("panel_frame"))
        frame.setAlphaF(0.75)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(frame, 1))
        p.drawRect(r.adjusted(10, 10, -10, -10))
        tick = QColor(theme.qcolor("accent"))
        tick.setAlphaF(0.85)
        p.setPen(QPen(tick, 1.6))
        cx, cy = r.center().x(), r.center().y()
        _draw_corner_ticks(p, r.adjusted(10, 10, -10, -10))

        # 3) 中央晶体花纹：六瓣，纯细线，透明度低
        _draw_petal_motif(p, QPointF(cx, cy - 26), min(w, h) * 0.20)

        # 4) 说明文字：让「这是预留区」这件事一目了然
        from PySide6.QtGui import QFont
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        label = QColor(theme.qcolor("text_hint"))
        label.setAlphaF(0.9)
        p.setPen(QPen(label, 1))
        box = QRectF(r.left() + 16, cy + 34, w - 32, 60)
        p.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                            | Qt.TextFlag.TextWordWrap), "立绘预留区\n二次元主题专用")

    def _paint_art(self, p: QPainter, r: QRectF) -> None:
        assert self._art is not None
        scaled = self._art.scaled(
            int(r.width()) - 20, int(r.height()) - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = r.left() + (r.width() - scaled.width()) / 2
        y = r.bottom() - scaled.height() - 10
        p.setOpacity(0.96)
        p.drawPixmap(int(x), int(y), scaled)
        p.setOpacity(1.0)


def _draw_corner_ticks(p: QPainter, r: QRectF) -> None:
    """四角定位短线：呼应全息面板的「光学定位标记」语言。"""
    k = 14.0
    for x, y, dx, dy in ((r.left(), r.top(), 1, 1),
                         (r.right(), r.top(), -1, 1),
                         (r.left(), r.bottom(), 1, -1),
                         (r.right(), r.bottom(), -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))


def _draw_petal_motif(p: QPainter, c: QPointF, radius: float) -> None:
    """六瓣晶体花纹：细线轮廓，用作占位纹样（正式插画会覆盖这里）。"""
    if radius < 6:
        return
    pen = QColor(theme.qcolor("crystal"))
    pen.setAlphaF(0.55)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(pen, 1.2))
    for i in range(6):
        ang = math.radians(i * 60)
        tip = QPointF(c.x() + math.cos(ang) * radius,
                      c.y() + math.sin(ang) * radius)
        side_a = QPointF(c.x() + math.cos(ang - 0.42) * radius * 0.52,
                         c.y() + math.sin(ang - 0.42) * radius * 0.52)
        side_b = QPointF(c.x() + math.cos(ang + 0.42) * radius * 0.52,
                         c.y() + math.sin(ang + 0.42) * radius * 0.52)
        petal = QPainterPath()
        petal.moveTo(c)
        petal.quadTo(side_a, tip)
        petal.quadTo(side_b, c)
        petal.closeSubpath()
        p.drawPath(petal)
    # 花心
    core = QColor(theme.qcolor("accent"))
    core.setAlphaF(0.35)
    p.setBrush(core)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(c, radius * 0.10, radius * 0.10)


def art_slot_visible(window_width: int) -> bool:
    """当前是否应显示装饰列（皮肤 + 宽度双条件）。"""
    return bool(theme.anime) and window_width >= MIN_WINDOW_WIDTH


__all__ = ["AnimeArtSlot", "ART_WIDTH", "MIN_WINDOW_WIDTH", "art_slot_visible"]
