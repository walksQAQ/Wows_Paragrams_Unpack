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

#: 用户自备立绘的存放目录（相对 exe / 源码根目录），程序不内置任何官方立绘
ART_SUBDIR = "data/skins"
#: 可接受的图片扩展名
ART_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg", ".bmp"}
#: 皮肤未声明候选文件名时的兜底
ART_CANDIDATES: tuple[str, ...] = ("art.png", "art.webp", "art.jpg", "art.jpeg")


def skins_dir() -> Path:
    """立绘目录（不存在则创建）。放在用户数据目录下，随用户自己的图片走。"""
    from utils.path_utils import get_app_dir
    d = get_app_dir() / ART_SUBDIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return d


def skin_art_files() -> tuple[str, ...]:
    """当前皮肤约定的立绘文件名（未启用皮肤时为空）。"""
    if theme.skin is None:
        return ()
    return theme.skin.art_files or ART_CANDIDATES


def resolve_art_path(explicit: str | None = None) -> Path | None:
    """确定要用的立绘文件：配置里指定的优先，否则在 skins 目录里找约定文件名。"""
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            from utils.path_utils import get_app_dir
            p = get_app_dir() / p
        if p.is_file() and p.suffix.lower() in ART_SUFFIXES:
            return p
    d = skins_dir()
    for name in skin_art_files() or ART_CANDIDATES:
        p = d / name
        if p.is_file():
            return p
    return None


# ─────────────────────────────────────────────────────────────
#  几何：莫比乌斯环 / 心 / 水晶
# ─────────────────────────────────────────────────────────────

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
    """工作区背景水印：按当前皮肤的能力位绘制。

    纹样画得足够大（跨越大半个工作区），面板底是半透明的，能透出约两成，
    于是整屏读起来像「浮在这个纹样之上」，而不是角落一个小装饰。
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
    """角色皮肤专属的装饰列：预留插画 / 立绘空间，同时承担皮肤识别。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._art: QPixmap | None = None
        self._art_scaled: QPixmap | None = None
        self._art_key: tuple | None = None
        self._art_file: str = ""
        self.setObjectName("SkinArtSlot")
        self.setFixedWidth(ART_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("")

    # ── 供后续接入正式立绘 ──────────────────────────────
    def set_art(self, pixmap: QPixmap | None) -> None:
        """直接给一张图（None 表示回到占位状态）。"""
        self._art = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._art_scaled: QPixmap | None = None
        self.update()

    def load_art(self, path: str | Path | None) -> bool:
        """从磁盘载入立绘；成功返回 True，失败或路径为空则回到占位状态。"""
        if not path:
            self.set_art(None)
            return False
        pm = QPixmap(str(path))
        if pm.isNull():
            self.set_art(None)
            return False
        self.set_art(pm)
        self._art_file = str(path)
        return True

    @property
    def art_file(self) -> str:
        return getattr(self, "_art_file", "")

    @property
    def has_art(self) -> bool:
        return self._art is not None

    def refresh_theme(self) -> None:
        self._art_scaled = None
        self._art_key = None
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

        if self._art is not None:
            self._paint_art(p, r)
            return
        # 2) 预留区细框 + 四角定位短线
        frame = QColor(theme.qcolor("panel_frame"))
        frame.setAlphaF(0.70)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(frame, 1))
        inner = r.adjusted(10, 10, -10, -10)
        p.drawRect(inner)
        p.setPen(QPen(_pink(0.80), 1.5))
        _draw_corner_ticks(p, inner)

        # 3) 主体：莫比乌斯环（翁法罗斯世界之形，上）+ 心（环心）+ 水晶簇（下）
        cx = r.center().x()
        radius = min(w * 0.34, inner.height() * 0.14)
        ring_cy = inner.top() + inner.height() * 0.28
        _draw_mobius(p, cx, ring_cy, radius, a)
        _draw_heart(p, cx, ring_cy + radius * 0.02, radius * 0.32, a * 1.15)
        _draw_crystals(p, cx, inner.top() + inner.height() * 0.55,
                       min(w * 0.16, 32.0), a)

        # 4) 底部说明：这块是留给立绘的
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        label = QColor(theme.qcolor("text_hint"))
        label.setAlphaF(0.85)
        p.setPen(QPen(label, 1))
        box = QRectF(r.left() + 14, inner.bottom() - 46, w - 28, 40)
        p.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                            | Qt.TextFlag.TextWordWrap),
                   "立绘预留区\n" + (theme.skin.name if theme.skin else "皮肤"))

    def _paint_art(self, p: QPainter, r: QRectF) -> None:
        """把立绘铺满装饰列：按宽度等比放大、底边对齐、顶部渐隐融入背景。

        立绘通常比这根窄条更长，所以放大后从**上方**裁掉多余部分——保留下半截
        （人物主体），顶部淡出到面板底色，读起来像插画从页面下缘浮上来。
        """
        src = self._art
        if src is None:
            return
        w, h = int(r.width()), int(r.height())
        key = (w, h, id(src))
        if self._art_scaled is None or self._art_key != key:
            scaled = src.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
            if scaled.height() > h:
                scaled = scaled.copy(0, scaled.height() - h, scaled.width(), h)
            self._art_scaled = scaled
            self._art_key = key
        pm = self._art_scaled
        x = r.left() + (w - pm.width()) / 2.0
        y = r.bottom() - pm.height()
        p.setOpacity(0.98)
        p.drawPixmap(int(round(x)), int(round(y)), pm)
        p.setOpacity(1.0)

        # 顶部渐隐：让插画边缘不生硬地切断
        fade_h = min(150.0, pm.height() * 0.38)
        fade = QLinearGradient(QPointF(0, y), QPointF(0, y + fade_h))
        base = QColor(theme.qcolor("window_bg"))
        c_opaque = QColor(base)
        c_opaque.setAlphaF(0.92)
        c_clear = QColor(base)
        c_clear.setAlpha(0)
        fade.setColorAt(0.0, c_opaque)
        fade.setColorAt(1.0, c_clear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fade)
        p.drawRect(QRectF(r.left(), y, w, fade_h))

        # 细框压在插画上，保留「这是留出来的位置」的边界感
        frame = QColor(theme.qcolor("panel_frame"))
        frame.setAlphaF(0.70)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(frame, 1))
        inner = r.adjusted(10, 10, -10, -10)
        p.drawRect(inner)
        p.setPen(QPen(_pink(0.80), 1.5))
        _draw_corner_ticks(p, inner)


