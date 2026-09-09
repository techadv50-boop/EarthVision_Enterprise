from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.privacy import privacy_statement
from app.service.agent import AgentService
from app.status.events import to_iso


class DashboardWindow(QMainWindow):
    def __init__(self, service: AgentService, on_close) -> None:
        super().__init__()
        self.service = service
        self._on_close = on_close
        self.setWindowTitle(__app_name__)
        self.resize(720, 520)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel(__app_name__)
        title.setObjectName("title")
        subtitle = QLabel(f"Version {__version__}  ·  Presence monitoring only")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.status_badge = QLabel("")
        layout.addWidget(self.status_badge)
        tabs = QTabWidget()
        tabs.addTab(self._status_tab(), "Status")
        tabs.addTab(self._audit_tab(), "Audit log")
        tabs.addTab(self._privacy_tab(), "Privacy")
        layout.addWidget(tabs)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def _status_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.employee_label = QLabel()
        self.device_label = QLabel()
        self.connection_label = QLabel()
        self.last_comm_label = QLabel()
        self.activity_label = QLabel()
        self.monitor_label = QLabel()
        for label in (
            self.employee_label,
            self.device_label,
            self.connection_label,
            self.last_comm_label,
            self.activity_label,
            self.monitor_label,
        ):
            layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _audit_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Employee", "Device", "Event"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        return widget

    def _privacy_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        text = QLabel(privacy_statement())
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch(1)
        return widget

    def refresh(self) -> None:
        state = self.service.engine.state
        self.status_badge.setText(f"Employee status: {state.employee_status()}")
        self.employee_label.setText(f"Employee ID: {state.employee_id}")
        self.device_label.setText(f"Device ID: {state.device_id}")
        self.connection_label.setText(f"Connection: {state.connection}")
        last = to_iso(state.last_server_communication) or "none"
        self.last_comm_label.setText(f"Last server communication: {last}")
        self.activity_label.setText(f"Current activity status: {state.activity_status()}")
        self.monitor_label.setText(
            "Monitoring: running" if self.service.is_monitoring() else "Monitoring: stopped"
        )
        events = self.service.events()[-50:]
        self.table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = [
                to_iso(event.timestamp) or "",
                event.employee_id,
                event.device_id,
                event.event_type.value,
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        self._on_close()
        event.accept()
