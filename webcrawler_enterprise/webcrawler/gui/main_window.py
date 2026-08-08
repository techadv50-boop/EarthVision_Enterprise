"""Main application window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from webcrawler import __app_name__, __version__
from webcrawler.auth.manager import AuthManager, UserAccount
from webcrawler.db.database import Database
from webcrawler.gui.login_dialog import ChangePasswordDialog
from webcrawler.gui.progress_panel import ProgressPanel
from webcrawler.gui.settings_dialog import SettingsDialog
from webcrawler.gui.workers import CrawlWorker
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.settings.manager import SettingsManager
from webcrawler.utils.url import parse_url_list


class MainWindow(QMainWindow):
    def __init__(
        self,
        auth: AuthManager | None = None,
        user: UserAccount | None = None,
    ) -> None:
        super().__init__()
        self.auth = auth or AuthManager()
        self.user = user
        title_user = f" — {user.username}" if user else ""
        self.setWindowTitle(f"{__app_name__} v{__version__}{title_user}")
        self.resize(1100, 780)

        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.settings
        self.worker = CrawlWorker()
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)

        self._build_menu()
        self._build_ui()
        self._restore_settings()
        self._set_running_ui(False)
        if self.user:
            self.statusBar().showMessage(f"Signed in as {self.user.username} ({self.user.role})")
        # After power loss / crash / offline stop, offer to continue automatically.
        QTimer.singleShot(250, self._offer_auto_resume)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        account = self.menuBar().addMenu("&Account")
        change_pw = QAction("Change Password…", self)
        change_pw.triggered.connect(self._change_password)
        account.addAction(change_pw)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("About", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, stretch=3)
        root.addLayout(right, stretch=2)

        left.addWidget(QLabel("Input URLs (one per line)"))
        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText(
            "https://www.harvard.edu\n"
            "https://www.mit.edu\n"
            "https://www.stanford.edu\n"
            "https://www.nasa.gov\n"
            "https://www.uet.edu.pk"
        )
        left.addWidget(self.urls_edit, stretch=1)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Output Folder"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select destination folder…")
        folder_row.addWidget(self.output_edit, stretch=1)
        self.browse_btn = QPushButton("Browse Output Folder")
        self.browse_btn.clicked.connect(self._browse_output)
        folder_row.addWidget(self.browse_btn)
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.clicked.connect(self._open_output)
        folder_row.addWidget(self.open_folder_btn)
        left.addLayout(folder_row)

        self.light_mode = QCheckBox(
            "Light mode — crawl ALL pages for emails & phones only (no file downloads, faster)"
        )
        self.light_mode.setChecked(bool(self.settings.contact_scan_only))
        self.light_mode.setToolTip(
            "Reads every HTML page and linked PDF/DOC/XLS/etc. for contacts, "
            "then discards the file. Does not save website files to disk."
        )
        left.addWidget(self.light_mode)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.stop_btn = QPushButton("Stop")
        self.clear_btn = QPushButton("Clear URLs")
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self._pause)
        self.resume_btn.clicked.connect(self._resume)
        self.stop_btn.clicked.connect(self._stop)
        self.clear_btn.clicked.connect(self.urls_edit.clear)
        for btn in (
            self.start_btn,
            self.pause_btn,
            self.resume_btn,
            self.stop_btn,
            self.clear_btn,
        ):
            btn_row.addWidget(btn)
        left.addLayout(btn_row)

        left.addWidget(QLabel("Activity Log"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        left.addWidget(self.log_view, stretch=1)

        self.progress_panel = ProgressPanel()
        right.addWidget(self.progress_panel)
        right.addStretch(1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _restore_settings(self) -> None:
        if self.settings.output_folder:
            self.output_edit.setText(self.settings.output_folder)
        if self.settings.last_urls:
            self.urls_edit.setPlainText(self.settings.last_urls)
        self.light_mode.setChecked(bool(self.settings.contact_scan_only))

    def _persist_inputs(self) -> None:
        self.settings.output_folder = self.output_edit.text().strip()
        self.settings.last_urls = self.urls_edit.toPlainText()
        self.settings.contact_scan_only = self.light_mode.isChecked()
        self.settings_manager.save(self.settings)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.output_edit.setText(path)
            self._persist_inputs()

    def _open_output(self) -> None:
        path = self.output_edit.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Output Folder", "Please select a valid output folder.")
            return
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _open_settings(self) -> None:
        self.settings.contact_scan_only = self.light_mode.isChecked()
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.result_settings()
            self.light_mode.setChecked(bool(self.settings.contact_scan_only))
            self.settings_manager.save(self.settings)
            self.statusBar().showMessage("Settings saved", 3000)

    def _change_password(self) -> None:
        if not self.user:
            return
        dialog = ChangePasswordDialog(
            self.auth,
            self.user.username,
            self,
            forced=False,
            require_current=True,
        )
        if dialog.exec() and dialog.user:
            self.user = dialog.user
            self.statusBar().showMessage("Password changed", 3000)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {__app_name__}",
            f"{__app_name__} v{__version__}\n\n"
            "Automatically crawl websites, download documents,\n"
            "and extract emails and phone numbers.",
        )

    def _start(self) -> None:
        urls_text = self.urls_edit.toPlainText()
        urls = parse_url_list(urls_text)
        output = self.output_edit.text().strip()
        if not urls:
            QMessageBox.warning(self, "Invalid URLs", "Enter at least one valid URL.")
            return
        if not output:
            QMessageBox.warning(self, "Output Folder", "Select an output folder.")
            return
        Path(output).mkdir(parents=True, exist_ok=True)
        self._persist_inputs()
        self.log_view.clear()
        mode = "LIGHT contact-scan" if self.settings.contact_scan_only else "FULL download"
        self._append_log(f"Queued {len(urls)} website(s). Starting ({mode})…")
        self._set_running_ui(True)
        self.worker.start(urls_text, output, self.settings)

    def _pause(self) -> None:
        self.worker.pause()
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.statusBar().showMessage("Paused")

    def _resume(self) -> None:
        if self.worker.is_busy():
            self.worker.resume()
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.statusBar().showMessage("Running")
        else:
            # Resume unfinished queue from disk after interruption
            try:
                self._set_running_ui(True)
                self._append_log("Resuming unfinished websites from saved progress…")
                self.worker.resume_queue(self.settings)
            except Exception as exc:
                self._set_running_ui(False)
                QMessageBox.information(self, "Resume", str(exc))

    def _offer_auto_resume(self) -> None:
        """Offer Resume for old unfinished work. Start always uses the URL box only."""
        try:
            qm = QueueManager(Database())
            unfinished = qm.count_unfinished()
            if unfinished <= 0:
                return
            reply = QMessageBox.question(
                self,
                "Resume unfinished crawl?",
                f"Found {unfinished} unfinished website(s) from a previous run.\n\n"
                "Yes = continue those old websites from where they stopped.\n"
                "No = ignore them. Click Start with the URLs currently in the box "
                "to begin a new crawl from scratch.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._resume()
            else:
                self.resume_btn.setEnabled(True)
                self.statusBar().showMessage(
                    f"{unfinished} old website(s) ignored — Start uses the URL box only",
                    8000,
                )
        except Exception:
            pass

    def _stop(self) -> None:
        self.worker.stop()
        self.statusBar().showMessage("Stopping…")

    def _on_progress(self, state) -> None:
        self.progress_panel.update_state(state)
        self.statusBar().showMessage(state.status)

    def _on_log(self, message: str) -> None:
        self._append_log(message)

    def _on_finished(self) -> None:
        self._set_running_ui(False)
        self.statusBar().showMessage("Finished")
        self._append_log("Processing finished.")

    def _on_error(self, message: str) -> None:
        self._set_running_ui(False)
        QMessageBox.critical(self, "Error", message)
        self._append_log(f"ERROR: {message}")

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _set_running_ui(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.urls_edit.setReadOnly(running)
        self.output_edit.setReadOnly(running)
        self.browse_btn.setEnabled(not running)
        self.light_mode.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        # Resume stays available when idle so power-loss recovery is one click.
        self.resume_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._persist_inputs()
        if self.worker.is_busy():
            reply = QMessageBox.question(
                self,
                "Crawl in progress",
                "A crawl is running. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
        event.accept()
