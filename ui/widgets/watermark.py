"""用于界面和导出图片的轻量数据溯源水印。"""

from __future__ import annotations

import getpass
import sqlite3
import socket
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap

from utils.theme import theme

#: 水印整体透明度（0–255）：要求「存在但几乎不干扰阅读」
WATERMARK_ALPHA = 72
#: 水印字号（px）：与界面右下角信息带一致
WATERMARK_PX = 8
#: 水印距边缘留白（px）
WATERMARK_MARGIN = 8.0
#: 水印整体高度（px）
WATERMARK_HEIGHT = 16.0


def _identity() -> str:
    """返回可读且不包含路径的本机身份信息。"""
    try:
        host = socket.gethostname().strip()
    except OSError:
        host = ""
    try:
        user = getpass.getuser().strip()
    except (ImportError, OSError):
        user = ""
    return "/".join(part for part in (host, user) if part) or "local"


def watermark_text(version_code: str | None = None) -> str:
    """生成当前时刻的水印文本。"""
    if version_code is None:
        try:
            from services.database_service import get_db
            version_code = get_db().get_latest_version_code() or ""
        except (OSError, RuntimeError, sqlite3.Error):
            version_code = ""
    version = version_code or "no-data"
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    return f"DB {version} | {_identity()} | {now}"


def watermark_label_qss() -> str:
    """右下角信息带的样式（透明度与导出水印保持一致）。"""
    c = theme.qcolor("text_hint")
    return (
        "QLabel {"
        " background: transparent;"
        f" color: rgba({c.red()}, {c.green()}, {c.blue()}, {WATERMARK_ALPHA});"
        ' font-family: "Consolas", "Courier New", monospace;'
        f" font-size: {WATERMARK_PX}px;"
        " }"
    )


def paint_watermark(painter: QPainter, rect: QRectF, version_code: str | None = None) -> None:
    """在目标右下角绘制低干扰水印。"""
    if rect.width() < 160 or rect.height() < 20:
        return
    painter.save()
    font = QFont("Consolas", WATERMARK_PX)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(WATERMARK_PX)
    painter.setFont(font)
    color = theme.qcolor("text_hint")
    color.setAlpha(WATERMARK_ALPHA)
    painter.setPen(color)
    painter.drawText(
        QRectF(rect.left() + WATERMARK_MARGIN,
               rect.bottom() - WATERMARK_HEIGHT - 3.0,
               rect.width() - WATERMARK_MARGIN * 2, WATERMARK_HEIGHT),
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        watermark_text(version_code),
    )
    painter.restore()


def watermark_pixmap(pixmap: QPixmap, version_code: str | None = None) -> QPixmap:
    """返回带水印副本，不修改调用方持有的原图。"""
    if pixmap is None or pixmap.isNull():
        return pixmap
    result = QPixmap(pixmap)
    painter = QPainter(result)
    paint_watermark(painter, QRectF(result.rect()), version_code)
    painter.end()
    return result
