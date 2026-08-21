"""UI 窗口工具函数（Phase 4 U4 收敛：懒创建单实例+居中+显示样板）。"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


def center_on_screen(dialog: QWidget, relative_to: QWidget | None = None) -> None:
    """将对话框居中到父窗口，无父窗口时居中到主屏幕。"""
    if relative_to is not None and relative_to.isVisible():
        geo = relative_to.frameGeometry()
        x = geo.x() + (geo.width() - dialog.width()) // 2
        y = geo.y() + (geo.height() - dialog.height()) // 2
        dialog.move(max(x, 0), max(y, 0))
        return
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        dialog.move(geo.x() + (geo.width() - dialog.width()) // 2,
                    geo.y() + (geo.height() - dialog.height()) // 2)


def ensure_dialog_shown(parent: object, attr: str, factory, center_parent=None) -> QWidget:
    """懒创建/居中/显示对话框单例（替代 5 处样板）。

    parent: 持有单例的父对象（如 self）
    attr: 单例属性名（如 "_assets_viewer"）
    factory: 无参工厂函数，返回 QWidget 对话框
    center_parent: 居中参考窗口（None 则居中到主屏幕）
    返回对话框实例。
    """
    dlg = getattr(parent, attr, None)
    if dlg is None:
        dlg = factory()
        setattr(parent, attr, dlg)
        center_on_screen(dlg, center_parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg