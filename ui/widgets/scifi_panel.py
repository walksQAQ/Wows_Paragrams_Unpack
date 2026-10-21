"""
SciFiPanel / HoloBackdrop / SparkDot —— 全息指挥台风格的纯绘制控件。

只负责外观：不持有业务状态、不发业务信号。所有颜色来自 utils.theme token，
主题切换（bus.theme_changed）与全息开关（apply_holo_enabled）时自动重绘。

最小用法::

    from ui.widgets import SciFiPanel

    panel = SciFiPanel(chamfer=12, glow=True)
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(*panel.content_margins())
    lay.addWidget(QLabel("LOADOUT"))

绘制顺序（paintEvent）：
    半透明底 → 切角外框 → 内 1px 细线 → 聚焦外辉光（3 圈递减）
    → 顶部 1px holo_ice 渐变（0 → 60% → 0）→ 8 段 11px HUD 角线
静态部分（底/框/内线/顶部高光）缓存为 QPixmap，仅在尺寸/主题变化时重建；
动态部分（辉光呼吸、HUD 悬停）每帧直接绘制，且只刷新边缘环带，不触发子控件重绘。
"""

from __future__ import annotations

import math
import weakref

from PySide6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer,
    QVariantAnimation, Property,
)
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QRegion,
)
from PySide6.QtWidgets import QFrame, QWidget

from utils.theme import theme

# 已创建的全息控件（弱引用），供全局开关 / 主题切换统一刷新
_LIVE: "weakref.WeakSet[QWidget]" = weakref.WeakSet()
_bus_hooked = False

# PRISM CORE §7：持续的循环动效属于被限制项，呼吸辉光默认关闭；
# 需要时改为 True 即可恢复（不影响任何功能逻辑）。
BREATH_ENABLED = False


def _hook_bus() -> None:
    """首次创建控件时接入主题切换信号（延迟导入，避免循环依赖）。"""
    global _bus_hooked
    if _bus_hooked:
        return
    try:
        from app.signals import bus
        bus.theme_changed.connect(lambda _mode: _refresh_all())
        _bus_hooked = True
    except Exception:  # noqa: BLE001
        pass


def _refresh_all() -> None:
    for w in list(_LIVE):
        try:
            w._on_style_changed()  # type: ignore[attr-defined]
        except RuntimeError:
            pass


def apply_holo_enabled(enabled: bool) -> None:
    """全局开关：关闭后网格、辉光、呼吸、点缀全部停用，面板回退为普通圆角面板。"""
    theme.set_holo(enabled)
    _refresh_all()


def _with_alpha(c: QColor, factor: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, c.alphaF() * factor)))
    return out


