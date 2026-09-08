from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.backup.lock import BackupAlreadyRunning, BackupLock
from app.backup.progress import ProgressReporter
from app.config.schema import AppConfig
from app.config.store import save_config
from app.engine.status import clear_stale_progress, collect_dashboard_status, live_dashboard_message, progress_path
from app.gui.history_page import HistoryPage
from app.gui.logs_page import LogsPage
from app.gui.password import prompt_ubuntu_password
from app.gui.restore_page import RestorePage
from app.gui.security_page import SecurityPage
from app.gui.settings_page import SettingsPage
from app.gui.setup_dialog import DrivePickerDialog, SetupDialog
from app.gui.styles import STYLESHEET
from app.gui.widgets import Card
from app.ssh.client import SSHClient, SSHError
from app.utils.disk import needs_setup
from app.utils.format import format_bytes, format_duration

_LOG = logging.getLogger("serverbackup.gui")


class DashboardPage(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        title = QLabel(f"{__app_name__}")
        title.setObjectName("title")
        subtitle = QLabel(
            f"Version {__version__}  ·  Primary action: BACKUP NOW  ·  Automatic backup is OFF by default"
        )
        subtitle.setObjectName("subtitle")
        readonly = QLabel(
            "This dashboard is read-only. Click EDIT SETTINGS or CHOOSE BACKUP DRIVE to change values."
        )
        readonly.setObjectName("subtitle")
        readonly.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(readonly)
        setup_row = QHBoxLayout()
        edit_settings = QPushButton("EDIT SETTINGS")
        edit_settings.setObjectName("primary")
        edit_settings.clicked.connect(self._window.show_settings)
        choose_drive = QPushButton("CHOOSE BACKUP DRIVE")
        choose_drive.clicked.connect(self._window.choose_backup_drive)
        setup_row.addWidget(edit_settings)
        setup_row.addWidget(choose_drive)
        layout.addLayout(setup_row)
        self.server_card = Card("SERVER STATUS")
        self.master_card = Card("MASTER BACKUP")
        self.backup_card = Card("BACKUP STATUS")
        self.storage_card = Card("STORAGE")
        self.schedule_card = Card("SCHEDULE")
        layout.addWidget(self.server_card)
        layout.addWidget(self.master_card)
        layout.addWidget(self.backup_card)
        layout.addWidget(self.storage_card)
        layout.addWidget(self.schedule_card)
        self.security_card = Card("SERVER SECURITY")
        layout.addWidget(self.security_card)
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.speed_label = QLabel("")
        layout.addWidget(self.speed_label)
        self.backup_button = QPushButton("BACKUP NOW")
        self.backup_button.setObjectName("primary")
        self.backup_button.clicked.connect(self._window.confirm_backup)
        layout.addWidget(self.backup_button)
        self.rebuild_button = QPushButton("REBUILD MASTER BASELINE")
        self.rebuild_button.clicked.connect(self._window.confirm_rebuild)
        layout.addWidget(self.rebuild_button)
        self.cancel_button = QPushButton("CANCEL BACKUP")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self._window.cancel_backup)
        self.cancel_button.setVisible(False)
        layout.addWidget(self.cancel_button)
        grid = QHBoxLayout()
        for label, handler in [
            ("TEST CONNECTION", self._window.test_connection),
            ("BACKUP HISTORY", self._window.show_history),
            ("VIEW LOGS", self._window.show_logs),
            ("OPEN BACKUP FOLDER", self._window.open_backup_folder),
            ("SETTINGS", self._window.show_settings),
            ("RESTORE", self._window.show_restore),
            ("TEST BACKUP INTEGRITY", self._window.test_integrity),
            ("DRY RUN", self._window.dry_run),
            ("REFRESH", self._window.refresh),
        ]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            grid.addWidget(button)
        wrap = QWidget()
        wrap.setLayout(grid)
        layout.addWidget(wrap)
        security_label = QLabel("SERVER SECURITY")
        security_label.setStyleSheet("font-weight: 700; color: #10233a;")
        layout.addWidget(security_label)
        sec_grid = QHBoxLayout()
        check_btn = QPushButton("SECURITY CHECK")
        check_btn.clicked.connect(self._window.security_check)
        sec_grid.addWidget(check_btn)
        for label, tab in [
            ("ROTATE SECURITY CREDENTIALS", "rotate"),
            ("VIEW SERVER CHANGES", "changes"),
            ("VIEW SECURITY REPORT", "report"),
            ("SECURITY HISTORY", "history"),
            ("ROLLBACK SECURITY CHANGES", "rollback"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=tab: self._window.show_security(name))
            sec_grid.addWidget(button)
        sec_wrap = QWidget()
        sec_wrap.setLayout(sec_grid)
        layout.addWidget(sec_wrap)
        layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def render(self, status: dict, ssh_state: tuple[str, str] | None = None) -> None:
        connection, ssh = ssh_state or (status.get("connection") or "UNKNOWN", status.get("ssh") or "UNKNOWN")
        self.server_card.set_rows(
            [
                ("Ubuntu Server:", status.get("server_ip") or "—"),
                ("Connection:", connection),
                ("SSH:", ssh),
            ]
        )
        self.master_card.set_rows(
            [
                ("Status:", str(status.get("master_status") or "MISSING")),
                ("Generation:", str(status.get("master_generation") or "—")),
                ("Last operation:", str(status.get("master_type") or "—")),
                ("Updated:", str(status.get("master_updated") or "—")),
                ("OJS files_dir:", str(status.get("master_ojs") or "—")),
                ("Integrity:", str(status.get("master_detail") or "—")),
            ]
        )
        self.backup_card.set_rows(
            [
                ("Last Backup:", str(status.get("last_backup") or "—")),
                ("Last Backup Status:", str(status.get("last_status") or "NEVER RUN")),
                ("Last Backup Size:", str(status.get("last_size") or "—")),
                ("Successful timestamped archives:", str(status.get("successful_backups") or 0)),
                ("Master retention:", "none (no keep-5)"),
            ]
        )
        self.storage_card.set_rows(
            [
                ("Backup Drive:", str(status.get("drive") or "—")),
                ("Total Space:", str(status.get("total_space") or "—")),
                ("Free Space:", str(status.get("free_space") or "—")),
                ("Used Space:", str(status.get("used_space") or "—")),
            ]
        )
        self.schedule_card.set_rows(
            [
                ("Automatic Backup:", str(status.get("automatic_backup") or "OFF")),
                ("Next Automatic Backup:", str(status.get("next_automatic_backup") or "—")),
            ]
        )
        self.security_card.set_rows(
            [
                ("Mode:", str(status.get("security_mode") or "BALANCED")),
                ("Last Security Check:", str(status.get("last_security_check") or "NEVER RUN")),
                ("Overall:", str(status.get("security_overall") or "NEVER RUN")),
                ("Layer 1 Entry:", str(status.get("security_layer1") or "—")),
                ("Layer 2 Access:", str(status.get("security_layer2") or "—")),
                ("Layer 3 Integrity:", str(status.get("security_layer3") or "—")),
            ]
        )
        progress = status.get("progress") or {}
        running = bool(status.get("backup_running"))
        self.cancel_button.setVisible(running)
        self.backup_button.setEnabled(not running)
        self.rebuild_button.setEnabled(not running)
        message = status.get("live_message") or live_dashboard_message(progress, running=running)
        self.status_label.setText(message)
        done = int(progress.get("bytes_done") or 0)
        total = int(progress.get("bytes_total") or 0)
        progress_status = str(progress.get("status") or "idle").lower()
        show_details = running or progress_status == "success"
        if total > 0 and show_details:
            self.progress_bar.setValue(min(100, int(done * 100 / total)))
        elif running:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100 if progress_status == "success" else 0)
        bits = []
        if show_details:
            speed = int(progress.get("speed_bps") or 0)
            eta = progress.get("eta_seconds")
            sha = progress.get("sha256")
            if speed:
                bits.append(f"Speed: {format_bytes(speed)}/s")
            if eta:
                bits.append(f"Estimated remaining: {format_duration(eta)}")
            if sha:
                bits.append(f"SHA-256: {sha}")
            steps = progress.get("steps") or []
            if steps:
                bits.append(" | ".join(f"{'✓' if s.get('ok') else '•'} {s.get('label')}" for s in steps[-6:]))
        self.speed_label.setText("\n".join(bits))


