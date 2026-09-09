from __future__ import annotations

from typing import Any


def tray_color(indicator: str) -> tuple[int, int, int]:
    return {
        "green": (22, 163, 74),
        "yellow": (202, 138, 4),
        "red": (220, 38, 38),
        "warning": (217, 119, 6),
    }.get(indicator, (100, 116, 139))


def make_icon(indicator: str) -> Any:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r, g, b = tray_color(indicator)
    painter.setBrush(QColor(r, g, b))
    painter.setPen(QColor(15, 23, 42))
    painter.drawEllipse(2, 2, 28, 28)
    painter.end()
    return QIcon(pixmap)