def _rect_path(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addRect(r)
    return path


def chamfer_rect_path(r: QRectF, chamfer: float = 18.0) -> QPainterPath:
    """左上 / 右下 45° 切角的矩形路径（参考图里面板与窗口的统一轮廓）。"""
    c = max(0.0, min(chamfer, r.width() / 3, r.height() / 3))
    p = QPainterPath()
    p.moveTo(r.left() + c, r.top())
    p.lineTo(r.right(), r.top())
    p.lineTo(r.right(), r.bottom() - c)
    p.lineTo(r.right() - c, r.bottom())
    p.lineTo(r.left(), r.bottom())
    p.lineTo(r.left(), r.top() + c)
    p.closeSubpath()
    return p


def paint_chamfer_frame(p: QPainter, r: QRectF, chamfer: float = 18.0,
                       *, glow: bool = True) -> QPainterPath:
    """画一层切角细线框：外侧弱辉光 + 1px 冰蓝线 + 切角描亮。"""
    path = chamfer_rect_path(r, chamfer)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if glow:
        halo = QPen(_with_alpha(theme.qcolor("light_halo"), 0.45), 3.0)
        halo.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(halo)
        p.drawPath(path)

    p.setPen(QPen(theme.qcolor("panel_frame"), 1.0))
    p.drawPath(path)

    hi = QPen(theme.qcolor("panel_frame_hi"), 1.4)
    hi.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(hi)
    c = max(0.0, min(chamfer, r.width() / 3, r.height() / 3))
    p.drawLine(QPointF(r.left() + c, r.top()), QPointF(r.left(), r.top() + c))
    p.drawLine(QPointF(r.right(), r.bottom() - c), QPointF(r.right() - c, r.bottom()))
    return path


def _draw_corner_crystal(p: QPainter, center: QPointF, s: float,
                         edge: QColor, body: QColor) -> None:
    """窗口角的晶体装饰：多面体 + 内部折射线（参考图四角的发光晶体）。

    只在工作区四角各放一个，不进入任何控件内部——保持「克制点缀」。
    """
    cx, cy = center.x(), center.y()
    p.save()

    # 主体：拉长的六边形
    path = QPainterPath()
    path.moveTo(cx, cy - s)
    path.lineTo(cx + s * 0.62, cy - s * 0.35)
    path.lineTo(cx + s * 0.52, cy + s * 0.62)
    path.lineTo(cx, cy + s)
    path.lineTo(cx - s * 0.52, cy + s * 0.62)
    path.lineTo(cx - s * 0.62, cy - s * 0.35)
    path.closeSubpath()

    fill = QColor(body)
    fill.setAlphaF(0.20 if theme.dark else 0.28)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)

    # 内部切面：一条竖直棱 + 两条斜棱，形成折射感
    facet = QColor(body)
    facet.setAlphaF(0.34 if theme.dark else 0.40)
    p.setBrush(facet)
    left = QPainterPath()
    left.moveTo(cx, cy - s)
    left.lineTo(cx, cy + s)
    left.lineTo(cx - s * 0.52, cy + s * 0.62)
    left.lineTo(cx - s * 0.62, cy - s * 0.35)
    left.closeSubpath()
    p.drawPath(left)

    hi = QColor(edge)
    hi.setAlphaF(0.30)
    p.setBrush(hi)
    top = QPainterPath()
    top.moveTo(cx, cy - s)
    top.lineTo(cx + s * 0.62, cy - s * 0.35)
    top.lineTo(cx, cy - s * 0.05)
    top.closeSubpath()
    p.drawPath(top)

    # 棱线
    line = QColor(edge)
    line.setAlphaF(0.85 if theme.dark else 0.70)
    p.setPen(QPen(line, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.drawLine(QPointF(cx, cy - s), QPointF(cx, cy + s))
    p.drawLine(QPointF(cx - s * 0.62, cy - s * 0.35), QPointF(cx + s * 0.62, cy - s * 0.35))
    p.restore()


def frame_strokes(r: QRectF, *, chamfer: float = 16.0,
                  gap_ratio: float = 0.42) -> list[list[QPointF]]:
    """科幻「角标式」框：四条边各画一段，边中留缺口。

    取自 ARWES / Star Citizen 一类 HUD 的做法——45° 切角包住四个角，
    每条边只画到 55%~60% 就在中途断开，缺口在上下、左右两侧错开，
    既保住「这是一个框」的边界感，又不像普通卡片那样呆板闭合。
    """
    c = max(6.0, min(chamfer, r.width() / 5.0, r.height() / 4.0))
    l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
    w, h = rr - l, b - t
    keep = max(0.2, 1.0 - gap_ratio)

    top_end = l + c + max(0.0, (w - 2 * c)) * keep
    right_end = t + c + max(0.0, (h - 2 * c)) * keep
    bot_end = rr - c - max(0.0, (w - 2 * c)) * keep
    left_end = b - c - max(0.0, (h - 2 * c)) * keep

    return [
        # 左上 45° 切角 + 上边
        [QPointF(l, t + c), QPointF(l + c, t), QPointF(top_end, t)],
        # 右上 45° 切角 + 右边
        [QPointF(rr - c, t), QPointF(rr, t + c), QPointF(rr, right_end)],
        # 右下 45° 切角 + 下边
        [QPointF(rr, b - c), QPointF(rr - c, b), QPointF(bot_end, b)],
        # 左下 45° 切角 + 左边
        [QPointF(l + c, b), QPointF(l, b - c), QPointF(l, left_end)],
    ]


def paint_frame_strokes(p: QPainter, strokes: list[list[QPointF]],
                        *, halo_width: float = 5.0, core_width: float = 2.0) -> None:
    """按「外晕 → 银色金属 → 蓝色光线芯」三层描边一组折线。

    三层叠加正是「银色金属与蓝色光线交织」的实现：粗的蓝晕浮在外侧，
    中间的银线提供实体感，最内层的细蓝光像电流一样穿过银线。
    """
    p.setBrush(Qt.BrushStyle.NoBrush)
    cap, join = Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin

    # 1) 蓝色光晕（外侧扩散）
    halo = QPen(_with_alpha(theme.qcolor("light_halo"), 0.5), halo_width)
    halo.setCapStyle(cap)
    halo.setJoinStyle(join)
    p.setPen(halo)
    for s in strokes:
        p.drawPolyline(s)

    # 2) 银色金属芯（浅色主题下"银"要用深灰表现，否则白底上看不见）
    grad = QLinearGradient(QPointF(0, 0), QPointF(1, 1))
    hi = QColor(theme.qcolor("metal_hi" if theme.dark else "metal_lo"))
    hi.setAlphaF(0.92 if theme.dark else 1.0)
    lo = QColor(theme.qcolor("metal_lo" if theme.dark else "metal_mid"))
    lo.setAlphaF(0.55 if theme.dark else 0.85)
    grad.setColorAt(0.0, hi)
    grad.setColorAt(1.0, lo)
    metal = QPen(QBrush(grad), max(1.4, core_width))
    metal.setCapStyle(cap)
    metal.setJoinStyle(join)
    p.setPen(metal)
    for s in strokes:
        p.drawPolyline(s)

    # 3) 蓝色光线芯（压在银线上）
    core = QPen(_with_alpha(theme.qcolor("light_core"), 0.85), max(0.8, core_width * 0.5))
    core.setCapStyle(cap)
    core.setJoinStyle(join)
    p.setPen(core)
    for s in strokes:
        p.drawPolyline(s)

    # 4) 拐点金属节点（斜切的起止点，强化精密机械感）
    node = QColor(theme.qcolor("metal_hi"))
    node.setAlphaF(0.95)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(node)
    for s in strokes:
        for pt in s[1:3]:
            p.drawRect(QRectF(pt.x() - 1.4, pt.y() - 1.4, 2.8, 2.8))


# ─────────────────────────────────────────────────────────────
#  SciFiPanel
# ─────────────────────────────────────────────────────────────

class SciFiPanel(QFrame):
    """切角全息面板容器。

    参数：
      chamfer      左上 / 右下切角尺寸（px）
      hud_corners  是否绘制四角 HUD 短线
      accent       HUD 角线使用的 token 名
      radius       另两角圆角 / 关闭全息时的普通圆角
      holo         False → 普通圆角面板（不画切角/高光/HUD）
      glow         是否为“聚焦面板”（外辉光 + 4s 呼吸），全界面建议只开一个
      spark        昔涟点缀：None | "pearl" | "violet"，画在右上角
    """

    HUD_LEN = 11
    HUD_REST = 0.40
    GLOW_RINGS = 3
    MARGIN = 4          # 外圈预留：辉光 3 圈 + HUD 悬停外扩 2px
    MIN_CHAMFER = 16    # 切角下限：太小就看不出「切角」这个语言了
    BREATH_MS = 4000
    BREATH_AMP = 0.06

    def __init__(self, parent: QWidget | None = None, *, chamfer: int = 12,
                 hud_corners: bool = True, accent: str = "holo_ice",
                 radius: int = 4, holo: bool = True, glow: bool = False,
                 spark: str | None = None, crystal: bool = False) -> None:
        super().__init__(parent)
        self._chamfer = chamfer
        self._hud = hud_corners
        self._accent = accent
        self._radius = radius
        self._holo = holo
        self._glow = glow
        self._spark = spark
        self._crystal = crystal
        self._hud_t = 0.0
        self._breath = 0.0
        self._cache: QPixmap | None = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._hud_anim = QPropertyAnimation(self, b"hudProgress", self)
        self._hud_anim.setDuration(140)   # PRISM CORE §7：悬停反馈 100–160ms
        self._hud_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._breath_anim = QVariantAnimation(self)
        self._breath_anim.setStartValue(0.0)
        self._breath_anim.setEndValue(2 * math.pi)
        self._breath_anim.setDuration(self.BREATH_MS)
        self._breath_anim.setLoopCount(-1)
        self._breath_anim.valueChanged.connect(self._on_breath)

        _LIVE.add(self)
        _hook_bus()
        self._sync_animations()

    # ── 公共辅助 ─────────────────────────────────────────
    def content_margins(self) -> tuple[int, int, int, int]:
        """推荐给内部 layout 的边距：避开辉光环带与切角。"""
        m = self.MARGIN + 1
        c = max(self._chamfer, self.MIN_CHAMFER) // 2 if self._active() else 0
        return (m + 2, m + c, m + 2, m + c)

    def set_glow(self, glow: bool) -> None:
        self._glow = glow
        self._sync_animations()
        self.update()

    # ── 动画属性 ─────────────────────────────────────────
    def _get_hud(self) -> float:
        return self._hud_t

    def _set_hud(self, v: float) -> None:
        self._hud_t = float(v)
        self.update(self._edge_region())

    hudProgress = Property(float, _get_hud, _set_hud)

    def _on_breath(self, v) -> None:
        self._breath = math.sin(float(v))
        self.update(self._edge_region())

    # ── 状态 ─────────────────────────────────────────────
    def _active(self) -> bool:
        return self._holo and theme.holo_enabled

    def _sync_animations(self) -> None:
        # PRISM CORE §7：不做持续循环的动态装饰，呼吸辉光默认关闭
        want = BREATH_ENABLED and self._active() and self._glow
        running = self._breath_anim.state() == QVariantAnimation.State.Running
        if want and not running and self.isVisible():
            self._breath_anim.start()
        elif not want and running:
            self._breath_anim.stop()
            self._breath = 0.0

    def _on_style_changed(self) -> None:
        self._cache = None
        self._sync_animations()
        self.update()

    def _edge_region(self) -> QRegion:
        """只刷新外圈环带（辉光 + HUD），避免子控件被连带重绘。"""
        r = self.rect()
        band = self.MARGIN + self.HUD_LEN + 2
        inner = r.adjusted(band, band, -band, -band)
        reg = QRegion(r)
        if inner.isValid():
            reg = reg.subtracted(QRegion(inner))
        return reg

    # ── 几何 ─────────────────────────────────────────────
    def _panel_rect(self) -> QRectF:
        m = self.MARGIN + 0.5
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _chamfer_path(self, r: QRectF, inset: float = 0.0,
                      chamfer: float | None = None) -> QPainterPath:
        """全息面板的填充轮廓：对角切角（左上 + 右下），不带圆角。"""
        r = r.adjusted(inset, inset, -inset, -inset)
        base = self._chamfer if chamfer is None else chamfer
        base = max(base, self.MIN_CHAMFER)
        c = max(0.0, min(base, r.width() / 4, r.height() / 4))
        p = QPainterPath()
        p.moveTo(r.left() + c, r.top())
        p.lineTo(r.right(), r.top())
        p.lineTo(r.right(), r.bottom() - c)
        p.lineTo(r.right() - c, r.bottom())
        p.lineTo(r.left(), r.bottom())
        p.lineTo(r.left(), r.top() + c)
        p.closeSubpath()
        return p

    # ── 事件 ─────────────────────────────────────────────
    def resizeEvent(self, e) -> None:  # noqa: N802
        self._cache = None
        super().resizeEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        self._sync_animations()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        if self._breath_anim.state() == QVariantAnimation.State.Running:
            self._breath_anim.stop()
        super().hideEvent(e)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._animate_hud(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._animate_hud(0.0)
        super().leaveEvent(e)

    def _animate_hud(self, target: float) -> None:
        if not (self._active() and self._hud):
            return
        self._hud_anim.stop()
        self._hud_anim.setStartValue(self._hud_t)
        self._hud_anim.setEndValue(target)
        self._hud_anim.start()

    # ── 绘制 ─────────────────────────────────────────────
    def _build_cache(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._panel_rect()
        path = self._chamfer_path(r)

        # 1) 面板底：深蓝半透明，网格与背后的光带能透上来
        p.fillPath(path, theme.qcolor("panel_fill"))

        # 2) 内部斜向微光：左上略亮、右下略暗，制造一点点体积
        p.save()
        p.setClipPath(path)
        sheen = QLinearGradient(r.topLeft(), r.bottomRight())
        sa = QColor(theme.qcolor("accent"))
        sa.setAlphaF(0.055 if theme.dark else 0.035)
        sb = QColor(theme.qcolor("accent"))
        sb.setAlphaF(0.0)
        sheen.setColorAt(0.0, sa)
        sheen.setColorAt(0.55, sb)
        sheen.setColorAt(1.0, sa)
        p.fillPath(path, QBrush(sheen))
        p.restore()

        # 3) 边框：1px 冰蓝细线 + 外侧 3px 弱辉光（参考图的轮廓就是一条细线）
        p.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPen(_with_alpha(theme.qcolor("light_halo"), 0.45), 3.0)
        halo.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(halo)
        p.drawPath(path)

        frame = QPen(theme.qcolor("panel_frame"), 1.0)
        p.setPen(frame)
        p.drawPath(path)

        # 4) 切角描亮：两条 45° 边用高亮色，标出面板的「光学入口」
        hi = QPen(theme.qcolor("panel_frame_hi"), 1.4)
        hi.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(hi)
        c = max(0.0, min(self._chamfer, r.width() / 3, r.height() / 3))
        p.drawLine(QPointF(r.left() + c, r.top()), QPointF(r.left(), r.top() + c))
        p.drawLine(QPointF(r.right(), r.bottom() - c), QPointF(r.right() - c, r.bottom()))

        # 5) 左缘定位锚点：切角下方一小段高亮，代替整条标题线（不压内容）
        if r.height() > 90:
            anchor = QColor(theme.qcolor("accent"))
            anchor.setAlphaF(0.75)
            p.setPen(QPen(anchor, 1.6))
            y0 = r.top() + c + 8
            p.drawLine(QPointF(r.left(), y0), QPointF(r.left(), min(y0 + 22, r.bottom() - c - 8)))

        # 6) 晶体切面（关键位置才用）
        if self._crystal:
            _draw_facet(p, QPointF(r.left() + c + 10, r.top() + 5.0), 4.4,
                        theme.qcolor("crystal_edge"), theme.qcolor("crystal"))

        # 7) 昔涟点缀（静态晶体切面）
        if self._spark:
            _draw_spark(p, QPointF(r.right() - 14, r.top() + 12), 4.0,
                        theme.qcolor("spark_violet" if self._spark == "violet" else "spark_pearl"))
        p.end()
        return pm

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._active():
            # 回退：普通圆角面板
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QPen(QColor(theme["border"]), 1))
            p.setBrush(QColor(theme["panel_bg"]))
            p.drawRoundedRect(r, self._radius, self._radius)
            return
        if self._cache is None or self._cache.deviceIndependentSize().toSize() != self.size():
            self._cache = self._build_cache()
        p.drawPixmap(0, 0, self._cache)
        r = self._panel_rect()
        # 4) 聚焦外辉光：3 圈递减，裁剪到外框之外
        if self._glow:
            outside = QPainterPath()
            outside.addRect(QRectF(self.rect()))
            path = self._chamfer_path(r)
            outside = outside.subtracted(path)
            p.save()
            p.setClipPath(outside)
            base = theme.qcolor("holo_glow")
            k = 1.0 + self.BREATH_AMP * self._breath
            for i in range(self.GLOW_RINGS):
                p.setPen(QPen(_with_alpha(base, k * (0.9 - 0.3 * i)), 2 * (i + 1)))
                p.drawPath(path)
            p.restore()
        # 6) HUD 角线：静止 40%，悬停 100% 且外扩 2px
        if self._hud:
            col = _with_alpha(theme.qcolor(self._accent),
                              self.HUD_REST + (1 - self.HUD_REST) * self._hud_t)
            p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            o = 2.0 * self._hud_t
            x0, y0 = r.left() - o, r.top() - o
            x1, y1 = r.right() + o, r.bottom() + o
            L = self.HUD_LEN
            for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                                   (x0, y1, 1, -1), (x1, y1, -1, -1)):
                p.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
                p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))


