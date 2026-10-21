"""角色主题的**立绘预留位**。

这里只负责「把位置留出来」，不绘制任何具象内容：

* 宽度固定，随窗口宽度自动显隐（太窄时收起，避免挤压详情面板）；
* 画一圈极淡的虚线框 + 四角定位短线 + 一行提示文字，告诉使用者这块是留给立绘的；
* 背景只铺一层几乎看不见的竖向渐变，保持与整体主题同色系；
* 完全不接收鼠标、不进 Tab 链，纯装饰。

后续要放立绘时，只需在这里加一个 `QPixmap` 成员并在 `paintEvent` 里
`drawPixmap`，或者直接把本控件替换成 `QLabel`——主窗口那边不用动。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from utils.theme import theme

#: 预留位宽度（px）
ART_WIDTH = 200
#: 窗口窄于此宽度时自动收起
MIN_WINDOW_WIDTH = 1500


class SkinArtSlot(QWidget):
    """角色主题右侧的立绘预留位（纯占位，不画具体图形）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SkinArtSlot")
        self.setFixedWidth(ART_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("立绘预留位：可在此放入角色插画（自行准备素材）")

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        w, h = r.width(), r.height()
        if w < 20 or h < 60:
            return

        # 1) 竖向微渐变：与整体底同色系，几乎不可见，只为不显得是一块死白
        grad = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
        top = QColor(theme.qcolor("accent"))
        top.setAlphaF(0.045 if theme.holo_enabled else 0.02)
        clear = QColor(theme.qcolor("accent"))
        clear.setAlphaF(0.0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(0.55, clear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(r)

        # 2) 虚线预留框 + 四角定位短线
        inner = r.adjusted(10, 10, -10, -10)
        frame = QColor(theme.qcolor("panel_frame"))
        frame.setAlphaF(0.55)
        pen = QPen(frame, 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 5])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawRect(inner)

        tick = QColor(theme.qcolor("accent"))
        tick.setAlphaF(0.55)
        p.setPen(QPen(tick, 1.4))
        k = 12.0
        for x, y, dx, dy in ((inner.left(), inner.top(), 1, 1),
                             (inner.right(), inner.top(), -1, 1),
                             (inner.left(), inner.bottom(), 1, -1),
                             (inner.right(), inner.bottom(), -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))

        # 3) 提示文字（居中偏下，避免以后贴图时挡住人物）
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        label = QColor(theme.qcolor("text_hint"))
        label.setAlphaF(0.75)
        p.setPen(QPen(label, 1))
        box = QRectF(inner.left() + 12, inner.bottom() - 52, inner.width() - 24, 44)
        p.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
                            | Qt.TextFlag.TextWordWrap), "立绘预留位\n自行准备素材")


def art_slot_visible(window_width: int) -> bool:
    """当前是否应显示立绘预留位（皮肤具备该能力位 + 窗口够宽）。"""
    return theme.uses_art_slot and window_width >= MIN_WINDOW_WIDTH


__all__ = ["SkinArtSlot", "ART_WIDTH", "MIN_WINDOW_WIDTH", "art_slot_visible"]
