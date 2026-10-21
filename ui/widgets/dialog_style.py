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
    HoloBackdrop, SciFiPanel, paint_chamfer_frame, _LIVE,
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
/* 按钮样式不在这里重复定义：对话框继承 resources/styles/main.qss 里那唯一一条
   QPushButton 规则，保证「保存/取消/关闭/浏览」与主界面普通按钮完全一致。 */
QDialog QGroupBox {
    border: 1px solid @border_soft@;
    border-radius: 0px;
    margin-top: 12px;
    padding-top: 9px;
}
QDialog QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 6px;
    color: @accent@;
    background-color: @window_bg@;
}
"""

#: 主操作按钮（对话框的「确定/保存」、工具的主要动作）。
#: 普通按钮 = 全局 QPushButton 规则；这个变体只加信号色描边，不做整块填充。
PRIMARY_BTN_QSS = """
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 @metal_sheen_a@, stop:0.55 @metal_glow@,
                stop:1 @metal_sheen_a@);
    color: @accent@;
    border: 1px solid @accent@;
    border-radius: 0px;
    padding: 5px 14px;
    min-height: 16px;
    font-weight: bold;
}
QPushButton:hover {
    background: @hover_bg@;
    color: @accent_hi@;
    border-color: @accent_hi@;
}
QPushButton:pressed {
    background: @inset@;
    color: @accent_hi@;
    border-color: @accent@;
}
QPushButton:disabled {
    background: @panel_bg@;
    color: @text_hint@;
    border-color: @border@;
}
"""


def _with_alpha(c: QColor, factor: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, c.alphaF() * factor)))
    return out


class HoloDialog(QDialog):
    """带光学边框的子窗口基类。

    在窗口内侧绘制「切角细线 + 弱辉光」，与主窗口的 SciFiPanel 保持同一视觉语言。
    绘制位于窗口自身表面，不占用布局、不遮挡内容；但由于切角是斜的，内容区的
    四角必须退到斜线内侧，否则控件边框/文字会从切掉的那个角里穿出去——因此
    这里在首次显示时把顶层 layout 的边距抬到 :meth:`content_inset`。
    """

    FRAME_INSET = 7
    FRAME_CHAMFER = 14
    #: 内容与框线之间的最小留白（保证四角都在切角轮廓内）
    CONTENT_INSET = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        theme.bind(self, DIALOG_QSS)
        _LIVE.add(self)

    def _on_style_changed(self) -> None:
        self.update()

    def _ensure_content_inset(self) -> None:
        """把顶层 layout 的边距抬到安全值（只增不减，避免抖动）。"""
        lay = self.layout()
        if lay is None:
            return
        m = lay.contentsMargins()
        need = self.CONTENT_INSET if theme.holo_enabled else 10
        new = (max(m.left(), need), max(m.top(), need),
               max(m.right(), need), max(m.bottom(), need))
        if new != (m.left(), m.top(), m.right(), m.bottom()):
            lay.setContentsMargins(*new)

    def showEvent(self, e) -> None:  # noqa: N802
        self._ensure_content_inset()
        super().showEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if not theme.holo_enabled:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(
            self.FRAME_INSET + 0.5, self.FRAME_INSET + 0.5,
            -(self.FRAME_INSET + 0.5), -(self.FRAME_INSET + 0.5))
        paint_chamfer_frame(p, r, self.FRAME_CHAMFER)


__all__ = ["HoloDialog", "HoloWindow", "DIALOG_QSS", "WINDOW_QSS", "PRIMARY_BTN_QSS"]


class HoloWindow(QMainWindow):
    """独立主窗口（非模态浏览器）的统一外观。

    自动把原有的中央控件包进 HoloBackdrop（窗口底色 + 32px 网格 + 光学边框），
    外圈留出足够边距避开外框的切角，内容再放进切角全息面板，与主窗口的工作区
    同一语言。

    只改呈现层：调用方仍然照旧 setCentralWidget(内容)，内部完成包装，
    不改变任何布局层级关系或信号连接。
    """

    #: 外框（HoloBackdrop 绘制）与内层面板之间的安全距离。
    #: 必须 >= 外框切角的一半 + 框线位置，否则内层面板的角会穿出外框的斜角。
    WRAP_MARGIN = 16

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
