from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config.schema import AgentConfig
from app.privacy import privacy_statement


class SetupDialog(QDialog):
    def __init__(self, parent, config: AgentConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle("Employee Monitoring Agent — Setup")
        self.setMinimumWidth(420)
        self.config = config
        layout = QVBoxLayout(self)
        title = QLabel("First-run setup")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("Set a dashboard password. It is stored as a hash, never as plain text."))
        form = QFormLayout()
        self.employee = QLineEdit(config.employee_id)
        self.device = QLineEdit(config.device_id)
        self.server = QLineEdit(config.server_url)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Employee ID", self.employee)
        form.addRow("Device ID", self.device)
        form.addRow("Server URL", self.server)
        form.addRow("Password", self.password)
        form.addRow("Confirm password", self.confirm)
        layout.addLayout(form)
        notice = QLabel(privacy_statement())
        notice.setWordWrap(True)
        notice.setObjectName("subtitle")
        layout.addWidget(notice)
        row = QHBoxLayout()
        row.addStretch(1)
        save = QPushButton("Save and continue")
        save.setObjectName("primary")
        save.clicked.connect(self._accept)
        row.addWidget(save)
        layout.addLayout(row)

    def _accept(self) -> None:
        if not self.employee.text().strip():
            QMessageBox.warning(self, "Setup", "Employee ID is required.")
            return
        if not self.password.text():
            QMessageBox.warning(self, "Setup", "Password is required.")
            return
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Setup", "Passwords do not match.")
            return
        self.accept()

    def values(self) -> tuple[str, str, str, str]:
        return (
            self.employee.text().strip(),
            self.device.text().strip(),
            self.server.text().strip(),
            self.password.text(),
        )


class SettingsDialog(QDialog):
    def __init__(self, parent, config: AgentConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.employee = QLineEdit(config.employee_id)
        self.device = QLineEdit(config.device_id)
        self.server = QLineEdit(config.server_url)
        self.inactivity = QSpinBox()
        self.inactivity.setRange(5, 3600)
        self.inactivity.setValue(config.inactivity_timeout_seconds)
        self.heartbeat = QSpinBox()
        self.heartbeat.setRange(5, 3600)
        self.heartbeat.setValue(config.heartbeat_interval_seconds)
        form.addRow("Employee ID", self.employee)
        form.addRow("Device ID", self.device)
        form.addRow("Server URL", self.server)
        form.addRow("Inactivity seconds", self.inactivity)
        form.addRow("Heartbeat seconds", self.heartbeat)
        layout.addLayout(form)
        note = QLabel("Windows passwords are never collected. Activity uses last-input age only.")
        note.setWordWrap(True)
        note.setObjectName("subtitle")
        layout.addWidget(note)
        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

    def apply_to(self, config: AgentConfig) -> AgentConfig:
        config.employee_id = self.employee.text().strip()
        config.device_id = self.device.text().strip()
        config.server_url = self.server.text().strip()
        config.inactivity_timeout_seconds = int(self.inactivity.value())
        config.heartbeat_interval_seconds = int(self.heartbeat.value())
        return config
