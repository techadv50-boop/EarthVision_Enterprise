"""GUI manual BACKUP NOW must use Paramiko with an in-memory password."""

from __future__ import annotations

MANUAL_BACKUP_NEED_PASSWORD = "Please run TEST CONNECTION first."


def manual_backup_password_error(password: str | None) -> str | None:
    """Return a preflight error if GUI BACKUP NOW must not start."""
    if not str(password or "").strip():
        return MANUAL_BACKUP_NEED_PASSWORD
    return None