class MainWindow(QMainWindow):
    _dry_run_finished = Signal(bool, str)

    def __init__(self, config: AppConfig, ssh_password: str = "") -> None:
        super().__init__()
        self.config = config
        self._ssh_password = ssh_password or ""
        self._ssh_state = ("UNKNOWN", "UNKNOWN")
        self.setWindowTitle(f"{__app_name__}  {__version__}")
        self.resize(1100, 780)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self)
        self.settings_page = SettingsPage()
        self.history_page = HistoryPage()
        self.logs_page = LogsPage()
        self.restore_page = RestorePage()
        self.security_page = SecurityPage()
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.logs_page)
        self.stack.addWidget(self.restore_page)
        self.stack.addWidget(self.security_page)
        layout.addWidget(self.stack)
        back = QPushButton("Back to dashboard")
        back.clicked.connect(self.show_dashboard)
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignLeft)
        self.settings_page.load_config(config)
        self.statusBar().showMessage(f"{__app_name__} Version {__version__}")
        self._dry_run_finished.connect(self._on_dry_run_finished, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def _ssh_client(self) -> SSHClient:
        return SSHClient(self.config, password=self._ssh_password or None)

    def _has_usable_key(self) -> bool:
        key = (self.config.ssh_private_key_path or "").strip()
        if not key:
            return False
        return Path(os.path.expandvars(os.path.expanduser(key))).is_file()

    def ensure_password(self) -> bool:
        if self._ssh_password:
            return True
        if self._has_usable_key():
            return True
        entered = prompt_ubuntu_password(self, self.config.ssh_username, self.config.server_ip)
        if entered is None:
            return False
        self._ssh_password = entered
        if not self._ssh_password:
            QMessageBox.warning(
                self,
                "Ubuntu password",
                f"Enter the SSH password for {self.config.ssh_username}@{self.config.server_ip}, "
                "or click Create SSH key first.",
            )
            return False
        return True

    def show_dashboard(self) -> None:
        self.stack.setCurrentWidget(self.dashboard)
        self.refresh()

    def show_settings(self) -> None:
        self.config = self.settings_page.current_config()
        self.settings_page.load_config(self.config)
        self.stack.setCurrentWidget(self.settings_page)
        self.settings_page.server_ip.setFocus()

    def choose_backup_drive(self) -> None:
        self.config = self.settings_page.current_config()
        dialog = DrivePickerDialog(self.config.backup_destination, self)
        if not dialog.exec() or not dialog.selected:
            return
        self.config.backup_destination = dialog.selected
        self.config.setup_completed = True
        self.settings_page.load_config(self.config)
        save_config(self.config)
        try:
            Path(self.config.backup_destination).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Backup folder", str(exc))
        self.refresh()
        QMessageBox.information(
            self,
            "Backup folder",
            f"Backups will be saved to:\n{self.config.backup_destination}",
        )

    def show_history(self) -> None:
        self.history_page.reload(self.config)
        self.stack.setCurrentWidget(self.history_page)

    def show_logs(self) -> None:
        self.logs_page.reload(self.config)
        self.stack.setCurrentWidget(self.logs_page)

    def show_restore(self) -> None:
        self.restore_page.reload(self.config, ssh_password=self._ssh_password)
        self.stack.setCurrentWidget(self.restore_page)

    def show_security(self, tab: str = "check") -> None:
        self.security_page.reload(self.config)
        self.security_page.show_tab(tab)
        self.stack.setCurrentWidget(self.security_page)

    def security_check(self) -> None:
        self.show_security("check")
        self.security_page._run_check()

    def open_restore(self, location: str) -> None:
        self.restore_page.reload(self.config, selected=location, ssh_password=self._ssh_password)
        self.stack.setCurrentWidget(self.restore_page)

    def refresh(self) -> None:
        """Reload local dashboard files. This never opens an SSH connection."""
        if self.stack.currentWidget() is self.settings_page:
            self.config = self.settings_page.current_config()
            return
        self.config = self.settings_page.current_config()
        status = collect_dashboard_status(self.config)
        status["connection"] = self._ssh_state[0]
        status["ssh"] = self._ssh_state[1]
        self.dashboard.render(status, self._ssh_state)

    def confirm_backup(self) -> None:
        lock = BackupLock(self.config.backup_destination)
        if lock.is_locked():
            QMessageBox.warning(self, "BACKUP NOW", "Backup already in progress.")
            return
        message = (
            "Start a master backup of the Ubuntu production server now?\n\n"
            f"Source:\n{self.config.server_ip}\n\n"
            f"Destination:\n{self.config.backup_destination}\\master\\\n\n"
            "First run creates a FULL master baseline. Later runs are INCREMENTAL.\n"
            "Unchanged data is recorded as NO_CHANGE. Master does not use keep-5 retention.\n"
            "Existing YYYY-MM-DD timestamped archives are left untouched."
        )
        box = QMessageBox(self)
        box.setWindowTitle("BACKUP NOW")
        box.setText(message)
        start = box.addButton("START BACKUP", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not start:
            return
        if not self.ensure_password():
            return
        save_config(self.config)
        config = self.config
        password = self._ssh_password

        def work() -> None:
            from app.engine.backup_engine import BackupEngine, BackupError

            try:
                BackupEngine(config, ssh=SSHClient(config, password=password or None), mode="manual").run()
            except (BackupError, SSHError, OSError) as exc:
                ProgressReporter(progress_path()).write(status="failed", message=str(exc), error=str(exc))

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("Backup started.")

    def confirm_rebuild(self) -> None:
        lock = BackupLock(self.config.backup_destination)
        if lock.is_locked():
            QMessageBox.warning(self, "REBUILD MASTER", "Backup already in progress.")
            return
        message = (
            "Rebuild the master baseline from a full Ubuntu inventory?\n\n"
            "This stages a new generation and replaces HEAD only after verification.\n"
            "The previous HEAD remains valid if staging fails.\n"
            "Existing 1.3.7 timestamped archives are not deleted."
        )
        box = QMessageBox(self)
        box.setWindowTitle("REBUILD MASTER BASELINE")
        box.setText(message)
        start = box.addButton("REBUILD", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not start:
            return
        if not self.ensure_password():
            return
        save_config(self.config)
        config = self.config
        password = self._ssh_password

        def work() -> None:
            from app.engine.backup_engine import BackupEngine, BackupError

            try:
                BackupEngine(config, ssh=SSHClient(config, password=password or None), mode="manual").rebuild_master()
            except (BackupError, SSHError, OSError) as exc:
                ProgressReporter(progress_path()).write(status="failed", message=str(exc), error=str(exc))

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("Master rebuild started.")

    def cancel_backup(self) -> None:
        ProgressReporter(progress_path()).request_cancel()
        self.statusBar().showMessage("Cancel requested.")

    def test_connection(self) -> None:
        from app.engine.backup_engine import BackupEngine

        self.config = self.settings_page.current_config()
        entered = prompt_ubuntu_password(self, self.config.ssh_username, self.config.server_ip)
        if entered is None:
            return
        self._ssh_password = entered
        if not self._ssh_password and not self._has_usable_key():
            QMessageBox.warning(
                self,
                "Ubuntu password",
                f"Enter the SSH password for {self.config.ssh_username}@{self.config.server_ip}, "
                "or click Create SSH key first.",
            )
            return
        engine = BackupEngine(self.config, ssh=self._ssh_client())
        try:
            result = engine.test_connection()
        except SSHError as exc:
            self._ssh_state = ("DISCONNECTED", "FAILED")
            QMessageBox.critical(self, "TEST CONNECTION", str(exc))
            self.refresh()
            return
        ok = bool(result.get("login") and result.get("script"))
        self._ssh_state = ("CONNECTED" if result.get("reachable") else "DISCONNECTED", "OK" if ok else "FAILED")
        details = "\n".join(result.get("details") or []) or str(result)
        if ok:
            clear_stale_progress(self.config)
            QMessageBox.information(self, "TEST CONNECTION", details)
        else:
            QMessageBox.critical(self, "TEST CONNECTION", details)
        self.refresh()

    def dry_run(self) -> None:
        self.config = self.settings_page.current_config()
        if BackupLock(self.config.backup_destination).is_locked():
            QMessageBox.warning(self, "DRY RUN", "Backup already in progress.")
            return
        if not self.ensure_password():
            return
        save_config(self.config)
        config = self.config
        password = self._ssh_password

        def work() -> None:
            from app.engine.backup_engine import BackupEngine, BackupCancelled, BackupError

            try:
                result = BackupEngine(config, ssh=SSHClient(config, password=password or None)).dry_run()
                text = str(result.get("report_text") or "Dry run finished.")
                self._dry_run_finished.emit(bool(result.get("ok")), text)
            except BackupAlreadyRunning as exc:
                _LOG.error("DRY_RUN_ERROR %s", exc)
                self._dry_run_finished.emit(False, str(exc))
            except BackupCancelled as exc:
                _LOG.info("DRY_RUN_ERROR cancelled")
                self._dry_run_finished.emit(False, str(exc))
            except (BackupError, SSHError, OSError, Exception) as exc:
                _LOG.exception("DRY_RUN_ERROR")
                try:
                    ProgressReporter(progress_path()).write(status="failed", message=str(exc), error=str(exc))
                except OSError:
                    pass
                self._dry_run_finished.emit(False, str(exc))

        threading.Thread(target=work, name="serverbackup-dry-run", daemon=True).start()
        self.statusBar().showMessage("Dry run started.")

    def _on_dry_run_finished(self, ok: bool, text: str) -> None:
        self.refresh()
        if ok:
            QMessageBox.information(self, "DRY RUN", text)
            self.statusBar().showMessage("Dry run complete.")
        else:
            QMessageBox.critical(self, "DRY RUN failed", text)
            self.statusBar().showMessage("Dry run failed.")

    def test_integrity(self) -> None:
        from app.master.health import assess_health
        from app.master.store import MasterStore

        store = MasterStore(self.config.backup_destination)
        health = assess_health(store, deep=True)
        QMessageBox.information(
            self,
            "MASTER INTEGRITY",
            f"Status: {health.get('status')}\nGeneration: {health.get('generation')}\n{health.get('detail')}",
        )

    def open_backup_folder(self) -> None:
        self.open_path(self.config.backup_destination)

    def open_path(self, path: str) -> None:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
            return
        opener = "xdg-open"
        subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_gui(config: AppConfig) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    ssh_password = ""
    if needs_setup(config):
        dialog = SetupDialog(config)
        if dialog.exec():
            config = dialog.apply_to(config)
            ssh_password = dialog.ubuntu_password()
            save_config(config)
            try:
                Path(config.backup_destination).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
    window = MainWindow(config, ssh_password=ssh_password)
    window.show()
    if needs_setup(config):
        window.choose_backup_drive()
    return app.exec()
