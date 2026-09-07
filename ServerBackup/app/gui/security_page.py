from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import AppConfig
from app.config.store import default_config_path, save_config
from app.serversec.credentials import proposed_rotation, rotate_local_token
from app.serversec.engine import SecurityEngine, SecurityError
from app.serversec.snapshot import SecurityStore
from app.ssh.client import SSHError
from app.utils.process import spawn_detached


class SecurityPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        self._last_report: dict | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("SERVER SECURITY")
        heading.setObjectName("title")
        layout.addWidget(heading)
        subtitle = QLabel(
            "On-demand three-layer audit. Backup and restore are unchanged. "
            "Checks do not run in the background and do not stop Nginx, PHP-FPM, or MariaDB."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.tabs = QTabWidget()
        self.check_tab = QWidget()
        self.changes_tab = QWidget()
        self.report_tab = QWidget()
        self.history_tab = QWidget()
        self.rotate_tab = QWidget()
        self.rollback_tab = QWidget()
        self.tabs.addTab(self.check_tab, "Security check")
        self.tabs.addTab(self.changes_tab, "Server changes")
        self.tabs.addTab(self.report_tab, "Security report")
        self.tabs.addTab(self.history_tab, "Security history")
        self.tabs.addTab(self.rotate_tab, "Rotate credentials")
        self.tabs.addTab(self.rollback_tab, "Rollback")
        layout.addWidget(self.tabs)
        self._build_check()
        self._build_changes()
        self._build_report()
        self._build_history()
        self._build_rotate()
        self._build_rollback()

    def show_tab(self, name: str) -> None:
        mapping = {
            "check": 0,
            "changes": 1,
            "report": 2,
            "history": 3,
            "rotate": 4,
            "rollback": 5,
        }
        self.tabs.setCurrentIndex(mapping.get(name, 0))

    def reload(self, config: AppConfig) -> None:
        self._config = config
        store = SecurityStore(config.security_store)
        latest = store.latest_id()
        self.mode_label.setText(f"Mode: {config.security_mode} (BALANCED default is audit-only)")
        if latest:
            try:
                self._last_report = store.load_report(latest)
                self._fill_findings(self._last_report.get("findings") or [])
                self.summary.setText(
                    f"Last check: {self._last_report.get('timestamp')}  ·  Overall: {self._last_report.get('overall')}"
                )
                self.report_view.setPlainText(
                    (store.reports / f"security-{latest}.txt").read_text(encoding="utf-8")
                    if (store.reports / f"security-{latest}.txt").is_file()
                    else str(self._last_report)
                )
            except (OSError, ValueError):
                self.summary.setText("Last check could not be read.")
        else:
            self.summary.setText("Last check: NEVER RUN")
            self.findings.setRowCount(0)
            self.report_view.setPlainText("No security report yet. Click SECURITY CHECK.")
        snapshots = store.list_snapshots()
        ids = [row["id"] for row in snapshots]
        for combo in (self.left_snap, self.right_snap):
            current = combo.currentText()
            combo.clear()
            combo.addItems(ids)
            if current:
                combo.setCurrentText(current)
        self.history_list.setRowCount(len(snapshots))
        for index, row in enumerate(snapshots):
            self.history_list.setItem(index, 0, QTableWidgetItem(row["id"]))
            self.history_list.setItem(index, 1, QTableWidgetItem(row["path"]))
        self.proposal.setPlainText(_proposal_text(proposed_rotation()))
        points = store.list_rollback_points()
        self.rollback_combo.clear()
        for point in points:
            self.rollback_combo.addItem(str(point.get("id")), point)

    def _build_check(self) -> None:
        layout = QVBoxLayout(self.check_tab)
        self.mode_label = QLabel("Mode: BALANCED")
        self.summary = QLabel("Last check: NEVER RUN")
        layout.addWidget(self.mode_label)
        layout.addWidget(self.summary)
        run = QPushButton("SECURITY CHECK")
        run.setObjectName("primary")
        run.clicked.connect(self._run_check)
        layout.addWidget(run)
        accept = QPushButton("Accept current snapshot as trusted baseline")
        accept.clicked.connect(self._accept_trusted)
        layout.addWidget(accept)
        self.findings = QTableWidget(0, 4)
        self.findings.setHorizontalHeaderLabels(["Severity", "Kind", "Path / detail", "Reason"])
        self.findings.horizontalHeader().setStretchLastSection(True)
        self.findings.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.findings)

    def _build_changes(self) -> None:
        layout = QVBoxLayout(self.changes_tab)
        layout.addWidget(QLabel("Compare historical snapshots (example: 2026-09-06 VS 2026-09-07)."))
        row = QHBoxLayout()
        self.left_snap = QComboBox()
        self.right_snap = QComboBox()
        row.addWidget(self.left_snap)
        row.addWidget(QLabel("VS"))
        row.addWidget(self.right_snap)
        compare = QPushButton("VIEW SERVER CHANGES")
        compare.clicked.connect(self._compare)
        row.addWidget(compare)
        layout.addLayout(row)
        self.changes_table = QTableWidget(0, 4)
        self.changes_table.setHorizontalHeaderLabels(["Severity", "Kind", "Path / detail", "Reason"])
        self.changes_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.changes_table)

    def _build_report(self) -> None:
        layout = QVBoxLayout(self.report_tab)
        layout.addWidget(QLabel("Comprehensive report. Passwords and private keys are never included."))
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        layout.addWidget(self.report_view)

    def _build_history(self) -> None:
        layout = QVBoxLayout(self.history_tab)
        self.history_list = QTableWidget(0, 2)
        self.history_list.setHorizontalHeaderLabels(["Snapshot", "Location"])
        self.history_list.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.history_list)

    def _build_rotate(self) -> None:
        layout = QVBoxLayout(self.rotate_tab)
        layout.addWidget(
            QLabel(
                "Rotates only the application security token. "
                "MariaDB, OJS, website, PHP, SMTP, API, and SSH host credentials are never changed."
            )
        )
        self.proposal = QPlainTextEdit()
        self.proposal.setReadOnly(True)
        layout.addWidget(self.proposal)
        form = QFormLayout()
        self.rotate_confirm = QLineEdit()
        self.rotate_confirm.setPlaceholderText("ROTATE")
        form.addRow("Type ROTATE to confirm", self.rotate_confirm)
        layout.addLayout(form)
        button = QPushButton("ROTATE SECURITY CREDENTIALS")
        button.setObjectName("danger")
        button.clicked.connect(self._rotate)
        layout.addWidget(button)
        self.rotate_result = QPlainTextEdit()
        self.rotate_result.setReadOnly(True)
        layout.addWidget(self.rotate_result)

    def _build_rollback(self) -> None:
        layout = QVBoxLayout(self.rollback_tab)
        layout.addWidget(
            QLabel(
                "Restores only security state written by this application "
                "(/etc/serverbackup token hash and the local trusted pointer). "
                "Website files, databases, and Nginx are not rolled back here — use Restore for those."
            )
        )
        self.rollback_combo = QComboBox()
        layout.addWidget(self.rollback_combo)
        self.rollback_confirm = QLineEdit()
        self.rollback_confirm.setPlaceholderText("ROLLBACK")
        layout.addWidget(self.rollback_confirm)
        button = QPushButton("ROLLBACK SECURITY CHANGES")
        button.setObjectName("danger")
        button.clicked.connect(self._rollback)
        layout.addWidget(button)

    def _fill_findings(self, findings: list, table: QTableWidget | None = None) -> None:
        widget = table or self.findings
        widget.setRowCount(len(findings))
        for index, item in enumerate(findings):
            detail = str(item.get("path") or item.get("detail") or "")
            values = [
                str(item.get("severity") or ""),
                str(item.get("kind") or ""),
                detail,
                str(item.get("reason") or ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if item.get("severity") == "CRITICAL":
                    cell.setForeground(Qt.GlobalColor.red)
                widget.setItem(index, col, cell)

    def _run_check(self) -> None:
        if not self._config:
            return
        from app.backup.lock import BackupLock

        if BackupLock(self._config.backup_destination).is_locked():
            QMessageBox.warning(
                self,
                "SECURITY CHECK",
                "A backup is running. Security check was not started so production I/O is not increased.",
            )
            return
        save_config(self._config)
        from pathlib import Path

        spawn_detached(
            ["--security-check", "--config", str(default_config_path())],
            cwd=Path(__file__).resolve().parents[2],
        )
        QMessageBox.information(
            self,
            "SECURITY CHECK",
            "On-demand audit started in the background. Refresh this page after it finishes. "
            "No production files will be modified.",
        )

    def _accept_trusted(self) -> None:
        if not self._config:
            return
        store = SecurityStore(self._config.security_store)
        latest = store.latest_id()
        if not latest:
            QMessageBox.information(self, "Trusted baseline", "Run SECURITY CHECK first.")
            return
        store.set_trusted(latest)
        QMessageBox.information(self, "Trusted baseline", f"Trusted snapshot is now {latest}.")

    def _compare(self) -> None:
        if not self._config:
            return
        left = self.left_snap.currentText()
        right = self.right_snap.currentText()
        if not left or not right:
            QMessageBox.information(self, "Compare", "Select two snapshots.")
            return
        engine = SecurityEngine(self._config)
        result = engine.compare(left, right)
        self._fill_findings(result.get("findings") or [], self.changes_table)

    def _rotate(self) -> None:
        if not self._config:
            return
        proposal = proposed_rotation()
        box = QMessageBox(self)
        box.setWindowTitle("ROTATE SECURITY CREDENTIALS")
        box.setText(
            "Target: application security token\n\n"
            "This will NOT change MariaDB, OJS, website, PHP, SMTP, API, or SSH login keys.\n"
            "A rollback point (hashes only) is created first.\n"
            "The new token is shown once and is not written to reports or logs."
        )
        box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
        go = box.addButton("APPLY ROTATION", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        try:
            store = SecurityStore(self._config.security_store)
            result = rotate_local_token(store, confirmation=self.rotate_confirm.text())
            engine = SecurityEngine(self._config)
            try:
                engine.rotate_remote_token(new_hash=_hash_from_result(result), confirmation="ROTATE")
            except (SecurityError, SSHError) as exc:
                # Local rotation succeeded; remote helper may not be installed yet.
                result["remote"] = str(exc)
        except ValueError as exc:
            QMessageBox.warning(self, "Rotation", str(exc))
            return
        token = result.get("new_token") or ""
        self.rotate_result.setPlainText(
            f"{result.get('message')}\n\nNew token (shown once):\n{token}\n\nStore this securely. It will not appear in logs."
        )

    def _rollback(self) -> None:
        if not self._config:
            return
        rollback_id = self.rollback_combo.currentText()
        if not rollback_id:
            QMessageBox.information(self, "Rollback", "No application-managed rollback point exists.")
            return
        try:
            engine = SecurityEngine(self._config)
            result = engine.rollback(rollback_id, confirmation=self.rollback_confirm.text())
        except (SecurityError, ValueError, SSHError) as exc:
            QMessageBox.critical(self, "Rollback", str(exc))
            return
        QMessageBox.information(self, "Rollback", str(result))


def _proposal_text(proposal: dict) -> str:
    lines = [
        f"Target: {proposal.get('target')}",
        f"Action: {proposal.get('action')}",
        f"Current token id: {proposal.get('current_token_id')}",
        f"Lockout protection: {proposal.get('lockout_protection')}",
        "",
        "Will not change:",
    ]
    for item in proposal.get("will_not_change") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _hash_from_result(result: dict) -> str:
    from app.serversec.credentials import load_credential_record

    return str(load_credential_record().get("token_hash") or "")
