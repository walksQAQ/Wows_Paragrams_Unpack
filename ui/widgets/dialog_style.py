"""子窗口的统一全息外观：HoloDialog 基类 + 统一 QSS。

设计意图（PRISM CORE §2.2 / §12）：
  所有可从主窗口引出的 QDialog 共享同一套视觉语言——近黑蓝底、
  断续结构线、顶部光学定位光段、低圆角分组框——而不是各写各的样式。

只影响绘制，不改变任何业务逻辑或控件行为。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QMainWindow, QVBoxLayout

from utils.theme import theme
from ui.widgets.scifi_panel import (
    HoloBackdrop, SciFiPanel, frame_strokes, paint_frame_strokes, _LIVE,
)

# 独立主窗口（non-modal 浏览器）只需覆盖与全局 QSS 不同之处：
# 树/文本区嵌在全息面板内部，去掉全局的 1px 框；文本区用等宽字体。
# 其余（工具栏、输入框、滚动条、分割条…）全部复用 resources/styles/main.qss，
# 避免各窗口重复定义颜色与样式。
WINDOW_QSS = """
QTreeWidget { border: none; border-radius: 0px; }
QTreeWidget::item { padding: 2px 3px; border-left: 2px solid transparent; }
QTreeWidget::item:selected { background-color: @hover_bg@; color: @text@;
                             border-left: 2px solid @accent@; }
QTextEdit { background-color: transparent; border: none; padding: 8px;
            font-family: "Cascadia Code", Consolas, "Courier New", monospace; font-size: 12px; }
QToolBar QLabel#info { color: @text_muted@; padding: 0 8px; }
QToolBar QLabel#source { color: @text_hint@; padding: 0 10px; font-size: 12px; }
"""

DIALOG_QSS = """
QDialog {
    background: @window_bg@;
    color: @text@;
}
/* 对话框按钮：方角细光线框，与主界面的斜切薄片同一硬度 */
QDialog QPushButton {
    background: transparent;
    border: 1px solid @metal_edge@;
    border-radius: 0px;
    padding: 5px 16px;
    color: @text@;
}
QDialog QPushButton:hover {
    border-color: @accent@;
    color: @accent@;
    background: @hover_bg@;
}
QDialog QPushButton:default {
    border-color: @accent@;
    color: @accent@;
}
QDialog QPushButton:pressed {
    background: @accent@;
    color: @on_accent@;
    border-color: @accent@;
}
QDialog QGroupBox {
    border: 1px solid @border@;
    border-radius: 0px;
    margin-top: 12px;
    padding-top: 9px;
}
QDialog QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 6px;
    color: @text_muted@;
    background-color: @window_bg@;
}
"""


def _with_alpha(c: QColor, factor: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, c.alphaF() * factor)))
    return out


class HoloDialog(QDialog):
    """带光学边框的子窗口基类。

    在窗口内侧 6px 处绘制「断续结构线 + 顶部/左侧定位光段」，与主窗口的
    SciFiPanel 保持同一视觉语言。绘制位于窗口自身表面，不占用布局、不遮挡内容。
    """

    INSET = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        theme.bind(self, DIALOG_QSS)
        _LIVE.add(self)

    def _on_style_changed(self) -> None:
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if not theme.holo_enabled:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(7.5, 7.5, -7.5, -7.5)
        strokes = frame_strokes(r, chamfer=18.0)
        paint_frame_strokes(p, strokes, halo_width=5.0, core_width=1.6)


__all__ = ["HoloDialog", "HoloWindow", "DIALOG_QSS", "WINDOW_QSS"]


class HoloWindow(QMainWindow):
    """独立主窗口（非模态浏览器）的统一外观。

    自动把原有的中央控件包进 HoloBackdrop（窗口底色 + 32px 网格 + 光学边框），
    外圈留 12px 避开边框，内容再放进切角全息面板，与主窗口的工作区同一语言。

    只改呈现层：调用方仍然照旧 setCentralWidget(内容)，内部完成包装，
    不改变任何布局层级关系或信号连接。
    """

    WRAP_MARGIN = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._wrapped = False
        theme.bind(self, WINDOW_QSS)
        _LIVE.add(self)

    def _on_style_changed(self) -> None:
        central = self.centralWidget()
        if central is not None:
            central.update()
        self.update()

    def setCentralWidget(self, widget) -> None:  # noqa: N802
        if widget is None or self._wrapped:
            super().setCentralWidget(widget)
            return
        holder = HoloBackdrop(self, frame=True)
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(self.WRAP_MARGIN, self.WRAP_MARGIN,
                                 self.WRAP_MARGIN, self.WRAP_MARGIN)
        outer.setSpacing(0)

        panel = SciFiPanel(chamfer=14, accent="holo_ice", spark="pearl")
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(*panel.content_margins())
        inner.setSpacing(0)
        widget.setParent(panel)
        inner.addWidget(widget)

        outer.addWidget(panel)
        super().setCentralWidget(holder)
        self._wrapped = True
