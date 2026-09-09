"""Dashboard status gathered without mutating production systems.

Refresh and status collection are local-only: they read lock, progress,
history, and disk files. They never open SSH.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.backup.live import is_backup_operation, show_live_backup_panel
from app.backup.lock import BackupLock
from app.backup.progress import ProgressReporter, idle_progress_payload
from app.backup.retention import list_history, list_successful_backups
from app.config.schema import AppConfig
from app.config.store import load_state, runtime_dir
from app.master.health import assess_health
from app.master.store import MasterStore
from app.utils.disk import drive_status
from app.utils.format import format_gb


def progress_path() -> Path:
    return runtime_dir() / "progress.json"


def live_dashboard_message(progress: Mapping[str, Any] | None, *, running: bool) -> str:
    """Banner text for the dashboard.

    Leftover progress.json from an earlier process is never shown as live
    status. Only the current running operation updates this banner.
    """
    data = dict(progress or {})
    if running:
        return str(data.get("message") or "BACKUP IN PROGRESS")
    return "Ready."


def master_idle_facts(config: AppConfig) -> dict[str, Any]:
    store = MasterStore(config.backup_destination)
    meta = store.load_meta()
    generation = store.head_generation()
    size = int(meta.get("master_bytes") or meta.get("source_bytes") or 0)
    if generation is None:
        head = "MISSING"
    else:
        head = str(generation)
    return {"current_size": size, "head_state": head, "generation": generation}


def clear_stale_progress(config: AppConfig) -> bool:
    """Normalize leftover runtime state to IDLE when no backup lock is held."""
    return normalize_startup_progress(config)


def normalize_startup_progress(config: AppConfig) -> bool:
    """Crash recovery is not implemented: leftover RUNNING/PREPARING/CANCELLED become IDLE."""
    if BackupLock(config.backup_destination).is_locked():
        return False
    reporter = ProgressReporter(progress_path())
    data = reporter.read()
    facts = master_idle_facts(config)
    last_result = None
    if isinstance(data.get("last_result"), dict):
        last_result = data.get("last_result")
    elif str(data.get("status") or "").lower() in {"failed", "cancelled", "success"}:
        last_result = {
            "status": data.get("status"),
            "message": data.get("message"),
            "error": data.get("error"),
            "operation_id": data.get("operation_id") or data.get("backup_id"),
            "head_state": data.get("head_state"),
        }
    reporter.reset_idle(
        master_size=int(facts["current_size"] or 0),
        head_state=str(facts["head_state"]),
        last_result=last_result,
    )
    return True


def format_discovery_count(value: Any, *, zero_as_dash: bool = False) -> str:
    """Render dashboard discovery counts. 0 must not become an em dash except when requested."""
    if value is None or value == "":
        return "—"
    try:
        number = int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else "—"
    if zero_as_dash and number == 0:
        return "—"
    return str(number)


def collect_dashboard_status(config: AppConfig) -> dict[str, Any]:
    dest = Path(config.backup_destination)
    drive = drive_status(dest)
    lock = BackupLock(dest)
    progress = ProgressReporter(progress_path()).read()
    lock_held = lock.is_locked()
    file_running = str(progress.get("status") or "").lower() == "running"
    running = lock_held and (file_running or is_backup_operation(progress) or str(progress.get("kind") or "") == "dry_run")
    if not lock_held:
        running = False
    facts = master_idle_facts(config)
    successful = list_successful_backups(dest)
    history = list_history(dest)
    last = history[0] if history else None
    state = load_state()
    master = _master_status(config)
    store = MasterStore(dest)
    master_history = store.list_history()
    last_master = master_history[0] if master_history else None
    last_status = (
        (last_master or {}).get("status")
        or (last or {}).get("status")
        or state.get("last_status")
        or "NEVER RUN"
    )
    last_time = (
        (last_master or {}).get("timestamp")
        or (last or {}).get("timestamp")
        or state.get("last_backup")
        or "—"
    )
    last_size = (last_master or {}).get("bytes_transferred")
    if last_size is None:
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
        "retention": "master (no keep-5)",
        "master_status": master.get("status"),
        "master_generation": master.get("generation"),
        "master_detail": master.get("detail"),
        "master_type": master.get("last_type"),
        "master_ojs": master.get("ojs"),
        "master_updated": master.get("updated_at"),
        "drive": drive.path,
        "drive_exists": drive.exists,
        "total_space": format_gb(drive.total_bytes) if drive.exists else "—",
        "free_space": format_gb(drive.free_bytes) if drive.exists else "—",
        "used_space": format_gb(drive.used_bytes) if drive.exists else "—",
        "automatic_backup": "ON" if config.automatic_backup else "OFF",
        "next_automatic_backup": next_auto if config.automatic_backup else "—",
        "backup_running": running,
        "show_live_panel": show_live_backup_panel(progress, running=running),
        "live_message": live_dashboard_message(progress, running=running),
        "progress": progress if running else idle_progress_payload(
            master_size=int(facts["current_size"] or 0),
            head_state=str(facts["head_state"]),
            last_result=progress.get("last_result") if isinstance(progress.get("last_result"), dict) else None,
        ),
        "master_bytes": facts["current_size"],
        "head_label": facts["head_state"],
        "destination": str(dest),
        "drive_error": drive.error,
        **_discovery_status(config),
        **_security_status(config),
    }


def _discovery_status(config: AppConfig) -> dict[str, Any]:
    snap: dict[str, Any] = {}
    apps: list[dict[str, Any]] = []
    try:
        from app.discover.gate import assess_backup_gate
        from app.discover.policy import apply_policy, load_snapshot

        snap = load_snapshot(config.backup_destination)
        apps = apply_policy(list(snap.get("applications") or []), config.backup_destination)
    except Exception:
        return {
            "discovered_total": None,
            "discovered_approved": None,
            "discovered_review": None,
            "discovered_removed": None,
        }
    if not apps:
        return {
            "discovered_total": None,
            "discovered_approved": None,
            "discovered_review": None,
            "discovered_removed": None,
        }
    gate = assess_backup_gate(apps, list(snap.get("database_inventory") or []))
    return {
        "discovered_total": gate.get("applications_discovered", 0),
        "discovered_approved": gate.get("applications_approved", 0),
        "discovered_review": gate.get("applications_pending", 0),
        "discovered_removed": sum(1 for row in apps if row.get("change") == "removed"),
    }


def _master_status(config: AppConfig) -> dict[str, Any]:
    store = MasterStore(config.backup_destination)
    health = assess_health(store, deep=False)
    meta = store.load_meta()
    history = store.list_history()
    last = history[0] if history else {}
    ojs = meta.get("ojs") or []
    ojs_text = ", ".join(
        f"{item.get('domain')}:{item.get('files_dir')}" for item in ojs if isinstance(item, dict)
    )
    return {
        "status": health.get("status"),
        "generation": health.get("generation"),
        "detail": health.get("detail"),
        "last_type": last.get("type") or meta.get("last_type"),
        "updated_at": meta.get("updated_at") or last.get("timestamp"),
        "ojs": ojs_text or "—",
    }


def _security_status(config: AppConfig) -> dict[str, Any]:
    try:
        from app.serversec.snapshot import SecurityStore

        store = SecurityStore(config.security_store)
        latest = store.latest_id()
        report = store.load_report(latest) if latest else None
    except Exception:
        latest = None
        report = None
    return {
        "security_mode": config.security_mode,
        "last_security_check": (report or {}).get("timestamp") or latest or "NEVER RUN",
        "security_overall": (report or {}).get("overall") or "NEVER RUN",
        "security_layer1": (report or {}).get("layer1") or "—",
        "security_layer2": (report or {}).get("layer2") or "—",
        "security_layer3": (report or {}).get("layer3") or "—",
    }
