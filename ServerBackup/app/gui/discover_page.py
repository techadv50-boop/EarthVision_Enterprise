from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import AppConfig
from app.discover.approval import (
    application_id,
    approve_selected_applications,
    format_application_approval_block,
    hostnames,
    mark_row_approved,
    split_approval_applications,
)
from app.discover.policy import (
    acknowledge_removed_applications,
    apply_database_policy,
    apply_policy,
    approve_all_applications,
    load_snapshot,
    save_snapshot,
    set_database_decision,
    snapshot_application_row,
)


class _ApplicationRow(QFrame):
    def __init__(self, app: dict, *, checkable: bool, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.setObjectName("card")
        layout = QHBoxLayout(self)
        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("applicationCheck")
        self.checkbox.setVisible(checkable)
        self.checkbox.setEnabled(checkable)
        self.checkbox.setProperty("application_id", application_id(app))
        if checkable and not app.get("included"):
            self.checkbox.setChecked(False)
        elif checkable:
            self.checkbox.setChecked(True)
        layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignTop)
        body = QLabel(format_application_approval_block(app))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setObjectName("applicationBlock")
        layout.addWidget(body, 1)

    def is_checked(self) -> bool:
        return bool(self.checkbox.isVisible() and self.checkbox.isEnabled() and self.checkbox.isChecked())


class _DatabaseRow(QFrame):
    def __init__(self, row: dict, parent=None) -> None:
        super().__init__(parent)
        self.row = row
        self.setObjectName("card")
        layout = QHBoxLayout(self)
        body = QLabel(_format_database_block(row))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setObjectName("databaseBlock")
        layout.addWidget(body, 1)
        buttons = QVBoxLayout()
        include = QPushButton("DUMP AS UNASSIGNED")
        include.setObjectName("includeUnassigned")
        include.setProperty("database_name", str(row.get("name") or ""))
        exclude = QPushButton("EXCLUDE FROM BACKUP")
        exclude.setObjectName("excludeDatabase")
        exclude.setProperty("database_name", str(row.get("name") or ""))
        buttons.addWidget(include)
        buttons.addWidget(exclude)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.include_btn = include
        self.exclude_btn = exclude


def _format_database_block(row: dict) -> str:
    size = int(row.get("size_bytes") or 0)
    tables = row.get("table_count")
    lines = [
        str(row.get("name") or "—"),
        f"    {row.get('status') or 'UNASSOCIATED DATABASE — REQUIRES REVIEW'}",
        f"    tables: {tables if tables is not None else '—'}    size_bytes: {size}",
    ]
    if row.get("row_count") is not None:
        lines.append(f"    rows: {row.get('row_count')}")
    if row.get("reason"):
        lines.append(f"    {row.get('reason')}")
    return "\n".join(lines)


