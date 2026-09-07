from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from app.config.schema import AppConfig
from app.logutil.logger import log_file_for_today


class LogsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: AppConfig | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("Logs")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.meta = QLabel("")
        layout.addWidget(self.meta)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        layout.addWidget(self.view)
        buttons = QHBoxLayout()
        refresh = QPushButton("Reload")
        refresh.clicked.connect(self.reload)
        open_folder = QPushButton("Open log folder")
        open_folder.clicked.connect(self._open_folder)
        buttons.addWidget(refresh)
        buttons.addWidget(open_folder)
        buttons.addStretch()
        layout.addLayout(buttons)

    def reload(self, config: AppConfig | None = None) -> None:
        if config:
            self._config = config
        if not self._config:
            return
        directory = Path(self._config.log_directory)
        path = log_file_for_today(directory)
        latest = path
        if directory.is_dir():
            logs = sorted(directory.glob("backup-*.log"))
            if logs:
                latest = logs[-1]
        self.meta.setText(str(latest))
        if latest.is_file():
            self.view.setPlainText(latest.read_text(encoding="utf-8", errors="replace")[-200000:])
        else:
            self.view.setPlainText("No log file yet.")

    def _open_folder(self) -> None:
        if not self._config:
            return
        window = self.window()
        if hasattr(window, "open_path"):
            window.open_path(self._config.log_directory)
