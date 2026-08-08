"""Application settings with automatic persistence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


DEFAULT_FILE_TYPES = [
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "csv",
    "txt",
    "zip",
]


# Isolated from older installs that used plain "WebCrawlerEnterprise".
# Do not rename back — that would reopen the old password/URL/queue database.
APP_DATA_FOLDER = "WebCrawlerEnterprise_v2"
LEGACY_APP_DATA_FOLDER = "WebCrawlerEnterprise"


def app_data_dir() -> Path:
    """Return THIS build's private data directory (never the legacy folder)."""
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_DATA_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_app_data_dir() -> Path:
    """Old program data folder — read-only reference; never used for storage."""
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / LEGACY_APP_DATA_FOLDER


@dataclass
class AppSettings:
    crawl_depth: int = 10000
    max_pages_per_site: int = 250000
    download_timeout: int = 45
    # Defaults tuned for deep site-wide contact discovery.
    worker_threads: int = 12
    page_workers: int = 16
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 WebCrawlerEnterprise/1.0"
    )
    download_file_types: list[str] = field(default_factory=lambda: list(DEFAULT_FILE_TYPES))
    ignore_robots_txt: bool = False
    follow_redirects: bool = True
    retry_attempts: int = 3
    output_folder: str = ""
    last_urls: str = ""
    page_timeout_ms: int = 20000
    respect_same_host_only: bool = True
    # Download every reachable internal page, document, and image; rebuild contact files.
    download_complete_site: bool = True
    download_all_images: bool = True
    # Light mode: crawl every page/PDF/doc for emails & phones only — do not save files.
    contact_scan_only: bool = True
    # False = resume unfinished site instead of wiping progress (needed for long runs).
    fresh_site_crawl: bool = False
    # Playwright only for thin/failed pages; capped for stability.
    use_playwright_fallback: bool = True
    max_playwright_fallback: int = 100
    request_pause_ms: int = 0
    max_download_queue: int = 1000
    max_download_bytes: int = 80 * 1024 * 1024

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class SettingsManager:
    """Load and save settings to JSON under the app data directory."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "settings.json")
        self.settings = AppSettings()
        self.load()

    def load(self) -> AppSettings:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.settings = AppSettings.from_dict(data)
            except (json.JSONDecodeError, TypeError, ValueError):
                self.settings = AppSettings()
        return self.settings

    def save(self, settings: AppSettings | None = None) -> None:
        if settings is not None:
            self.settings = settings
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.settings.to_dict(), indent=2),
            encoding="utf-8",
        )

    def update(self, **kwargs: Any) -> AppSettings:
        data = self.settings.to_dict()
        data.update(kwargs)
        self.settings = AppSettings.from_dict(data)
        self.save()
        return self.settings
