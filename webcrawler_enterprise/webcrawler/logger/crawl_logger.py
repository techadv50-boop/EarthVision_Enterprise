"""Crawl logging helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


# High-volume lines stay in crawl_log.txt. Sending every page to the
# window makes the interface freeze after many hours.
_GUI_QUIET_PREFIXES = (
    "Visited page:",
    "PDF harvest on ",
    "Queued ",
    "Contacts on ",
    "Scanned (not saved)",
    "Downloaded:",
    "Skipped:",
)


class CrawlLogger:
    """Write structured crawl events to crawl_log.txt and optional callback."""

    def __init__(
        self,
        log_path: Path | None = None,
        on_message: Callable[[str], None] | None = None,
    ) -> None:
        self.log_path = log_path
        self.on_message = on_message
        self._file = None
        self._logger = logging.getLogger("webcrawler")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def set_path(self, path: Path) -> None:
        self.log_path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._close_file()

    def close(self) -> None:
        self._close_file()

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def _emit(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] [{level}] {message}"
        if self.log_path:
            try:
                if self._file is None:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    self._file = open(self.log_path, "a", encoding="utf-8")
                self._file.write(line + "\n")
                self._file.flush()
            except Exception:
                self._close_file()
        if level == "ERROR":
            self._logger.error(message)
        elif level == "WARNING":
            self._logger.warning(message)
        else:
            self._logger.info(message)
        if self.on_message and not message.startswith(_GUI_QUIET_PREFIXES):
            self.on_message(line)

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def warning(self, message: str) -> None:
        self._emit("WARNING", message)

    def error(self, message: str) -> None:
        self._emit("ERROR", message)

    def page_visited(self, url: str, status: int | None = None) -> None:
        suffix = f" (HTTP {status})" if status is not None else ""
        self.info(f"Visited page: {url}{suffix}")

    def downloaded(self, url: str, path: str) -> None:
        self.info(f"Downloaded: {url} -> {path}")

    def skipped(self, url: str, reason: str) -> None:
        self.warning(f"Skipped: {url} ({reason})")
