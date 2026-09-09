from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app import __app_name__
from app.gui.icons import make_icon
from app.service.agent import AgentService
from app.status.events import to_iso


class AgentTray(QSystemTrayIcon):
    def __init__(self, service: AgentService, callbacks: dict) -> None:
        super().__init__()
        self.service = service
        self.callbacks = callbacks
        self.setToolTip(__app_name__)
        menu = QMenu()
        header = QAction(__app_name__, menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()
        menu.addAction("Open", callbacks["open"])
        self.status_menu = menu.addMenu("Status")
        menu.addAction("Settings", callbacks["settings"])
        menu.addAction("About", callbacks["about"])
        menu.addSeparator()
        menu.addAction("Exit", callbacks["exit"])
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        self.refresh()

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.callbacks["open"]()

    def refresh(self) -> None:
        state = self.service.engine.state
        self.setIcon(make_icon(state.tray_indicator()))
        self.setToolTip(
            f"{__app_name__}\n{state.employee_status()} · {state.connection}"
        )
        self.status_menu.clear()
        last = to_iso(state.last_server_communication) or "none"
        lines = [
            f"Employee ID: {state.employee_id}",
            f"Device ID: {state.device_id}",
            f"Connection status: {state.connection}",
            f"Last server communication: {last}",
            f"Current activity status: {state.activity_status()}",
        ]
        for line in lines:
            action = QAction(line, self.status_menu)
            action.setEnabled(False)
            self.status_menu.addAction(action)
