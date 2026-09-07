from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 700; font-size: 14px; color: #10233a;")
        layout.addWidget(heading)
        self.body = QGridLayout()
        layout.addLayout(self.body)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for index, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setStyleSheet("color: #5b6775;")
            val = QLabel(value)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setStyleSheet("font-weight: 600;")
            self.body.addWidget(key, index, 0)
            self.body.addWidget(val, index, 1)
