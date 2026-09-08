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
from app.discover.policy import approve_all_applications, load_snapshot, set_approval
from app.discover.report import format_discovery_report
from app.utils.format import format_bytes


def _hostnames(row: dict) -> list[str]:
    names = [str(n) for n in (row.get("hostnames") or []) if n]
    primary = str(row.get("hostname") or "")
    if primary and primary not in names:
        names.insert(0, primary)
    return names


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
            "Automatic Nginx discovery. New applications and new hostname aliases require approval."
        )
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Hostnames", "Type", "Root", "Database", "application_id", "Status"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.discover_btn = QPushButton("DISCOVER SERVER")
        self.discover_btn.setObjectName("primary")
        approve = QPushButton("APPROVE SELECTED")
        approve_all = QPushButton("APPROVE ALL DISCOVERED APPLICATIONS")
        exclude = QPushButton("EXCLUDE SELECTED")
        report = QPushButton("VIEW REPORT")
        buttons.addWidget(self.discover_btn)
        buttons.addWidget(approve)
        buttons.addWidget(approve_all)
        buttons.addWidget(exclude)
        buttons.addWidget(report)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Run DISCOVER SERVER to inventory active Nginx sites.")
        layout.addWidget(self.report)
        approve.clicked.connect(self._approve)
        approve_all.clicked.connect(self._approve_all)
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
            or "NEW HOSTNAME DETECTED" in str(row.get("status") or "")
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
            values = [
                ", ".join(_hostnames(row)),
                str(row.get("type") or ""),
                str(row.get("root") or ""),
                db,
                str(row.get("application_id") or ""),
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
        if excluded:
            row["status"] = "EXCLUDED — UNUSED DEFAULT ROOT" if row.get("unused_default_root") else "EXCLUDED"
        else:
            row["status"] = "READY"
        row["change"] = "excluded" if excluded else "unchanged"
        self.reload(self._config, {"applications": self._rows, "report_text": self.report.toPlainText()})
        action = "excluded from" if excluded else "approved for"
        extra = ""
        if row.get("estimated_bytes"):
            extra = f"\nEstimated size: {format_bytes(int(row['estimated_bytes']))}"
        QMessageBox.information(
            self,
            "DISCOVER SERVER",
            f"{ident} ({', '.join(_hostnames(row))}) {action} the backup set.{extra}\n\n"
            "BACKUP NOW is not run by this approval.",
        )

    def _approve_all(self) -> None:
        if not self._config:
            return
        pending = [
            row
            for row in self._rows
            if row.get("change") != "removed"
            and not row.get("excluded")
            and not row.get("unused_default_root")
            and "UNUSED DEFAULT ROOT" not in str(row.get("status") or "")
            and not row.get("included")
        ]
        if not pending:
            QMessageBox.information(self, "DISCOVER SERVER", "There are no applications waiting for approval.")
            return
        names = "\n".join(
            f"  {row.get('application_id')}  ({', '.join(_hostnames(row))})" for row in pending
        )
        answer = QMessageBox.question(
            self,
            "APPROVE ALL DISCOVERED APPLICATIONS",
            "Approve these applications for backup?\n\n"
            f"{names}\n\n"
            "Unused default roots stay excluded. BACKUP NOW is not run.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        approve_all_applications(self._config.backup_destination, self._rows)
        ids = {str(row.get("application_id") or "") for row in pending}
        for row in self._rows:
            if str(row.get("application_id") or "") in ids:
                row["included"] = True
                row["excluded"] = False
                row["status"] = "READY"
                row["change"] = "unchanged"
        self.reload(self._config, {"applications": self._rows, "report_text": format_discovery_report({"applications": self._rows})})
        QMessageBox.information(
            self,
            "DISCOVER SERVER",
            f"Approved {len(pending)} application(s). Unused default roots were not approved.\n\n"
            "BACKUP NOW is not run by this approval.",
        )

    def _show_report(self) -> None:
        text = self.report.toPlainText() or "Run DISCOVER SERVER first."
        QMessageBox.information(self, "DISCOVERY REPORT", text)
