"""Settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from webcrawler.settings.manager import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._settings = settings

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.crawl_depth = QSpinBox()
        self.crawl_depth.setRange(1, 100)
        self.crawl_depth.setValue(settings.crawl_depth)

        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 100000)
        self.max_pages.setValue(settings.max_pages_per_site)

        self.timeout = QSpinBox()
        self.timeout.setRange(5, 600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(settings.download_timeout)

        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setValue(settings.worker_threads)

        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(settings.retry_attempts)

        self.user_agent = QLineEdit(settings.user_agent)
        self.file_types = QLineEdit(", ".join(settings.download_file_types))

        self.ignore_robots = QCheckBox("Ignore robots.txt")
        self.ignore_robots.setChecked(settings.ignore_robots_txt)
        self.follow_redirects = QCheckBox("Follow redirects")
        self.follow_redirects.setChecked(settings.follow_redirects)

        form.addRow("Crawl depth", self.crawl_depth)
        form.addRow("Max pages per website", self.max_pages)
        form.addRow("Download timeout", self.timeout)
        form.addRow("Worker threads", self.workers)
        form.addRow("Retry attempts", self.retries)
        form.addRow("User-Agent", self.user_agent)
        form.addRow("Download file types", self.file_types)
        layout.addLayout(form)

        checks = QHBoxLayout()
        checks.addWidget(self.ignore_robots)
        checks.addWidget(self.follow_redirects)
        layout.addLayout(checks)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_settings(self) -> AppSettings:
        types = [
            t.strip().lower().lstrip(".")
            for t in self.file_types.text().split(",")
            if t.strip()
        ]
        data = self._settings.to_dict()
        data.update(
            {
                "crawl_depth": self.crawl_depth.value(),
                "max_pages_per_site": self.max_pages.value(),
                "download_timeout": self.timeout.value(),
                "worker_threads": self.workers.value(),
                "retry_attempts": self.retries.value(),
                "user_agent": self.user_agent.text().strip() or self._settings.user_agent,
                "download_file_types": types or self._settings.download_file_types,
                "ignore_robots_txt": self.ignore_robots.isChecked(),
                "follow_redirects": self.follow_redirects.isChecked(),
            }
        )
        return AppSettings.from_dict(data)