def _draw_corner_ticks(p: QPainter, r: QRectF) -> None:
    """四角定位短线。"""
    k = 13.0
    for x, y, dx, dy in ((r.left(), r.top(), 1, 1),
                         (r.right(), r.top(), -1, 1),
                         (r.left(), r.bottom(), 1, -1),
                         (r.right(), r.bottom(), -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))


class SkinWatermarkOverlay(QWidget):
    """工作区水印的**顶层叠加层**：画在所有面板之上，极低透明度。

    为什么需要它：面板、卡片、滚动区都有自己的（半透明或实心）底色，
    画在背景层的水印基本会被盖掉。真正的「整屏浮在世界之形上」只能靠
    一层盖在最上面的纸水印。透明度压到刻意很低的水平（近似纸纹），
    并且完全不接收鼠标、不进入 Tab 链，因此不影响任何信息阅读与操作。
    """

    #: 叠加层水印的整体不透明度（很低——只做纸纹，不做图形）
    ALPHA = 0.16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SkinWatermarkOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVisible(False)

    def paintEvent(self, e) -> None:  # noqa: N802
        if not theme.watermark_style:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_skin_watermark(p, QRectF(self.rect()), self.ALPHA)

    def refresh_theme(self) -> None:
        self.setVisible(bool(theme.watermark_style))
        self.update()


def art_slot_visible(window_width: int) -> bool:
    """当前是否应显示装饰列（皮肤能力位 + 窗口宽度双条件）。"""
    return theme.uses_art_slot and window_width >= MIN_WINDOW_WIDTH


__all__ = ["SkinArtSlot", "SkinWatermarkOverlay", "ART_WIDTH", "MIN_WINDOW_WIDTH",
           "art_slot_visible", "paint_skin_watermark", "mobius_ribbon",
           "heart_path", "crystal_shard", "resolve_art_path", "skins_dir",
           "skin_art_files", "ART_SUFFIXES", "ART_SUBDIR", "ART_CANDIDATES"]
