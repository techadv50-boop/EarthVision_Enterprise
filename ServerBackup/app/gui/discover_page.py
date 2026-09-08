from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import AppConfig
from app.discover.policy import load_snapshot, set_approval
from app.discover.report import format_discovery_report
from app.utils.format import format_bytes


class DiscoverPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        self._rows: list[dict] = []
        self._result: dict = {}
        layout = QVBoxLayout(self)
        heading = QLabel("DISCOVERED APPLICATIONS")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.summary = QLabel(
            "Automatic Nginx discovery. New sites require approval before they join the backup set."
        )
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Hostname", "Type", "Root", "Database", "Persistent Data", "Status"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.discover_btn = QPushButton("DISCOVER SERVER")
        self.discover_btn.setObjectName("primary")
        approve = QPushButton("APPROVE SELECTED")
        exclude = QPushButton("EXCLUDE SELECTED")
        report = QPushButton("VIEW REPORT")
        buttons.addWidget(self.discover_btn)
        buttons.addWidget(approve)
        buttons.addWidget(exclude)
        buttons.addWidget(report)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Run DISCOVER SERVER to inventory active Nginx sites.")
        layout.addWidget(self.report)
        approve.clicked.connect(self._approve)
        exclude.clicked.connect(self._exclude)
        report.clicked.connect(self._show_report)

    def reload(self, config: AppConfig, result: dict | None = None) -> None:
        self._config = config
        if result:
            self._result = result
            self._rows = list(result.get("applications") or [])
        else:
            snap = load_snapshot(config.backup_destination)
            self._rows = list(snap.get("applications") or [])
            self._result = snap
        live = [row for row in self._rows if row.get("change") != "removed"]
        review = [
            row
            for row in self._rows
            if "REVIEW" in str(row.get("status") or "")
            or "REQUIRES APPROVAL" in str(row.get("status") or "")
            or "NEW SITE DETECTED" in str(row.get("status") or "")
        ]
        removed = [row for row in self._rows if row.get("change") == "removed"]
        approved = [row for row in live if row.get("included")]
        self.summary.setText(
            f"Total discovered applications: {len(live)}    "
            f"Approved: {len(approved)}    "
            f"Needs review: {len(review)}    "
            f"Removed since last run: {len(removed)}"
        )
        self.table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            db = ""
            if row.get("database_type") or row.get("database_name"):
                db = f"{row.get('database_type') or ''} {row.get('database_name') or ''}".strip()
            persist = ", ".join(row.get("persistent_data_paths") or [])
            values = [
                str(row.get("hostname") or ""),
                str(row.get("type") or ""),
                str(row.get("root") or ""),
                db,
                persist,
                str(row.get("status") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(index, col, item)
        if result and result.get("report_text"):
            self.report.setPlainText(str(result["report_text"]))
        elif self._rows:
            self.report.setPlainText(format_discovery_report({"applications": self._rows, "hostname": "local snapshot"}))

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _approve(self) -> None:
        self._set_selected(approved=True, excluded=False)

    def _exclude(self) -> None:
        self._set_selected(approved=False, excluded=True)

    def _set_selected(self, *, approved: bool, excluded: bool) -> None:
        if not self._config:
            return
        row = self._selected()
        if not row:
            QMessageBox.information(self, "DISCOVER SERVER", "Select an application first.")
            return
        ident = str(row.get("application_id") or row.get("hostname") or "")
        set_approval(self._config.backup_destination, ident, approved=approved, excluded=excluded)
        row["included"] = approved and not excluded
        row["excluded"] = excluded
        row["status"] = "EXCLUDED" if excluded else "READY"
        row["change"] = "excluded" if excluded else "unchanged"
        self.reload(self._config, {"applications": self._rows, "report_text": self.report.toPlainText()})
        action = "excluded from" if excluded else "approved for"
        extra = ""
        if row.get("estimated_bytes"):
            extra = f"\nEstimated size: {format_bytes(int(row['estimated_bytes']))}"
        QMessageBox.information(
            self,
            "DISCOVER SERVER",
            f"{row.get('hostname')} {action} the backup set.{extra}\n\n"
            "BACKUP NOW is not changed in this discovery build.",
        )

    def _show_report(self) -> None:
        text = self.report.toPlainText() or "Run DISCOVER SERVER first."
        QMessageBox.information(self, "DISCOVERY REPORT", text)
