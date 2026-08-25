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


def prompt_schema_mismatch(parent: QWidget | None, server: str,
                           mismatches: list[dict]) -> None:
    """弹出数据库结构版本不匹配提示。

    用于「选择服务器」或「应用启动」时，检测到某服务器对应的两个数据库
    （game_data.db + assets_data.db）schema 版本与当前程序不一致时，向用户弹窗提醒。

    mismatches: check_schema_mismatches 返回的列表，元素含 db/found/expected。
    """
    from PySide6.QtWidgets import QMessageBox

    lines = "\n".join(
        f"• {m['db']}：{m['found']} → {m['expected']}"
        for m in mismatches)
    if all(m["found"] < m["expected"] for m in mismatches):
        detail = (
            "以下数据库的 schema 版本落后，数据可能已过时：\n\n"
            f"{lines}\n\n"
            "重新加载数据时会按当前结构重建（旧数据将被清空），请重新加载以确保兼容。")
    else:
        detail = (
            "以下数据库的 schema 版本与当前程序不一致：\n\n"
            f"{lines}\n\n"
            "数据可能不兼容，建议重新加载数据。")
    box = QMessageBox(parent)
    box.setWindowTitle("数据库结构版本不匹配")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(f"检测到 {server} 服务器的数据库结构版本与当前程序不匹配。")
    box.setInformativeText(detail)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()