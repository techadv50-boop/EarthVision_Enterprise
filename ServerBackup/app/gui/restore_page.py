from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.backup.retention import list_successful_backups
from app.config.schema import AppConfig
from app.master.store import MasterStore
from app.restore.restore_engine import CONFIRMATION_PHRASE, RestoreEngine, RestoreError, warning_text
from app.ssh.client import SSHClient, SSHError


class RestorePage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        self._ssh_password = ""
        layout = QVBoxLayout(self)
        heading = QLabel("Restore")
        heading.setObjectName("title")
        layout.addWidget(heading)
        warning = QLabel(
            "Restore can overwrite production data. A detailed warning is shown below. "
            "Nginx is never restarted automatically."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self.backup = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(
            [
                "Restore Website Files",
                "Restore Database",
                "Restore Nginx Configuration",
                "Restore Complete Backup",
            ]
        )
        self.kind.currentTextChanged.connect(self._refresh_warning)
        self.target = QLineEdit()
        self.database = QLineEdit()
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText(CONFIRMATION_PHRASE)
        form.addRow("Backup", self.backup)
        form.addRow("Restore type", self.kind)
        form.addRow("Website path (files restore)", self.target)
        form.addRow("Database name", self.database)
        form.addRow(f'Type {CONFIRMATION_PHRASE} to confirm', self.confirm)
        layout.addLayout(form)
        self.warning_box = QTextEdit()
        self.warning_box.setReadOnly(True)
        layout.addWidget(self.warning_box)
        button = QPushButton("RESTORE")
        button.setObjectName("danger")
        button.clicked.connect(self._restore)
        layout.addWidget(button)
        self._refresh_warning()

    def reload(self, config: AppConfig, selected: str | None = None, ssh_password: str = "") -> None:
        self._config = config
        self._ssh_password = ssh_password
        self.backup.clear()
        store = MasterStore(config.backup_destination)
        if store.has_head():
            head = store.head_generation()
            self.backup.addItem(f"Master HEAD (generation {head})", f"master:{head}")
            for tree_path in sorted(store.trees_dir.glob("*.json"), reverse=True):
                try:
                    gen = int(tree_path.stem)
                except ValueError:
                    continue
                if gen == head:
                    continue
                self.backup.addItem(f"Master generation {gen}", f"master:{gen}")
        for path in reversed(list_successful_backups(config.backup_destination)):
            self.backup.addItem(f"Legacy archive {path.name}", str(path))
        if selected:
            index = self.backup.findData(selected)
            if index >= 0:
                self.backup.setCurrentIndex(index)
        if config.website_directories:
            self.target.setText(config.website_directories[0])

    def _action(self) -> str:
        mapping = {
            "Restore Website Files": "restore-files",
            "Restore Database": "restore-database",
            "Restore Nginx Configuration": "restore-nginx",
            "Restore Complete Backup": "restore-complete",
        }
        return mapping[self.kind.currentText()]

    def _refresh_warning(self) -> None:
        self.warning_box.setPlainText(warning_text(self._action()))

    def _restore(self) -> None:
        if not self._config:
            return
        if self.backup.currentIndex() < 0:
            QMessageBox.warning(self, "Restore", "Select a successful backup.")
            return
        reply = QMessageBox.warning(
            self,
            "Confirm restore",
            self.warning_box.toPlainText() + "\n\nProceed only if you understand this is a production change.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return
        window = self.window()
        password = self._ssh_password
        if hasattr(window, "ensure_password"):
            if not window.ensure_password():
                return
            password = getattr(window, "_ssh_password", password)
        engine = RestoreEngine(
            self._config,
            ssh=SSHClient(self._config, password=password or None),
        )
        try:
            result = engine.restore(
                self.backup.currentData(),
                confirmation=self.confirm.text(),
                action=self._action(),
                target_path=self.target.text().strip() or None,
                database=self.database.text().strip() or None,
            )
        except (RestoreError, SSHError) as exc:
            QMessageBox.critical(self, "Restore", str(exc))
            return
        QMessageBox.information(self, "Restore", str(result.get("message") or result))