# ─────────────────────────────────────────────────────────────
#  HoloBackdrop —— 中央容器：底色 + 32px 网格（仅深色 + 全息开启）
# ─────────────────────────────────────────────────────────────

class HoloBackdrop(QWidget):
    GRID = 32

    def __init__(self, parent: QWidget | None = None, frame: bool = False,
                 crystals: bool = False) -> None:
        super().__init__(parent)
        self._tile: QPixmap | None = None
        self._frame = frame
        self._crystals = crystals
        _LIVE.add(self)
        _hook_bus()

    def _on_style_changed(self) -> None:
        self._tile = None
        self.update()

    def _build_tile(self) -> QPixmap:
        g = self.GRID
        pm = QPixmap(g, g)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        # 网格线用专用冷色 token（偏蓝），不再借用 text，避免出现偏绿的网格
        p.setPen(QPen(theme.qcolor("grid"), 1))
        p.drawLine(0, 0, g, 0)
        p.drawLine(0, 0, 0, g)
        p.end()
        return pm

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(e.rect(), QColor(theme["window_bg"]))
        # 网格在深浅两套主题下都绘制（浅色用深青、深色用冰蓝），
        # 否则系统为浅色时完全看不到全息空间感。
        if theme.holo_enabled:
            self._paint_light_bands(p)
            if self._tile is None:
                self._tile = self._build_tile()
            p.drawTiledPixmap(e.rect(), self._tile, e.rect().topLeft())
            self._paint_light_field(p)
        if self._frame:
            self._paint_frame(p)
        if self._crystals:
            self._paint_corner_crystals(p)

    def _paint_corner_crystals(self, p: QPainter) -> None:
        """工作区四角的晶体装饰（对应参考图的四角发光晶体）。

        晶体中心压在角落上，一半探出画布，读起来像「从窗口边角长出来的投影棱晶」。
        """
        if not theme.holo_enabled:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w < 360 or h < 240:
            return
        s = min(24.0, min(w, h) * 0.050)
        off = s * 0.45
        edge = theme.qcolor("crystal_edge")
        body = theme.qcolor("crystal")
        for cx, cy in ((off, off),
                       (w - off, off),
                       (off, h - off),
                       (w - off, h - off)):
            _draw_corner_crystal(p, QPointF(cx, cy), s, edge, body)

    def _paint_light_bands(self, p: QPainter) -> None:
        """斜向冷光带：参考图那种「投影光幕」的空间感，透明度极低。"""
        w, h = self.width(), self.height()
        if w < 8 or h < 8:
            return
        band = QLinearGradient(QPointF(w, 0), QPointF(0, h))
        c_on = QColor(theme.qcolor("accent"))
        c_on.setAlphaF(0.035 if theme.dark else 0.05)
        c_off = QColor(theme.qcolor("accent"))
        c_off.setAlpha(0.0)
        band.setColorAt(0.00, c_on)
        band.setColorAt(0.16, c_off)
        band.setColorAt(0.34, c_on)
        band.setColorAt(0.52, c_off)
        band.setColorAt(0.72, c_on)
        band.setColorAt(0.90, c_off)
        p.fillRect(self.rect(), QBrush(band))

    def _paint_light_field(self, p: QPainter) -> None:
        """极弱的蓝青空间光场：让背景有纵深，而不是一张纯色底。"""
        w, h = self.width(), self.height()
        if w < 8 or h < 8:
            return
        grad = QRadialGradient(QPointF(w * 0.42, h * 0.34), max(w, h) * 0.62)
        inner = QColor(theme.qcolor("accent"))
        inner.setAlphaF(0.055)
        mid = QColor(theme.qcolor("accent"))
        mid.setAlphaF(0.018)
        outer = QColor(theme.qcolor("accent"))
        outer.setAlpha(0)
        grad.setColorAt(0.0, inner)
        grad.setColorAt(0.55, mid)
        grad.setColorAt(1.0, outer)
        p.fillRect(self.rect(), QBrush(grad))

    def _paint_frame(self, p: QPainter) -> None:
        """独立窗口的外框：与面板同一套切角细线语言。"""
        if not theme.holo_enabled:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(7.5, 7.5, -7.5, -7.5)
        paint_chamfer_frame(p, r, 22.0)

        # 左缘定位锚点
        anchor = QColor(theme.qcolor("accent"))
        anchor.setAlphaF(0.8)
        p.setPen(QPen(anchor, 1.6))
        y0 = r.top() + 22 + 8
        p.drawLine(QPointF(r.left(), y0), QPointF(r.left(), min(y0 + 24, r.bottom() - 30)))


