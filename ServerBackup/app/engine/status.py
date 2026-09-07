"""Dashboard status gathered without mutating production systems."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backup.lock import BackupLock
from app.backup.progress import ProgressReporter
from app.backup.retention import list_history, list_successful_backups
from app.config.schema import AppConfig
from app.config.store import load_state, runtime_dir
from app.utils.disk import drive_status
from app.utils.format import format_gb


def progress_path() -> Path:
    return runtime_dir() / "progress.json"


def collect_dashboard_status(config: AppConfig) -> dict[str, Any]:
    dest = Path(config.backup_destination)
    drive = drive_status(dest)
    lock = BackupLock(dest)
    progress = ProgressReporter(progress_path()).read()
    successful = list_successful_backups(dest)
    history = list_history(dest)
    last = history[0] if history else None
    state = load_state()
    last_status = (last or {}).get("status") or state.get("last_status") or "NEVER RUN"
    last_time = (last or {}).get("timestamp") or state.get("last_backup") or "—"
    last_size = (last or {}).get("size")
    if last_size is None:
        last_size_display = "—"
    elif isinstance(last_size, (int, float)):
        last_size_display = format_gb(last_size)
    else:
        last_size_display = str(last_size)
    next_auto = "—"
    if config.automatic_backup:
        next_auto = state.get("next_automatic_backup") or "Scheduled"
    return {
        "server_ip": config.server_ip,
        "connection": "UNKNOWN",
        "ssh": "UNKNOWN",
        "last_backup": last_time,
        "last_status": last_status,
        "last_size": last_size_display,
        "successful_backups": len(successful),
        "retention": config.retention_count,
        "drive": drive.path,
        "drive_exists": drive.exists,
        "total_space": format_gb(drive.total_bytes) if drive.exists else "—",
        "free_space": format_gb(drive.free_bytes) if drive.exists else "—",
        "used_space": format_gb(drive.used_bytes) if drive.exists else "—",
        "automatic_backup": "ON" if config.automatic_backup else "OFF",
        "next_automatic_backup": next_auto if config.automatic_backup else "—",
        "backup_running": lock.is_locked() or progress.get("status") == "running",
        "progress": progress,
        "destination": str(dest),
        "drive_error": drive.error,
    }