class DiscoverPage(QWidget):
    """Application Discovery/Approval view opened by DISCOVER SERVER."""

    cancelled = Signal()
    approved = Signal(int)
    rediscover_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        self._rows: list[dict] = []
        self._databases: list[dict] = []
        self._result: dict = {}
        self._pending_rows: list[_ApplicationRow] = []
        self._excluded_rows: list[_ApplicationRow] = []
        self._database_rows: list[_DatabaseRow] = []
        layout = QVBoxLayout(self)
        heading = QLabel("APPLICATION DISCOVERY / APPROVAL")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.summary = QLabel(
            "Check the applications to include in the backup set. "
            "Unused default roots stay excluded unless you override that exclusion."
        )
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.busy = QLabel("")
        self.busy.setObjectName("subtitle")
        self.busy.setWordWrap(True)
        layout.addWidget(self.busy)
        layout.addLayout(self._button_row())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("approvalScroll")
        inner = QWidget()
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.override_excluded = QCheckBox(
            "Override exclusion and include unused default roots (not recommended)"
        )
        self.override_excluded.setObjectName("overrideExcluded")
        self.override_excluded.setVisible(False)
        layout.addWidget(self.override_excluded)
        layout.addLayout(self._button_row(bottom=True))

    def _button_row(self, *, bottom: bool = False) -> QHBoxLayout:
        buttons = QHBoxLayout()
        approve = QPushButton("APPROVE SELECTED")
        approve.setObjectName("approveSelectedBottom" if bottom else "approveSelected")
        approve_all = QPushButton("APPROVE ALL DISCOVERED")
        approve_all.setObjectName("approveAllBottom" if bottom else "approveAll")
        cancel = QPushButton("CANCEL")
        cancel.setObjectName("cancelApprovalBottom" if bottom else "cancelApproval")
        buttons.addWidget(approve)
        buttons.addWidget(approve_all)
        buttons.addWidget(cancel)
        buttons.addStretch()
        approve.clicked.connect(self._approve_selected)
        approve_all.clicked.connect(self._approve_all)
        cancel.clicked.connect(self.cancelled.emit)
        if not bottom:
            self.approve_selected_btn = approve
            self.approve_all_btn = approve_all
            self.cancel_btn = cancel
            rediscover = QPushButton("RE-RUN DISCOVERY")
            rediscover.setObjectName("rediscover")
            rediscover.clicked.connect(self.rediscover_requested.emit)
            buttons.addWidget(rediscover)
            self.rediscover_btn = rediscover
        return buttons

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy.setText(message if busy else "")
        enabled = not busy
        self.approve_selected_btn.setEnabled(enabled)
        self.approve_all_btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(True)

    def reload(self, config: AppConfig, result: dict | None = None) -> None:
        self._config = config
        if result:
            self._result = result
            self._rows = list(result.get("applications") or [])
            dest = config.backup_destination
            self._databases = apply_database_policy(list(result.get("database_inventory") or []), dest)
        else:
            snap = load_snapshot(config.backup_destination)
            self._rows = apply_policy(list(snap.get("applications") or []), config.backup_destination)
            self._databases = apply_database_policy(list(snap.get("database_inventory") or []), config.backup_destination)
            self._result = {**snap, "applications": self._rows, "database_inventory": self._databases}
        self._render()

    def _clear_list(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._pending_rows = []
        self._excluded_rows = []
        self._database_rows = []

    def _section(self, title: str) -> QLabel:
        label = QLabel(title)
        label.setStyleSheet("font-weight: 700; font-size: 14px; color: #10233a; padding-top: 8px;")
        return label

    def _render(self) -> None:
        pending, approved, excluded = split_approval_applications(self._rows)
        removed = [
            row
            for row in self._rows
            if row.get("change") == "removed" and "ACKNOWLEDGED" not in str(row.get("status") or "")
        ]
        unassociated = [
            row
            for row in self._databases
            if not row.get("system") and "UNASSOCIATED" in str(row.get("status") or "")
        ]
        leftover_dbs = [
            row
            for row in self._databases
            if not row.get("system") and "MIGRATION LEFTOVER" in str(row.get("status") or "")
        ]
        self.summary.setText(
            f"Pending approval: {len(pending)}    "
            f"Approved: {len(approved)}    "
            f"Excluded: {len(excluded)}    "
            f"Unassociated databases: {len(unassociated)}    "
            "BACKUP NOW is not started from this page."
        )
        self._clear_list()
        if pending:
            self._list.addWidget(self._section("APPLICATIONS"))
            for app in pending:
                row = _ApplicationRow(app, checkable=True)
                self._pending_rows.append(row)
                self._list.addWidget(row)
        if approved:
            self._list.addWidget(self._section("ALREADY APPROVED"))
            for app in approved:
                row = _ApplicationRow(app, checkable=True)
                row.checkbox.setChecked(True)
                self._list.addWidget(row)
        self._list.addWidget(self._section("[EXCLUDED]"))
        if excluded:
            for app in excluded:
                row = _ApplicationRow(app, checkable=False)
                self._excluded_rows.append(row)
                self._list.addWidget(row)
        else:
            empty = QLabel("    (none)")
            empty.setObjectName("subtitle")
            self._list.addWidget(empty)
        self.override_excluded.setVisible(bool(excluded))
        if unassociated:
            self._list.addWidget(self._section("UNASSOCIATED DATABASES"))
            hint = QLabel(
                "These schemas are not mapped to a live Nginx site. "
                "EXCLUDE leftover cutover copies, or DUMP AS UNASSIGNED into BACKUPS\\_unassigned-databases. "
                "BACKUP NOW stays blocked until every unassociated database is reviewed."
            )
            hint.setWordWrap(True)
            hint.setObjectName("subtitle")
            self._list.addWidget(hint)
            for db in unassociated:
                row = _DatabaseRow(db)
                row.include_btn.clicked.connect(lambda _=False, name=str(db.get("name") or ""): self._include_database(name))
                row.exclude_btn.clicked.connect(lambda _=False, name=str(db.get("name") or ""): self._exclude_database(name))
                self._database_rows.append(row)
                self._list.addWidget(row)
        if leftover_dbs:
            self._list.addWidget(self._section("EXCLUDED DATABASES (MIGRATION LEFTOVER)"))
            hint = QLabel(
                "These host schemas are only referenced under Dokploy migration copies. "
                "They are excluded from BACKUP NOW. Use DUMP AS UNASSIGNED to keep a copy."
            )
            hint.setWordWrap(True)
            hint.setObjectName("subtitle")
            self._list.addWidget(hint)
            for db in leftover_dbs:
                row = _DatabaseRow(db)
                row.exclude_btn.setVisible(False)
                row.include_btn.clicked.connect(
                    lambda _=False, name=str(db.get("name") or ""): self._include_database(name)
                )
                self._database_rows.append(row)
                self._list.addWidget(row)
        if removed:
            self._list.addWidget(self._section("REMOVED SITES"))
            hint = QLabel(
                "These applications are gone from active Nginx (Dokploy cutover). "
                "Master data is not deleted. Acknowledge after you have reviewed them."
            )
            hint.setWordWrap(True)
            hint.setObjectName("subtitle")
            self._list.addWidget(hint)
            for app in removed:
                self._list.addWidget(_ApplicationRow(app, checkable=False))
            ack = QPushButton("ACKNOWLEDGE REMOVED SITES")
            ack.setObjectName("acknowledgeRemoved")
            ack.clicked.connect(self._acknowledge_removed)
            self._list.addWidget(ack)
        if not pending and not approved and not excluded:
            empty = QLabel("Run DISCOVER SERVER to inventory active Nginx sites.")
            empty.setObjectName("subtitle")
            self._list.insertWidget(0, empty)
        self._list.addStretch()

    def _include_unused_default(self) -> bool:
        return bool(self.override_excluded.isVisible() and self.override_excluded.isChecked())

    def _persist(self) -> None:
        if not self._config:
            return
        snap = dict(self._result or {})
        snap["applications"] = [
            snapshot_application_row(row) for row in self._rows if row.get("change") != "removed"
        ]
        snap["database_inventory"] = list(self._databases)
        save_snapshot(self._config.backup_destination, snap)

    def _refresh(self) -> None:
        if not self._config:
            return
        payload = {**self._result, "applications": self._rows, "database_inventory": self._databases}
        self.reload(self._config, payload)

    def _include_database(self, name: str) -> None:
        if not self._config or not name:
            return
        set_database_decision(self._config.backup_destination, name, include_unassigned=True)
        self._databases = apply_database_policy(self._databases, self._config.backup_destination)
        self._persist()
        self._refresh()

    def _exclude_database(self, name: str) -> None:
        if not self._config or not name:
            return
        set_database_decision(self._config.backup_destination, name, excluded=True)
        self._databases = apply_database_policy(self._databases, self._config.backup_destination)
        self._persist()
        self._refresh()

    def _acknowledge_removed(self) -> None:
        if not self._config:
            return
        ids = [
            application_id(row)
            for row in self._rows
            if row.get("change") == "removed" and "ACKNOWLEDGED" not in str(row.get("status") or "")
        ]
        if not ids:
            return
        acknowledge_removed_applications(self._config.backup_destination, ids)
        self._rows = apply_policy(
            [row for row in self._rows if row.get("change") != "removed"],
            self._config.backup_destination,
        )
        self._persist()
        self._refresh()

    def _checked_ids(self) -> list[str]:
        ids: list[str] = []
        for row in self._pending_rows:
            if row.is_checked():
                ident = application_id(row.app)
                if ident:
                    ids.append(ident)
        return ids

    def _approve_selected(self) -> None:
        if not self._config:
            return
        selected = self._checked_ids()
        if not selected:
            QMessageBox.information(
                self,
                "APPLICATION DISCOVERY / APPROVAL",
                "Check at least one application first.",
            )
            return
        approved = approve_selected_applications(
            self._config.backup_destination,
            self._rows,
            selected,
            include_unused_default=self._include_unused_default(),
        )
        if not approved:
            QMessageBox.information(
                self,
                "APPLICATION DISCOVERY / APPROVAL",
                "No checked applications were eligible for approval.\n"
                "Unused default roots stay excluded unless you override that exclusion.",
            )
            return
        self._persist()
        self.reload(self._config, {"applications": self._rows, **{k: v for k, v in self._result.items() if k != "applications"}})
        self.approved.emit(len(approved))

    def _approve_all(self) -> None:
        if not self._config:
            return
        pending, _approved, excluded = split_approval_applications(self._rows)
        override = self._include_unused_default()
        targets = list(pending)
        if override:
            targets.extend(excluded)
        if not targets:
            QMessageBox.information(
                self,
                "APPLICATION DISCOVERY / APPROVAL",
                "There are no applications waiting for approval.",
            )
            return
        names = "\n".join(f"  {application_id(row)}  ({', '.join(hostnames(row))})" for row in targets)
        extra = ""
        if override and excluded:
            extra = "\n\nYou chose to override exclusion of unused default roots."
        else:
            extra = "\n\nUnused default roots stay excluded."
        answer = QMessageBox.question(
            self,
            "APPROVE ALL DISCOVERED",
            "Approve these applications for backup?\n\n"
            f"{names}{extra}\n\n"
            "BACKUP NOW is not run.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        approved = approve_all_applications(
            self._config.backup_destination,
            self._rows,
            include_unused_default=override,
        )
        wanted = set(approved)
        for row in self._rows:
            if application_id(row) in wanted:
                mark_row_approved(row)
        self._persist()
        self.reload(self._config, {"applications": self._rows, **{k: v for k, v in self._result.items() if k != "applications"}})
        self.approved.emit(len(approved))
