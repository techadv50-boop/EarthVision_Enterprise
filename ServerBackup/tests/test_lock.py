from pathlib import Path

from app.backup.lock import BackupAlreadyRunning, BackupLock
from tests.helpers import make_config


def test_lock_prevents_second_backup(tmp_path: Path):
    cfg = make_config(tmp_path)
    first = BackupLock(cfg.backup_destination)
    first.acquire(mode="manual", backup_id="a")
    second = BackupLock(cfg.backup_destination)
    try:
        second.acquire(mode="manual", backup_id="b")
        assert False, "second acquire should fail"
    except BackupAlreadyRunning as exc:
        assert "already in progress" in str(exc).lower()
    first.release()
    second.acquire(mode="manual", backup_id="b")
    second.release()


def test_scheduled_skip_message(tmp_path: Path):
    cfg = make_config(tmp_path)
    first = BackupLock(cfg.backup_destination)
    first.acquire(mode="manual", backup_id="a")
    scheduled = BackupLock(cfg.backup_destination)
    try:
        scheduled.acquire(mode="scheduled", backup_id="b")
        assert False, "scheduled acquire should fail"
    except BackupAlreadyRunning as exc:
        assert "Scheduled backup skipped" in str(exc)
    first.release()
