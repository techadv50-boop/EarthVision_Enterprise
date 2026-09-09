from pathlib import Path

from app.backup.lock import BackupLock
from app.backup.progress import ProgressReporter
from app.config.store import runtime_dir
from app.engine.backup_engine import BackupEngine
from app.engine.status import (
    clear_stale_progress,
    collect_dashboard_status,
    live_dashboard_message,
    progress_path,
)
from tests.helpers import FakeSSH, make_config

STALE_TIMEOUT = "SSH connection timed out."


def _write_progress(**updates) -> dict:
    return ProgressReporter(progress_path()).write(**updates)


def test_stale_timeout_is_not_live_when_no_backup_is_running():
    message = live_dashboard_message(
        {"status": "failed", "message": STALE_TIMEOUT},
        running=False,
    )
    assert message == "Ready."
    assert STALE_TIMEOUT not in message


def test_live_timeout_still_shows_while_backup_lock_is_held():
    message = live_dashboard_message(
        {"status": "running", "message": STALE_TIMEOUT},
        running=True,
    )
    assert message == STALE_TIMEOUT


def test_successful_backup_message_remains_when_idle():
    message = live_dashboard_message(
        {"status": "success", "message": "BACKUP COMPLETED SUCCESSFULLY"},
        running=False,
    )
    assert message == "BACKUP COMPLETED SUCCESSFULLY"


def test_dashboard_status_ignores_stale_failed_progress(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(status="failed", message=STALE_TIMEOUT, error=STALE_TIMEOUT)
    status = collect_dashboard_status(cfg)
    assert status["backup_running"] is False
    assert status["live_message"] == "Ready."
    assert status["progress"]["message"] == STALE_TIMEOUT


def test_dashboard_status_does_not_treat_orphan_running_progress_as_live(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(status="running", message=STALE_TIMEOUT)
    status = collect_dashboard_status(cfg)
    assert status["backup_running"] is False
    assert status["live_message"] == "Ready."


def test_dashboard_status_shows_progress_only_when_lock_is_held(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(status="running", message="Connecting to Ubuntu…")
    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="test")
    try:
        status = collect_dashboard_status(cfg)
        assert status["backup_running"] is True
        assert status["live_message"] == "Connecting to Ubuntu…"
    finally:
        lock.release()


def test_clear_stale_progress_after_successful_test_connection(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(status="failed", message=STALE_TIMEOUT, error=STALE_TIMEOUT)
    assert clear_stale_progress(cfg) is True
    leftover = ProgressReporter(progress_path()).read()
    assert leftover["status"] == "idle"
    assert leftover["message"] == "Ready."
    assert leftover.get("error") is None
    status = collect_dashboard_status(cfg)
    assert status["live_message"] == "Ready."


def test_clear_stale_progress_does_not_touch_a_live_backup(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(status="running", message="Transferring backup…")
    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="test")
    try:
        assert clear_stale_progress(cfg) is False
        leftover = ProgressReporter(progress_path()).read()
        assert leftover["message"] == "Transferring backup…"
        assert leftover["status"] == "running"
    finally:
        lock.release()


def test_backup_failure_stays_visible_without_lock(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(
        status="failed",
        operation="BACKUP — FULL MASTER BASELINE",
        ui_stage="FAILED",
        message="BACKUP FAILED",
        error="SSH connection timed out.",
        head_state="UNCHANGED",
    )
    status = collect_dashboard_status(cfg)
    assert status["backup_running"] is False
    assert status["show_live_panel"] is True
    assert "SSH connection timed out." in status["live_message"]


def test_clear_stale_progress_does_not_erase_backup_failure(tmp_path: Path):
    cfg = make_config(tmp_path)
    _write_progress(
        status="failed",
        operation="BACKUP",
        ui_stage="FAILED",
        message="BACKUP FAILED",
        error="worker crashed",
    )
    assert clear_stale_progress(cfg) is False
    leftover = ProgressReporter(progress_path()).read()
    assert leftover["status"] == "failed"
    assert leftover["error"] == "worker crashed"


def test_test_connection_does_not_write_progress(tmp_path: Path):
    cfg = make_config(tmp_path)
    reporter = ProgressReporter(runtime_dir() / "progress.json")
    reporter.write(status="failed", message=STALE_TIMEOUT, error=STALE_TIMEOUT)
    result = BackupEngine(cfg, ssh=FakeSSH()).test_connection()
    assert result["login"] is True
    assert result["script"] is True
    leftover = reporter.read()
    assert leftover["message"] == STALE_TIMEOUT
    assert leftover["status"] == "failed"
