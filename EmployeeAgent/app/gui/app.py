from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __app_name__, __version__
from app.gui.dashboard import DashboardWindow
from app.gui.password_dialog import prompt_password
from app.gui.setup_dialog import SettingsDialog, SetupDialog
from app.gui.styles import STYLESHEET
from app.gui.tray import AgentTray
from app.privacy import privacy_statement
from app.service.agent import AgentService


class AgentGui:
    def __init__(self, service: AgentService, *, background: bool) -> None:
        self.service = service
        self.background = background
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName(__app_name__)
        self.app.setStyleSheet(STYLESHEET)
        self.dashboard: DashboardWindow | None = None
        self.tray = AgentTray(
            service,
            {
                "open": self.open_dashboard,
                "settings": self.open_settings,
                "about": self.show_about,
                "exit": self.request_exit,
            },
        )
        self.tray.show()
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.tray.refresh)
        self.refresh_timer.start(1000)
        if os.name == "nt":
            try:
                from app.gui.native import NativeHooks
                from app.platform.windows import WindowsPlatform

                if isinstance(service.platform, WindowsPlatform):
                    self.hooks = NativeHooks(service.platform)
            except Exception:
                pass

    def maybe_setup(self) -> bool:
        if not self.service.config.needs_setup() or self.background:
            if self.service.config.needs_setup() and self.background:
                self.service.engine.set_config_error("Configuration required")
            return True
        dialog = SetupDialog(None, self.service.config)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        employee_id, device_id, server_url, password = dialog.values()
        config = self.service.config
        config.employee_id = employee_id
        config.device_id = device_id or config.device_id
        config.server_url = server_url or config.server_url
        hashed = self.service.access.set_password(password)
        config.password_hash = hashed
        self.service.engine.state.employee_id = config.employee_id
        self.service.engine.state.device_id = config.device_id
        self.service.save_config(config)
        return True

    def open_dashboard(self) -> None:
        if not prompt_password(
            None,
            title="Password Required",
            prompt="Password:",
            confirm_label="Authenticate",
            verifier=self.service.access.verify,
        ):
            return
        self.service.access.dashboard_open = True
        if self.dashboard is not None:
            self.dashboard.close()
        self.dashboard = DashboardWindow(self.service, on_close=self._dashboard_closed)
        self.dashboard.show()
        self.dashboard.raise_()

    def _dashboard_closed(self) -> None:
        self.service.close_dashboard()
        self.dashboard = None

    def open_settings(self) -> None:
        if not prompt_password(
            None,
            title="Password Required",
            prompt="Password:",
            confirm_label="Authenticate",
            verifier=self.service.access.verify,
        ):
            return
        dialog = SettingsDialog(None, self.service.config)
        if dialog.exec() == dialog.DialogCode.Accepted:
            config = dialog.apply_to(self.service.config)
            self.service.save_config(config)

    def show_about(self) -> None:
        QMessageBox.information(
            None,
            f"About {__app_name__}",
            f"{__app_name__} {__version__}\n\n{privacy_statement()}",
        )

    def request_exit(self) -> None:
        if not prompt_password(
            None,
            title="Exit Employee Monitoring Agent?",
            prompt="Password:",
            confirm_label="Confirm Exit",
            verifier=self.service.access.authorize_exit,
        ):
            return
        self.service.stop(record_exit=True)
        self.app.quit()

    def run(self) -> int:
        if not self.maybe_setup():
            self.service.stop(record_exit=False)
            return 0
        return self.app.exec()
