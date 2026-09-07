"""File logging with secret redaction. Never logs passwords or private keys."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.security.redact import redact_secrets


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_secrets(original)


class BackupLogger:
    def __init__(self, log_directory: str | Path, backup_id: str | None = None) -> None:
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        stamp = backup_id or datetime.now().strftime("%Y-%m-%d")
        self.path = self.log_directory / f"backup-{stamp}.log"
        self.logger = logging.getLogger(f"serverbackup.{stamp}.{id(self)}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.handlers.clear()
        handler = logging.FileHandler(self.path, encoding="utf-8")
        handler.setFormatter(
            RedactingFormatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        self.logger.addHandler(handler)
        stream = logging.StreamHandler()
        stream.setFormatter(
            RedactingFormatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        self.logger.addHandler(stream)

    def info(self, message: str) -> None:
        self.logger.info(redact_secrets(message))

    def warning(self, message: str) -> None:
        self.logger.warning(redact_secrets(message))

    def error(self, message: str) -> None:
        self.logger.error(redact_secrets(message))

    def debug(self, message: str) -> None:
        self.logger.debug(redact_secrets(message))

    def close(self) -> None:
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)


def log_file_for_today(log_directory: str | Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Path(log_directory) / f"backup-{stamp}.log"


def get_logger(log_directory: str | Path, backup_id: str | None = None) -> BackupLogger:
    return BackupLogger(log_directory, backup_id)


def prune_logs(log_directory: str | Path, retention_days: int) -> int:
    directory = Path(log_directory)
    if not directory.is_dir() or retention_days < 1:
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob("backup-*.log"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed
