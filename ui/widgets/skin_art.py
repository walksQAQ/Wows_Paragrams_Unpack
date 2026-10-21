"""角色皮肤（二次元主题）的装饰层。

本模块是**通用**的：所有纹样按皮肤能力位（`brand` / `watermark` / `art_slot`）
分发，新增一套二次元主题只需在 `utils.theme.SKINS` 里注册一条，这里不用改。

已内置的纹样
------------
``mobius``  莫比乌斯环
    来自官方对《崩坏：星穹铁道》**翁法罗斯这个世界本身**的形状设定——永恒之地、
    永劫回归，世界即一条首尾相接、扭一次才回到原点的带子（昔涟是「创世」泰坦、
    「翁法罗斯之心」，所以这套皮肤拿世界之形做空间基底符号）。
``heart``   心形
    昔涟的「爱」是官方文案明写的（「去人们心中栽种『爱』的水晶花」、光锥
    《This Love, Forever》），官方立绘外形本身就是一颗心。
``crystal`` 三枚切面棱晶
    银质水晶发饰 / 银质粉心晶石戒指 / 「碎片就像水晶花一样」。

这些绘制全部是静态、低透明度的线面组合，不参与任何业务交互。
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from utils.theme import theme

#: 装饰列宽度（px）
ART_WIDTH = 196
#: 窗口窄于此宽度时自动收起：装饰列不能把详情面板挤到裁切
MIN_WINDOW_WIDTH = 1700

def _mobius_point(cx: float, cy: float, radius: float, half_w: float,
                  u: float, v: float, tilt: float, squash: float) -> QPointF:
    """莫比乌斯参数面 ``(u, v)`` 上的一点，投影到 2D。

    x = (R + v·cos(u/2))·cos(u)
    y = (R + v·cos(u/2))·sin(u)
    z =  v·sin(u/2)                     ← 这一项产生半圈扭转
    再绕 X 轴倾斜 ``tilt`` 后正交投影。
    """
    rr = radius + v * math.cos(u / 2.0)
    x = rr * math.cos(u)
    y = rr * math.sin(u)
    z = v * math.sin(u / 2.0)
    y2 = y * math.cos(tilt) - z * math.sin(tilt)
    return QPointF(cx + x, cy + y2 * squash)


def mobius_ribbon(cx: float, cy: float, radius: float, half_w: float,
                  *, tilt: float = 0.62, squash: float = 0.86,
                  steps: int = 180) -> tuple[QPainterPath, list[QPolygonF]]:
    """返回 (带状外形, 若干条纵向丝线)。丝线在扭转处会互相交叉，是「莫比乌斯」的关键。"""
    band = QPainterPath()
    edge_a: list[QPointF] = []
    edge_b: list[QPointF] = []
    for i in range(steps + 1):
        u = 2.0 * math.pi * i / steps
        edge_a.append(_mobius_point(cx, cy, radius, half_w, u, half_w, tilt, squash))
        edge_b.append(_mobius_point(cx, cy, radius, half_w, u, -half_w, tilt, squash))

    band.addPolygon(QPolygonF(edge_a + list(reversed(edge_b))))
    band.closeSubpath()

    strands: list[QPolygonF] = []
    for frac in (-1.0, -0.5, 0.0, 0.5, 1.0):
        pts = [_mobius_point(cx, cy, radius, half_w, 2.0 * math.pi * i / steps,
                             half_w * frac, tilt, squash)
               for i in range(steps + 1)]
        strands.append(QPolygonF(pts))
    return band, strands


def heart_path(cx: float, cy: float, size: float) -> QPainterPath:
    """经典心形参数曲线（size ≈ 心宽 / 2）。"""
    path = QPainterPath()
    s = size / 16.0
    for i in range(0, 181):
        t = 2.0 * math.pi * i / 180.0
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t) - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t) - math.cos(4 * t))
        pt = QPointF(cx + x * s, cy - y * s)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


def crystal_shard(cx: float, cy: float, length: float, width: float,
                  angle_deg: float) -> QPainterPath:
    """一枚细长棱晶：菱形上下各带一个切面。"""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)

    def p(dx: float, dy: float) -> QPointF:
        return QPointF(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

    path = QPainterPath()
    path.moveTo(p(0, -length))
    path.lineTo(p(width, -length * 0.18))
    path.lineTo(p(0, length))
    path.lineTo(p(-width, -length * 0.18))
    path.closeSubpath()
    return path


# ─────────────────────────────────────────────────────────────
#  色板助手
# ─────────────────────────────────────────────────────────────

def _pink(alpha: float) -> QColor:
    c = QColor(theme.qcolor("accent"))
    c.setAlphaF(alpha)
    return c


def _violet(alpha: float) -> QColor:
    c = QColor(theme.qcolor("crystal"))
    c.setAlphaF(alpha)
    return c


def _periwinkle(alpha: float) -> QColor:
    c = QColor(theme.qcolor("crystal_edge"))
    c.setAlphaF(alpha)
    return c


# ─────────────────────────────────────────────────────────────
#  绘制
# ─────────────────────────────────────────────────────────────

def _draw_mobius(p: QPainter, cx: float, cy: float, radius: float,
                 alpha_scale: float) -> None:
    half_w = radius * 0.30
    tilt, squash = 0.75, 0.78
    _, strands = mobius_ribbon(cx, cy, radius, half_w, tilt=tilt, squash=squash)

    # 带面：按参数 u 分段填充，每片按「朝向」给不同透明度。
    # 这条假光照是它区别于普通椭圆环的关键——正面亮、转到背面就暗下去。
    steps = 180
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(steps):
        u0 = 2.0 * math.pi * i / steps
        u1 = 2.0 * math.pi * (i + 1) / steps
        quad = QPolygonF([
            _mobius_point(cx, cy, radius, half_w, u0, half_w, tilt, squash),
            _mobius_point(cx, cy, radius, half_w, u0, -half_w, tilt, squash),
            _mobius_point(cx, cy, radius, half_w, u1, -half_w, tilt, squash),
            _mobius_point(cx, cy, radius, half_w, u1, half_w, tilt, squash),
        ])
        shade = 0.25 + 0.75 * (0.5 + 0.5 * math.cos(u0 / 2.0))
        p.setBrush(_pink(0.13 * shade * alpha_scale))
        p.drawPolygon(quad)

    # 两条边分别描线：莫比乌斯环只有一条边，它绕两圈才回到起点，
    # 所以投影出来正好是内外两条互相咬合的曲线——这比画一个闭合轮廓更像环。
    grad = QLinearGradient(QPointF(cx - radius, cy - radius),
                           QPointF(cx + radius, cy + radius))
    grad.setColorAt(0.0, _pink(0.62 * alpha_scale))
    grad.setColorAt(0.5, _periwinkle(0.40 * alpha_scale))
    grad.setColorAt(1.0, _pink(0.55 * alpha_scale))
    pen = QPen(grad, 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen)
    for v in (half_w, -half_w):
        curve = QPolygonF([
            _mobius_point(cx, cy, radius, half_w, 2.0 * math.pi * i / steps,
                          v, tilt, squash)
            for i in range(steps + 1)
        ])
        p.drawPolyline(curve)

    # 纵向丝线：扭转处彼此交叉，这是莫比乌斯环的识别点
    for i, poly in enumerate(strands):
        a = (0.28 if i in (0, 4) else 0.18) * alpha_scale
        p.setPen(QPen(_violet(a), 0.9))
        p.drawPolyline(poly)

    # 光点：缎带上的高光
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_pink(0.55 * alpha_scale))
    p.drawEllipse(_mobius_point(cx, cy, radius, half_w, math.pi * 0.28,
                                half_w * 0.55, tilt, squash), 2.1, 2.1)


def _draw_heart(p: QPainter, cx: float, cy: float, size: float,
                alpha_scale: float) -> None:
    """心形：昔涟的「爱」锚点。描边 + 极淡填充，不抢正文。"""
    path = heart_path(cx, cy, size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_pink(0.10 * alpha_scale))
    p.drawPath(path)
    pen = QPen(_pink(0.78 * alpha_scale), 1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    # 心内一点银光，呼应银质粉心戒指
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, min(255, int(150 * alpha_scale))))
    p.drawEllipse(QPointF(cx - size * 0.22, cy - size * 0.18),
                  size * 0.11, size * 0.11)


def _draw_crystals(p: QPainter, cx: float, cy: float, scale: float,
                   alpha_scale: float) -> None:
    """三枚棱晶组成的水晶簇：白色基底 + 藕荷紫切面 + 长春花蓝高光棱。"""
    specs = ((-0.62, 0.34, -22.0, 1.00),
             (0.02, 0.00, 4.0, 1.22),
             (0.66, 0.38, 26.0, 0.86))
    for dx, dy, angle, k in specs:
        length = scale * k
        width = length * 0.36
        bx, by = cx + dx * scale, cy + dy * scale
        path = crystal_shard(bx, by, length, width, angle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, min(255, int(165 * alpha_scale))))
        p.drawPath(path)
        p.setPen(QPen(_violet(0.62 * alpha_scale), 1.1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # 内部棱线，制造折射
        a = math.radians(angle)
        p.setPen(QPen(_periwinkle(0.40 * alpha_scale), 0.8))
        p.drawLine(QPointF(bx, by - length * 0.9),
                   QPointF(bx + width * 0.55 * math.cos(a + 1.4),
                           by + length * 0.6))


def paint_skin_watermark(p: QPainter, r: QRectF, alpha: float = 1.0) -> None:
    """工作区**背景层**水印：按当前皮肤的能力位绘制。

    只画在 HoloBackdrop 的底图上，也就是所有面板的**下面**——因此它绝不会
    覆盖任何文字或数值，只在面板间隙露出一点空间感。面板底本身也带一点透明，
    能透出约三成纹样，但正文始终画在不透明的前景上。
    """
    kind = theme.watermark_style
    if not kind or r.width() < 320 or r.height() < 280:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    if kind == "mobius":
        radius = min(r.width() * 0.36, r.height() * 0.44)
        cx = r.left() + r.width() * 0.50
        cy = r.top() + r.height() * 0.46
        _draw_mobius(p, cx, cy, radius, 0.95 * alpha)
        _draw_heart(p, cx, cy + radius * 0.02, radius * 0.20, 0.62 * alpha)
    p.restore()


# ─────────────────────────────────────────────────────────────
#  装饰列控件
# ─────────────────────────────────────────────────────────────

class SkinArtSlot(QWidget):
    """角色皮肤的纹样列：纯装饰，不承载任何数据。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SkinArtSlot")
        self.setFixedWidth(ART_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("")

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
        hol = theme.holo_enabled
        a = 1.0 if hol else 0.45

        # 1) 竖向粉光：只做空间感
        grad = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
        grad.setColorAt(0.0, _pink(0.07 if hol else 0.04))
        grad.setColorAt(0.42, _pink(0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(r)

        # 2) 纹样：莫比乌斯环 + 心 + 水晶簇
        inner = r.adjusted(8, 8, -8, -8)
        _draw_placeholder_motifs(p, inner, a)

        # 3) 细框 + 四角定位短线压在立绘上，保留留白区的边界感
        frame = QColor(theme.qcolor("panel_frame"))
        frame.setAlphaF(0.70)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(frame, 1))
        p.drawRect(inner)
        p.setPen(QPen(_pink(0.80), 1.5))
        _draw_corner_ticks(p, inner)


def _draw_placeholder_motifs(p: QPainter, inner: QRectF, a: float) -> None:
    """通用占位纹样：莫比乌斯环 + 心 + 水晶簇（没有专属立绘的皮肤用它）。"""
    w = inner.width()
    cx = inner.center().x()
    radius = min(w * 0.34, inner.height() * 0.14)
    ring_cy = inner.top() + inner.height() * 0.28
    _draw_mobius(p, cx, ring_cy, radius, a)
    _draw_heart(p, cx, ring_cy + radius * 0.02, radius * 0.32, a * 1.15)
    _draw_crystals(p, cx, inner.top() + inner.height() * 0.55,
                   min(w * 0.16, 32.0), a)


def _draw_corner_ticks(p: QPainter, r: QRectF) -> None:
    """四角定位短线。"""
    k = 13.0
    for x, y, dx, dy in ((r.left(), r.top(), 1, 1),
                         (r.right(), r.top(), -1, 1),
                         (r.left(), r.bottom(), 1, -1),
                         (r.right(), r.bottom(), -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))


def art_slot_visible(window_width: int) -> bool:
    """当前是否应显示装饰列（皮肤能力位 + 窗口宽度双条件）。"""
    return theme.uses_art_slot and window_width >= MIN_WINDOW_WIDTH


__all__ = ["SkinArtSlot", "ART_WIDTH", "MIN_WINDOW_WIDTH",
           "art_slot_visible", "paint_skin_watermark",
           "mobius_ribbon", "heart_path", "crystal_shard"]
