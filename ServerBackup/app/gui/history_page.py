from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backup.checksum import sha256_file
from app.backup.retention import list_history
from app.backup.verify import ArchiveIntegrityError, verify_archive
from app.config.schema import AppConfig
from app.utils.format import format_bytes, format_duration


class HistoryPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        self._rows: list[dict] = []
        layout = QVBoxLayout(self)
        heading = QLabel("Backup History")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date/Time", "Status", "Size", "Duration", "SHA-256 / Location"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        details = QPushButton("View details")
        details.clicked.connect(self._details)
        verify = QPushButton("Verify integrity")
        verify.clicked.connect(self._verify)
        open_folder = QPushButton("Open backup folder")
        open_folder.clicked.connect(self._open)
        restore = QPushButton("Restore…")
        restore.clicked.connect(self._restore)
        buttons.addWidget(details)
        buttons.addWidget(verify)
        buttons.addWidget(open_folder)
        buttons.addWidget(restore)
        buttons.addStretch()
        layout.addLayout(buttons)

    def reload(self, config: AppConfig) -> None:
        self._config = config
        self._rows = list_history(config.backup_destination)
        self.table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            size = row.get("size")
            size_text = format_bytes(size) if isinstance(size, (int, float)) else "—"
            sha = row.get("sha256") or "—"
            location = row.get("location") or ""
            values = [
                str(row.get("timestamp") or row.get("id")),
                str(row.get("status") or "UNKNOWN"),
                size_text,
                format_duration(row.get("duration")),
                f"{sha}\n{location}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 1:
                    status = str(row.get("status") or "")
                    if status == "SUCCESS":
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    elif status in {"FAILED", "CANCELLED"}:
                        item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(index, col, item)
        self.table.resizeRowsToContents()

    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Backup history", "Select a backup first.")
            return None
        return self._rows[rows[0].row()]

    def _details(self) -> None:
        row = self._selected()
        if not row:
            return
        info = row.get("info") or row
        lines = [f"{key}: {value}" for key, value in info.items() if key != "info"]
        QMessageBox.information(self, "Backup details", "\n".join(lines) or str(row))

    def _verify(self) -> None:
        row = self._selected()
        if not row:
            return
        if row.get("status") != "SUCCESS":
            QMessageBox.warning(self, "Integrity", "Only successful backups can be verified.")
            return
        archive = Path(row["location"]) / "server-backup.tar.gz"
        try:
            verify_archive(archive)
            digest = sha256_file(archive)
        except (ArchiveIntegrityError, OSError) as exc:
            QMessageBox.critical(self, "Integrity", str(exc))
            return
        expected = row.get("sha256")
        if expected and expected != digest:
            QMessageBox.critical(self, "Integrity", "SHA-256 mismatch. This backup must not be trusted.")
            return
        QMessageBox.information(self, "Integrity", f"Archive OK.\nSHA-256:\n{digest}")

    def _open(self) -> None:
        row = self._selected()
        if not row:
            return
        path = row.get("location")
        if not path:
            return
        self.window().open_path(path)  # type: ignore[attr-defined]

    def _restore(self) -> None:
        row = self._selected()
        if not row:
            return
        if row.get("status") != "SUCCESS":
            QMessageBox.warning(self, "Restore", "Only a successful backup can be restored.")
            return
        window = self.window()
        if hasattr(window, "open_restore"):
            window.open_restore(row["location"])
