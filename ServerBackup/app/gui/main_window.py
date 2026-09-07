from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.backup.lock import BackupLock
from app.backup.progress import ProgressReporter
from app.config.schema import AppConfig
from app.config.store import default_config_path, load_config, save_config
from app.engine.status import collect_dashboard_status, progress_path
from app.gui.history_page import HistoryPage
from app.gui.logs_page import LogsPage
from app.gui.restore_page import RestorePage
from app.gui.settings_page import SettingsPage
from app.gui.styles import STYLESHEET
from app.gui.widgets import Card
from app.ssh.client import SSHClient, SSHError
from app.utils.format import format_bytes, format_duration
from app.utils.process import spawn_detached


class DashboardPage(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        layout = QVBoxLayout(self)
        title = QLabel(f"{__app_name__}")
        title.setObjectName("title")
        subtitle = QLabel(f"Version {__version__}  ·  Primary action: BACKUP NOW  ·  Automatic backup is OFF by default")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.server_card = Card("SERVER STATUS")
        self.backup_card = Card("BACKUP STATUS")
        self.storage_card = Card("STORAGE")
        self.schedule_card = Card("SCHEDULE")
        layout.addWidget(self.server_card)
        layout.addWidget(self.backup_card)
        layout.addWidget(self.storage_card)
        layout.addWidget(self.schedule_card)
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
        layout.addStretch()

    def render(self, status: dict, ssh_state: tuple[str, str] | None = None) -> None:
        connection, ssh = ssh_state or (status.get("connection") or "UNKNOWN", status.get("ssh") or "UNKNOWN")
        self.server_card.set_rows(
            [
                ("Ubuntu Server:", status.get("server_ip") or "—"),
                ("Connection:", connection),
                ("SSH:", ssh),
            ]
        )
        self.backup_card.set_rows(
            [
                ("Last Backup:", str(status.get("last_backup") or "—")),
                ("Last Backup Status:", str(status.get("last_status") or "NEVER RUN")),
                ("Last Backup Size:", str(status.get("last_size") or "—")),
                ("Successful Backups:", str(status.get("successful_backups") or 0)),
                ("Retention:", str(status.get("retention") or 5)),
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
        progress = status.get("progress") or {}
        running = bool(status.get("backup_running"))
        self.cancel_button.setVisible(running)
        self.backup_button.setEnabled(not running)
        message = progress.get("message") or ("BACKUP IN PROGRESS" if running else "Ready.")
        self.status_label.setText(message)
        done = int(progress.get("bytes_done") or 0)
        total = int(progress.get("bytes_total") or 0)
        if total > 0:
            self.progress_bar.setValue(min(100, int(done * 100 / total)))
        elif running:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100 if progress.get("status") == "success" else 0)
        speed = int(progress.get("speed_bps") or 0)
        eta = progress.get("eta_seconds")
        sha = progress.get("sha256")
        bits = []
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
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
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
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.logs_page)
        self.stack.addWidget(self.restore_page)
        layout.addWidget(self.stack)
        back = QPushButton("Back to dashboard")
        back.clicked.connect(self.show_dashboard)
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignLeft)
        self.settings_page.load_config(config)
        self.statusBar().showMessage(f"{__app_name__} Version {__version__}")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def show_dashboard(self) -> None:
        self.stack.setCurrentWidget(self.dashboard)
        self.refresh()

    def show_settings(self) -> None:
        self.config = self.settings_page.current_config()
        self.settings_page.load_config(self.config)
        self.stack.setCurrentWidget(self.settings_page)

    def show_history(self) -> None:
        self.history_page.reload(self.config)
        self.stack.setCurrentWidget(self.history_page)

    def show_logs(self) -> None:
        self.logs_page.reload(self.config)
        self.stack.setCurrentWidget(self.logs_page)

    def show_restore(self) -> None:
        self.restore_page.reload(self.config)
        self.stack.setCurrentWidget(self.restore_page)

    def open_restore(self, location: str) -> None:
        self.restore_page.reload(self.config, selected=location)
        self.stack.setCurrentWidget(self.restore_page)

    def refresh(self) -> None:
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
            "Start a complete backup of the Ubuntu production server now?\n\n"
            f"Source:\n{self.config.server_ip}\n\n"
            f"Destination:\n{self.config.backup_destination}\n\n"
            f"Retention:\n{self.config.retention_count} successful backups"
        )
        box = QMessageBox(self)
        box.setWindowTitle("BACKUP NOW")
        box.setText(message)
        start = box.addButton("START BACKUP", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not start:
            return
        save_config(self.config)
        try:
            spawn_detached(
                ["--backup", "--mode", "manual", "--config", str(default_config_path())],
                cwd=Path(__file__).resolve().parents[2],
            )
        except OSError as exc:
            QMessageBox.critical(self, "BACKUP NOW", str(exc))
            return
        self.statusBar().showMessage("Backup started in a background process.")

    def cancel_backup(self) -> None:
        ProgressReporter(progress_path()).request_cancel()
        self.statusBar().showMessage("Cancel requested.")

    def test_connection(self) -> None:
        from app.engine.backup_engine import BackupEngine

        engine = BackupEngine(self.config)
        try:
            result = engine.test_connection()
        except SSHError as exc:
            self._ssh_state = ("DISCONNECTED", "FAILED")
            QMessageBox.critical(self, "TEST CONNECTION", str(exc))
            self.refresh()
            return
        ok = result.get("login") and result.get("script")
        self._ssh_state = ("CONNECTED" if result.get("reachable") else "DISCONNECTED", "OK" if ok else "FAILED")
        details = "\n".join(result.get("details") or [])
        QMessageBox.information(self, "TEST CONNECTION", details or str(result))
        self.refresh()

    def dry_run(self) -> None:
        save_config(self.config)
        try:
            spawn_detached(
                ["--dry-run", "--config", str(default_config_path())],
                cwd=Path(__file__).resolve().parents[2],
            )
        except OSError as exc:
            QMessageBox.critical(self, "DRY RUN", str(exc))
            return
        self.statusBar().showMessage("Dry run started.")

    def test_integrity(self) -> None:
        self.show_history()
        QMessageBox.information(
            self,
            "TEST BACKUP INTEGRITY",
            "Select a successful backup in history, then click Verify integrity.",
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
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(config)
    window.show()
    return app.exec()
