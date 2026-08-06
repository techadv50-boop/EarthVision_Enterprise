"""Settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
        self.crawl_depth.setRange(1, 10000)
        self.crawl_depth.setValue(settings.crawl_depth)

        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 1000000)
        self.max_pages.setValue(settings.max_pages_per_site)

        self.timeout = QSpinBox()
        self.timeout.setRange(5, 600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(settings.download_timeout)

        self.page_workers = QSpinBox()
        self.page_workers.setRange(1, 64)
        self.page_workers.setValue(settings.page_workers)

        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
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
        self.complete_site = QCheckBox("Download complete website (no skips)")
        self.complete_site.setChecked(settings.download_complete_site)
        self.all_images = QCheckBox("Download all images")
        self.all_images.setChecked(settings.download_all_images)
        self.fresh_crawl = QCheckBox("Fresh crawl each Start (rebuild contacts)")
        self.fresh_crawl.setChecked(settings.fresh_site_crawl)
        self.pw_fallback = QCheckBox("Playwright fallback for JS/empty pages")
        self.pw_fallback.setChecked(settings.use_playwright_fallback)

        form.addRow("Crawl depth", self.crawl_depth)
        form.addRow("Max pages per website", self.max_pages)
        form.addRow("Download timeout", self.timeout)
        form.addRow("Page workers (speed)", self.page_workers)
        form.addRow("Download workers", self.workers)
        form.addRow("Retry attempts", self.retries)
        form.addRow("User-Agent", self.user_agent)
        form.addRow("Download file types", self.file_types)
        layout.addLayout(form)

        checks = QVBoxLayout()
        for widget in (
            self.ignore_robots,
            self.follow_redirects,
            self.complete_site,
            self.all_images,
            self.fresh_crawl,
            self.pw_fallback,
        ):
            checks.addWidget(widget)
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
                "page_workers": self.page_workers.value(),
                "worker_threads": self.workers.value(),
                "retry_attempts": self.retries.value(),
                "user_agent": self.user_agent.text().strip() or self._settings.user_agent,
                "download_file_types": types or self._settings.download_file_types,
                "ignore_robots_txt": self.ignore_robots.isChecked(),
                "follow_redirects": self.follow_redirects.isChecked(),
                "download_complete_site": self.complete_site.isChecked(),
                "download_all_images": self.all_images.isChecked(),
                "fresh_site_crawl": self.fresh_crawl.isChecked(),
                "use_playwright_fallback": self.pw_fallback.isChecked(),
            }
        )
        return AppSettings.from_dict(data)