# ─────────────────────────────────────────────────────────────
#  SparkDot —— 昔涟点缀（四芒星小光点），关闭全息时隐藏
# ─────────────────────────────────────────────────────────────

def _draw_facet(p: QPainter, center: QPointF, s: float,
                edge: QColor, body: QColor) -> None:
    """小型晶体切面：深色半透明体 + 细棱线（静态，不含纹理）。"""
    path = QPainterPath()
    cx, cy = center.x(), center.y()
    path.moveTo(cx, cy - s)
    path.lineTo(cx + s * 0.78, cy - s * 0.18)
    path.lineTo(cx + s * 0.46, cy + s)
    path.lineTo(cx - s * 0.46, cy + s)
    path.lineTo(cx - s * 0.78, cy - s * 0.18)
    path.closeSubpath()
    p.save()
    fill = QColor(body)
    fill.setAlphaF(0.34)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)
    line = QColor(edge)
    line.setAlphaF(0.80)
    p.setPen(QPen(line, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


def _draw_spark(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
    path = QPainterPath()
    s = r * 0.28
    path.moveTo(c.x(), c.y() - r)
    path.quadTo(c.x() + s, c.y() - s, c.x() + r, c.y())
    path.quadTo(c.x() + s, c.y() + s, c.x(), c.y() + r)
    path.quadTo(c.x() - s, c.y() + s, c.x() - r, c.y())
    path.quadTo(c.x() - s, c.y() - s, c.x(), c.y() - r)
    p.save()
    halo = QColor(color)
    halo.setAlphaF(0.18)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(halo)
    p.drawEllipse(c, r * 0.9, r * 0.9)
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


class CrystalMark(QWidget):
    """晶体切面标识（PRISM CORE §2.3：只用于关键位置）。

    深色透明基底 + 清晰几何切面 + 蓝青/淡紫折射高光。
    纯静态绘制，不参与业务逻辑。
    """

    def __init__(self, w: int = 16, h: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        _LIVE.add(self)
        _hook_bus()

    def _on_style_changed(self) -> None:
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, top, bot = w / 2.0, 1.0, h - 1.0
        left, right = 1.0, w - 1.0
        edge = theme.qcolor("crystal_edge")
        body = QColor(theme.qcolor("crystal"))
        body.setAlphaF(0.16)

        # 主切面：上尖、两侧折、下尖
        facet = QPainterPath()
        facet.moveTo(cx, top)
        facet.lineTo(right, h * 0.38)
        facet.lineTo(cx, h * 0.62)
        facet.lineTo(left, h * 0.38)
        facet.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body)
        p.drawPath(facet)

        # 下半部（折射体）
        lower = QPainterPath()
        lower.moveTo(cx, h * 0.62)
        lower.lineTo(right, h * 0.38)
        lower.lineTo(cx, bot)
        lower.lineTo(left, h * 0.38)
        lower.closeSubpath()
        deeper = QColor(body)
        deeper.setAlphaF(0.24)
        p.setBrush(deeper)
        p.drawPath(lower)

        # 棱线与折射高光（细线，低亮度）
        pen = QPen(edge, 1)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(facet)
        hi = QColor(edge)
        hi.setAlphaF(0.45)
        p.setPen(QPen(hi, 1))
        p.drawLine(QPointF(cx, top), QPointF(cx, bot))
        p.drawLine(QPointF(left, h * 0.38), QPointF(right, h * 0.38))


class SparkDot(QWidget):
    """固定 12×12 的点缀光点；tone = "pearl" | "violet"。"""

    def __init__(self, tone: str = "pearl", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = tone
        self.setFixedSize(12, 12)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        _LIVE.add(self)
        _hook_bus()
        self.setVisible(theme.holo_enabled)

    def _on_style_changed(self) -> None:
        self.setVisible(theme.holo_enabled)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        key = "spark_violet" if self._tone == "violet" else "spark_pearl"
        _draw_spark(p, QPointF(6, 6), 5.0, theme.qcolor(key))


__all__ = ["SciFiPanel", "HoloBackdrop", "SparkDot", "CrystalMark", "ScanStrip",
           "apply_holo_enabled"]


class ScanStrip(QWidget):
    """状态栏中的细长扫描光线（PRISM CORE §2.2 / §4.5）。

    只在任务运行期间活动；进度本身仍由数值与标准进度条表达，
    这道光线只是辅助的空间指示，不承载任何状态判断。
    """

    SPEED = 0.014      # 每 33ms 前进的比例
    BAND = 0.26        # 光带宽度占比

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)
        self._pos = -self.BAND
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        _LIVE.add(self)
        _hook_bus()

    def set_active(self, on: bool) -> None:
        on = bool(on) and theme.holo_enabled
        if on == self._active:
            return
        self._active = on
        if on:
            self._pos = -self.BAND
            self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def _tick(self) -> None:
        self._pos += self.SPEED
        if self._pos > 1.0:
            self._pos = -self.BAND
        self.update()

    def _on_style_changed(self) -> None:
        if not theme.holo_enabled:
            self.set_active(False)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self._active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        band = w * self.BAND
        x = self._pos * (w + band) - band
        c = theme.qcolor("accent")
        clear = QColor(c)
        clear.setAlphaF(0.0)
        peak = QColor(c)
        peak.setAlphaF(0.75)
        g = QLinearGradient(x, 0, x + band, 0)
        g.setColorAt(0.0, clear)
        g.setColorAt(0.5, peak)
        g.setColorAt(1.0, clear)
        p.fillRect(QRectF(x, 0, band, h), QBrush(g))

