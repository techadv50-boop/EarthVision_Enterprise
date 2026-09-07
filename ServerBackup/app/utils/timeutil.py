"""Timestamped backup IDs: YYYY-MM-DD_HHMMSS."""

from __future__ import annotations

from datetime import datetime

BACKUP_ID_FORMAT = "%Y-%m-%d_%H%M%S"


def backup_id_now(when: datetime | None = None) -> str:
    stamp = when or datetime.now()
    return stamp.strftime(BACKUP_ID_FORMAT)


def parse_backup_id(backup_id: str) -> datetime:
    return datetime.strptime(backup_id, BACKUP_ID_FORMAT)
