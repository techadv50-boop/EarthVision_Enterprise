from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import AppConfig, SYSTEM_DATABASES
from app.config.store import save_config
from app.database.discover import discover_databases
from app.gui.folders import create_and_fill_ssh_key, pick_backup_folder, pick_existing_folder, pick_ssh_key
from app.gui.setup_dialog import DrivePickerDialog
from app.scheduler.tasks import disable_schedule, enable_schedule
from app.ssh.client import SSHError
from app.ssh.keys import default_private_key_path


def _editable(widget: QLineEdit, placeholder: str = "") -> QLineEdit:
    widget.setReadOnly(False)
    widget.setEnabled(True)
    widget.setClearButtonEnabled(True)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if placeholder:
        widget.setPlaceholderText(placeholder)
    return widget


class SettingsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        heading = QLabel("Settings")
        heading.setObjectName("title")
        layout.addWidget(heading)
        hint = QLabel(
            "Type in the boxes below, or use Browse / Choose drive. "
            "The dashboard is read-only. Click Save settings when finished."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.server_ip = _editable(QLineEdit(), "192.168.18.18")
        self.ssh_username = _editable(QLineEdit(), "zhzh")
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_key = _editable(QLineEdit(), str(default_private_key_path()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_key)
        create_key = QPushButton("Create SSH key")
        create_key.clicked.connect(self._create_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.ssh_key)
        key_row.addWidget(browse)
        key_row.addWidget(create_key)
        self.destination = _editable(QLineEdit(), r"G:\ServerBackups")
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.destination)
        dest_browse = QPushButton("Browse folder…")
        dest_browse.clicked.connect(self._browse_destination)
        dest_drive = QPushButton("Choose drive…")
        dest_drive.clicked.connect(self._choose_drive)
        dest_row.addWidget(dest_browse)
        dest_row.addWidget(dest_drive)
        self.log_directory = _editable(QLineEdit(), r"C:\ServerBackup\Logs")
        log_row = QHBoxLayout()
        log_row.addWidget(self.log_directory)
        log_browse = QPushButton("Browse…")
        log_browse.clicked.connect(self._browse_logs)
        log_row.addWidget(log_browse)
        self.retention = QSpinBox()
        self.retention.setRange(1, 100)
        self.retry_count = QSpinBox()
        self.retry_count.setRange(1, 10)
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(1, 600)
        self.min_free = QDoubleSpinBox()
        self.min_free.setRange(1.0, 1000.0)
        self.min_remote = QDoubleSpinBox()
        self.min_remote.setRange(0.5, 1000.0)
        self.compression = QSpinBox()
        self.compression.setRange(1, 9)
        self.websites = QListWidget()
        self.websites.setMinimumHeight(90)
        self.extra = QListWidget()
        self.extra.setMinimumHeight(70)
        self.databases = QListWidget()
        self.databases.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.log_retention = QSpinBox()
        self.log_retention.setRange(1, 3650)
        self.automatic = QCheckBox("Automatic Backup (OFF by default)")
        self.schedule_type = QComboBox()
        self.schedule_type.addItems(["daily", "weekly", "custom"])
        self.schedule_time = _editable(QLineEdit(), "02:00")
        self.schedule_weekday = QComboBox()
        self.schedule_weekday.addItems(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        )
        form.addRow("Ubuntu server IP", self.server_ip)
        form.addRow("SSH username", self.ssh_username)
        form.addRow("SSH port", self.ssh_port)
        form.addRow("SSH private key path", key_row)
        form.addRow("Backup destination", dest_row)
        form.addRow("Log directory", log_row)
        form.addRow("Retention count", self.retention)
        form.addRow("Retry count", self.retry_count)
        form.addRow("Retry delay (seconds)", self.retry_delay)
        form.addRow("Minimum free disk (GB)", self.min_free)
        form.addRow("Minimum Ubuntu temp space (GB)", self.min_remote)
        form.addRow("Compression level", self.compression)
        form.addRow("Website directories", self.websites)
        self.website_input = _editable(QLineEdit(), "/var/www/example.com")
        website_btns = QHBoxLayout()
        website_btns.addWidget(self.website_input)
        add_site = QPushButton("Add path")
        add_site.clicked.connect(lambda: self._add_typed(self.website_input, self.websites))
        self.website_input.returnPressed.connect(lambda: self._add_typed(self.website_input, self.websites))
        remove_site = QPushButton("Remove selected")
        remove_site.clicked.connect(lambda: self._remove_selected(self.websites))
        website_btns.addWidget(add_site)
        website_btns.addWidget(remove_site)
        form.addRow("Add website path", website_btns)
        self.ojs = _editable(QLineEdit(), "/var/www/ojs-files")
        form.addRow("OJS private-files directory", self.ojs)
        self.nginx = _editable(QLineEdit(), "/etc/nginx")
        form.addRow("Nginx directory", self.nginx)
        form.addRow("Additional directories", self.extra)
        self.extra_input = _editable(QLineEdit(), "/absolute/unix/path")
        extra_btns = QHBoxLayout()
        extra_btns.addWidget(self.extra_input)
        add_extra = QPushButton("Add path")
        add_extra.clicked.connect(lambda: self._add_typed(self.extra_input, self.extra))
        self.extra_input.returnPressed.connect(lambda: self._add_typed(self.extra_input, self.extra))
        remove_extra = QPushButton("Remove selected")
        remove_extra.clicked.connect(lambda: self._remove_selected(self.extra))
        extra_btns.addWidget(add_extra)
        extra_btns.addWidget(remove_extra)
        form.addRow("Add additional path", extra_btns)
        form.addRow("Selected databases", self.databases)
        discover = QPushButton("DISCOVER DATABASES")
        discover.clicked.connect(self._discover)
        form.addRow("", discover)
        form.addRow("Log retention (days)", self.log_retention)
        form.addRow(self.automatic)
        form.addRow("Schedule type", self.schedule_type)
        form.addRow("Schedule time (HH:MM)", self.schedule_time)
        form.addRow("Weekly day", self.schedule_weekday)
        self.security_mode = QComboBox()
        self.security_mode.addItems(["LOW", "BALANCED", "HIGH", "CRITICAL"])
        form.addRow("Security mode (default BALANCED, audit-only)", self.security_mode)
        layout.addLayout(form)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def load_config(self, config: AppConfig) -> None:
        self._config = config
        self.server_ip.setText(config.server_ip)
        self.ssh_username.setText(config.ssh_username)
        self.ssh_port.setValue(config.ssh_port)
        self.ssh_key.setText(config.ssh_private_key_path)
        if not self.ssh_key.text().strip() and default_private_key_path().is_file():
            self.ssh_key.setText(str(default_private_key_path()))
        self.destination.setText(config.backup_destination)
        self.log_directory.setText(config.log_directory)
        self.retention.setValue(config.retention_count)
        self.retry_count.setValue(config.retry_count)
        self.retry_delay.setValue(config.retry_delay_seconds)
        self.min_free.setValue(config.min_free_disk_gb)
        self.min_remote.setValue(config.min_remote_free_disk_gb)
        self.compression.setValue(config.compression_level)
        self.websites.clear()
        self.websites.addItems(config.website_directories)
        self.ojs.setText(config.ojs_private_files)
        self.nginx.setText(config.nginx_directory)
        self.extra.clear()
        self.extra.addItems(config.extra_directories)
        self._fill_databases(config.selected_databases)
        self.log_retention.setValue(config.log_retention_days)
        self.automatic.setChecked(config.automatic_backup)
        self.schedule_type.setCurrentText(config.schedule_type)
        self.schedule_time.setText(config.schedule_time)
        self.schedule_weekday.setCurrentText(config.schedule_weekday)
        self.security_mode.setCurrentText(config.security_mode)

    def current_config(self) -> AppConfig:
        cfg = self._config or AppConfig()
        cfg.server_ip = self.server_ip.text().strip()
        cfg.ssh_username = self.ssh_username.text().strip()
        cfg.ssh_port = self.ssh_port.value()
        cfg.ssh_private_key_path = self.ssh_key.text().strip()
        cfg.backup_destination = self.destination.text().strip()
        cfg.log_directory = self.log_directory.text().strip()
        cfg.retention_count = self.retention.value()
        cfg.retry_count = self.retry_count.value()
        cfg.retry_delay_seconds = self.retry_delay.value()
        cfg.min_free_disk_gb = float(self.min_free.value())
        cfg.min_remote_free_disk_gb = float(self.min_remote.value())
        cfg.compression_level = self.compression.value()
        cfg.website_directories = [self.websites.item(i).text() for i in range(self.websites.count())]
        cfg.ojs_private_files = self.ojs.text().strip()
        cfg.nginx_directory = self.nginx.text().strip()
        cfg.extra_directories = [self.extra.item(i).text() for i in range(self.extra.count())]
        cfg.selected_databases = [
            self.databases.item(i).text().split(" ", 1)[0]
            for i in range(self.databases.count())
            if self.databases.item(i).checkState() == Qt.CheckState.Checked
        ]
        cfg.log_retention_days = self.log_retention.value()
        cfg.automatic_backup = self.automatic.isChecked()
        cfg.schedule_type = self.schedule_type.currentText()
        cfg.schedule_time = self.schedule_time.text().strip()
        cfg.schedule_weekday = self.schedule_weekday.currentText()
        cfg.security_mode = self.security_mode.currentText()
        if cfg.backup_destination:
            cfg.setup_completed = True
        return cfg

    def _fill_databases(self, selected: list[str]) -> None:
        self.databases.clear()
        names = list(selected)
        for name in names:
            self._add_db_item(name, checked=True)

    def _add_db_item(self, name: str, checked: bool) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        label = name
        if name in SYSTEM_DATABASES:
            label = f"{name} (system)"
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.databases.addItem(item)

    def _browse_key(self) -> None:
        path = pick_ssh_key(self, self.ssh_key.text().strip())
        if path:
            self.ssh_key.setText(path)

    def _create_key(self) -> None:
        create_and_fill_ssh_key(
            self,
            self.ssh_key,
            self.ssh_username.text().strip() or "zhzh",
            self.server_ip.text().strip() or "192.168.18.18",
        )

    def _browse_destination(self) -> None:
        path = pick_backup_folder(self, self.destination.text().strip())
        if path:
            self.destination.setText(path)

    def _choose_drive(self) -> None:
        dialog = DrivePickerDialog(self.destination.text().strip(), self)
        if dialog.exec() and dialog.selected:
            self.destination.setText(dialog.selected)

    def _browse_logs(self) -> None:
        path = pick_existing_folder(self, self.log_directory.text().strip(), "Select log folder")
        if path:
            self.log_directory.setText(path)

    def _add_typed(self, source: QLineEdit, widget: QListWidget) -> None:
        text = source.text().strip()
        if not text:
            return
        widget.addItem(text)
        source.clear()

    def _add_item(self, widget: QListWidget, title: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, title, "Absolute Unix path:")
        if ok and text.strip():
            widget.addItem(text.strip())

    def _remove_selected(self, widget: QListWidget) -> None:
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))

    def _discover(self) -> None:
        from app.gui.password import prompt_ubuntu_password
        from app.ssh.client import SSHClient

        cfg = self.current_config()
        password = prompt_ubuntu_password(self, cfg.ssh_username, cfg.server_ip)
        if password is None:
            return
        try:
            rows = discover_databases(cfg, client=SSHClient(cfg, password=password or None))
        except SSHError as exc:
            QMessageBox.warning(self, "Discover databases", str(exc))
            return
        self.databases.clear()
        for row in rows:
            default = (not row["system"]) or row["name"] in cfg.selected_databases
            self._add_db_item(str(row["name"]), checked=bool(default and not row["system"]))

    def _save(self) -> None:
        cfg = self.current_config()
        save_config(cfg)
        self._config = cfg
        try:
            if cfg.automatic_backup:
                enable_schedule(cfg)
            else:
                disable_schedule()
        except RuntimeError as exc:
            QMessageBox.information(
                self,
                "Scheduling",
                f"Settings saved. Scheduling could not be applied here: {exc}",
            )
            return
        QMessageBox.information(self, "Settings", "Settings saved.")
