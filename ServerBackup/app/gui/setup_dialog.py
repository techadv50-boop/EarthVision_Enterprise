"""First-run dialog: choose backup drive, then SSH key. Does not contact Ubuntu."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config.schema import AppConfig
from app.gui.folders import create_and_fill_ssh_key, drive_label, pick_backup_folder, pick_ssh_key
from app.ssh.keys import default_private_key_path
from app.utils.disk import backup_folder_for_drive, list_backup_drives


class DrivePickerDialog(QDialog):
    """Pick a Windows drive; returns G:\\ServerBackups."""

    def __init__(self, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.selected = ""
        self.setWindowTitle("Select backup drive")
        self.setModal(True)
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the drive where backups should be stored."))
        self.drives = QListWidget()
        current_root = Path(current or ".").anchor.rstrip("\\/").upper()
        for drive in list_backup_drives():
            item = QListWidgetItem(drive_label(drive.path, drive.free_bytes, drive.total_bytes))
            item.setData(Qt.ItemDataRole.UserRole, drive.path)
            self.drives.addItem(item)
            if drive.path.rstrip("\\/").upper() == current_root:
                self.drives.setCurrentItem(item)
        if self.drives.count() and self.drives.currentRow() < 0:
            self.drives.setCurrentRow(0)
        self.drives.itemDoubleClicked.connect(lambda *_: self._accept())
        layout.addWidget(self.drives)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        item = self.drives.currentItem()
        if not item:
            QMessageBox.warning(self, "Select backup drive", "Select a drive from the list.")
            return
        self.selected = backup_folder_for_drive(str(item.data(Qt.ItemDataRole.UserRole)))
        self.accept()


class SetupDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Select backup drive")
        self.setModal(True)
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        title = QLabel("Select backup drive")
        title.setObjectName("title")
        layout.addWidget(title)
        help_text = QLabel(
            "Choose the backup drive, then enter the Ubuntu SSH password for zhzh. "
            "The password is not saved. Automatic backup stays OFF. "
            "Nginx, PHP-FPM, and MariaDB are not contacted by this step."
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("subtitle")
        layout.addWidget(help_text)

        layout.addWidget(QLabel("Available drives"))
        self.drives = QListWidget()
        self.drives.itemClicked.connect(self._apply_selected_drive)
        layout.addWidget(self.drives)

        dest_row = QHBoxLayout()
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(r"G:\ServerBackups")
        self.destination.setClearButtonEnabled(True)
        browse_dest = QPushButton("Browse folder…")
        browse_dest.clicked.connect(self._browse_folder)
        dest_row.addWidget(self.destination)
        dest_row.addWidget(browse_dest)
        form = QFormLayout()
        form.addRow("Backup folder", dest_row)

        key_row = QHBoxLayout()
        self.ssh_key = QLineEdit()
        self.ssh_key.setPlaceholderText(str(default_private_key_path()))
        self.ssh_key.setClearButtonEnabled(True)
        browse_key = QPushButton("Browse key…")
        browse_key.clicked.connect(self._browse_key)
        create_key = QPushButton("Create SSH key")
        create_key.clicked.connect(self._create_key)
        key_row.addWidget(self.ssh_key)
        key_row.addWidget(browse_key)
        key_row.addWidget(create_key)
        form.addRow("SSH private key", key_row)

        self.server_ip = QLineEdit()
        self.server_ip.setClearButtonEnabled(True)
        self.ssh_username = QLineEdit()
        self.ssh_username.setClearButtonEnabled(True)
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_password = QLineEdit()
        self.ssh_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_password.setPlaceholderText("Ubuntu SSH password (not saved)")
        self.ssh_password.setClearButtonEnabled(True)
        form.addRow("Ubuntu server IP", self.server_ip)
        form.addRow("SSH username", self.ssh_username)
        form.addRow("SSH port", self.ssh_port)
        form.addRow("Ubuntu password", self.ssh_password)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        continue_btn = buttons.addButton("Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        continue_btn.setObjectName("primary")
        buttons.addButton("Skip for now", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load(config)
        self._fill_drives()

    def _load(self, config: AppConfig) -> None:
        self.destination.setText(config.backup_destination)
        self.ssh_key.setText(config.ssh_private_key_path)
        if not self.ssh_key.text().strip() and default_private_key_path().is_file():
            self.ssh_key.setText(str(default_private_key_path()))
        self.server_ip.setText(config.server_ip)
        self.ssh_username.setText(config.ssh_username or "zhzh")
        self.ssh_port.setValue(int(config.ssh_port))

    def _fill_drives(self) -> None:
        self.drives.clear()
        current = Path(self.destination.text().strip() or ".")
        current_root = str(current.anchor or current).rstrip("\\/").upper()
        for drive in list_backup_drives():
            item = QListWidgetItem(drive_label(drive.path, drive.free_bytes, drive.total_bytes))
            item.setData(Qt.ItemDataRole.UserRole, drive.path)
            self.drives.addItem(item)
            root = drive.path.rstrip("\\/").upper()
            if root == current_root:
                self.drives.setCurrentItem(item)
        if self.drives.count() and self.drives.currentRow() < 0:
            self.drives.setCurrentRow(0)

    def _apply_selected_drive(self) -> None:
        item = self.drives.currentItem()
        if not item:
            return
        root = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not root:
            return
        self.destination.setText(backup_folder_for_drive(root))

    def _browse_folder(self) -> None:
        chosen = pick_backup_folder(self, self.destination.text().strip())
        if chosen:
            self.destination.setText(chosen)

    def _browse_key(self) -> None:
        chosen = pick_ssh_key(self, self.ssh_key.text().strip())
        if chosen:
            self.ssh_key.setText(chosen)

    def _create_key(self) -> None:
        create_and_fill_ssh_key(
            self,
            self.ssh_key,
            self.ssh_username.text().strip() or "zhzh",
            self.server_ip.text().strip() or "192.168.18.18",
        )

    def _accept(self) -> None:
        dest = self.destination.text().strip()
        if not dest:
            QMessageBox.warning(self, "Select backup drive", "Choose a backup drive or folder.")
            return
        key = self.ssh_key.text().strip()
        if key and not Path(os_expand(key)).is_file():
            QMessageBox.warning(self, "SSH private key", f"Key file not found:\n{key}")
            return
        if not key and not self.ssh_password.text():
            QMessageBox.warning(
                self,
                "Ubuntu login",
                "Enter the Ubuntu password, or click Create SSH key.",
            )
            return
        self.accept()

    def ubuntu_password(self) -> str:
        return self.ssh_password.text()

    def apply_to(self, config: AppConfig) -> AppConfig:
        config.backup_destination = self.destination.text().strip()
        config.ssh_private_key_path = self.ssh_key.text().strip()
        config.server_ip = self.server_ip.text().strip()
        config.ssh_username = self.ssh_username.text().strip()
        config.ssh_port = self.ssh_port.value()
        config.setup_completed = True
        return config


def os_expand(path: str) -> str:
    from os.path import expanduser, expandvars

    return expandvars(expanduser(path))
