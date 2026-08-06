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


def app_data_dir() -> Path:
    """Return platform-appropriate application data directory."""
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "WebCrawlerEnterprise"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    crawl_depth: int = 10
    max_pages_per_site: int = 500
    download_timeout: int = 60
    worker_threads: int = 4
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
    page_timeout_ms: int = 30000
    respect_same_host_only: bool = True

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
