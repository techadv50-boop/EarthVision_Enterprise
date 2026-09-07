from pathlib import Path

from app.engine.backup_engine import BackupCancelled, BackupEngine, BackupError
from app.backup.retention import list_successful_backups
from tests.helpers import FakeSSH, make_config, make_valid_archive, write_success_backup


def _seed_five(dest: Path) -> list[str]:
    ids = [
        "2026-09-01_010000",
        "2026-09-02_010000",
        "2026-09-03_010000",
        "2026-09-04_010000",
        "2026-09-05_010000",
    ]
    for backup_id in ids:
        write_success_backup(dest, backup_id)
    return ids


def test_successful_backup_and_retention(tmp_path: Path):
    cfg = make_config(tmp_path)
    dest = Path(cfg.backup_destination)
    ids = _seed_five(dest)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    engine.backup_id = "2026-09-06_010000"

    def transfer(archive: Path) -> int:
        make_valid_archive(archive, databases=cfg.selected_databases)
        return archive.stat().st_size

    engine.transfer_fn = transfer
    info = engine.run()
    assert info["status"] == "SUCCESS"
    assert info["sha256"]
    remaining = [p.name for p in list_successful_backups(dest)]
    assert remaining == ids[1:] + ["2026-09-06_010000"]
    assert not list(dest.glob(".incomplete_*"))


def test_failed_backup_preserves_five(tmp_path: Path):
    cfg = make_config(tmp_path)
    dest = Path(cfg.backup_destination)
    ids = _seed_five(dest)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    engine.backup_id = "2026-09-06_010000"

    def transfer(_archive: Path) -> int:
        raise BackupError("network failure")

    engine.transfer_fn = transfer
    try:
        engine.run()
        assert False, "backup should fail"
    except BackupError:
        pass
    remaining = [p.name for p in list_successful_backups(dest)]
    assert remaining == ids
    assert not list(dest.glob(".incomplete_*"))


def test_cancel_removes_incomplete_only(tmp_path: Path):
    cfg = make_config(tmp_path)
    dest = Path(cfg.backup_destination)
    ids = _seed_five(dest)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    engine.progress.request_cancel()
    try:
        engine.run()
        assert False, "should cancel"
    except BackupCancelled:
        pass
    remaining = [p.name for p in list_successful_backups(dest)]
    assert remaining == ids
    assert not list(dest.glob(".incomplete_*"))


def test_concurrent_backup_prevented(tmp_path: Path):
    cfg = make_config(tmp_path)
    from app.backup.lock import BackupAlreadyRunning, BackupLock

    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="running")
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="scheduled")
    engine.transfer_fn = lambda path: 1
    try:
        engine.run()
        assert False, "scheduled backup should skip"
    except BackupAlreadyRunning as exc:
        assert "Scheduled backup skipped" in str(exc)
    lock.release()


def test_insufficient_disk_space(tmp_path: Path):
    cfg = make_config(tmp_path, min_free_disk_gb=10**9)
    engine = BackupEngine(cfg, ssh=FakeSSH())
    engine.transfer_fn = lambda path: 1
    try:
        engine.run()
        assert False, "should fail disk check"
    except BackupError as exc:
        assert "Insufficient disk space" in str(exc)


def test_ssh_auth_failure_is_not_retried(tmp_path: Path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.engine.backup_engine.time.sleep", lambda seconds: sleeps.append(seconds))
    cfg = make_config(tmp_path, retry_count=3, retry_delay_seconds=30)
    engine = BackupEngine(cfg, ssh=FakeSSH(login_ok=False), mode="manual")
    engine.transfer_fn = lambda path: 1
    try:
        engine.run()
        assert False, "should fail SSH login"
    except BackupError as exc:
        assert "Permission denied" in str(exc)
    assert sleeps == []


def test_temporary_ssh_error_is_retried(tmp_path: Path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.engine.backup_engine.time.sleep", lambda seconds: sleeps.append(seconds))
    cfg = make_config(tmp_path, retry_count=3, retry_delay_seconds=7)

    class FlakySSH(FakeSSH):
        def test_login(self):
            self.calls.append("login")
            if self.calls.count("login") < 3:
                from app.ssh.client import SSHError

                raise SSHError("Cannot reach 192.168.18.18 port 22")
            return super().test_login()

    engine = BackupEngine(cfg, ssh=FlakySSH(), mode="manual")
    engine.transfer_fn = lambda path: make_valid_archive(path, databases=cfg.selected_databases).stat().st_size
    engine.backup_id = "2026-09-07_010000"
    info = engine.run()
    assert info["status"] == "SUCCESS"
    assert sleeps == [7, 7]


def test_redaction_in_logs(tmp_path: Path):
    from app.security.redact import redact_secrets

    text = redact_secrets("password=supersecret token=abc -----BEGIN OPENSSH PRIVATE KEY-----abc-----END OPENSSH PRIVATE KEY-----")
    assert "supersecret" not in text
    assert "PRIVATE KEY" not in text or "[REDACTED]" in text
