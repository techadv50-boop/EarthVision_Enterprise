from pathlib import Path

from app.engine.backup_engine import BackupCancelled, BackupEngine, BackupError
from app.backup.retention import list_successful_backups
from app.master.health import assess_health
from app.master.store import MasterStore
from tests.helpers import (
    FakeSSH,
    LocalMasterSSH,
    enable_backup,
    make_config,
    master_config,
    seed_remote_tree,
    write_success_backup,
)


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


def test_first_run_creates_full_master_baseline_and_keeps_legacy_archives(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    dest = Path(cfg.backup_destination)
    ids = _seed_five(dest)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    engine = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"), mode="manual")
    info = engine.run()
    assert info["status"] == "SUCCESS"
    assert info["type"] == "FULL"
    assert info["generation"] == 1
    store = MasterStore(dest)
    assert store.head_generation() == 1
    remaining = [p.name for p in list_successful_backups(dest)]
    assert remaining == ids
    assert (dest / "master").is_dir()
    assert not list(dest.glob(".incomplete_*"))
    health = assess_health(store, deep=True)
    assert health["status"] in {"HEALTHY", "WARNING"}


def test_second_run_with_no_file_or_db_change_is_no_change(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote")
    enable_backup(cfg, ssh)
    first = BackupEngine(cfg, ssh=ssh, mode="manual").run()
    assert first["type"] == "FULL"
    second = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"), mode="manual").run()
    assert second["type"] == "NO_CHANGE"
    assert MasterStore(cfg.backup_destination).head_generation() == 1


def test_incremental_new_modified_deleted_renamed_moved(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    site = Path(remote["xdgen.com"])
    (site / "index.html").write_text("changed\n", encoding="utf-8")
    (site / "brand-new.txt").write_text("new\n", encoding="utf-8")
    (site / "home.html").write_text("changed\n", encoding="utf-8")
    # Keep index.html so Nginx classification stays Static; deleting it
    # would mint a new other:<root> application_id and block BACKUP NOW.
    # restore a rename of ojs file
    ojs = Path(remote["ojsxd"])
    (ojs / "paper.pdf").replace(ojs / "renamed.pdf")
    # move a 50sea file into xdgen
    Path(remote["50sea.com"], "index.html").replace(site / "moved-from-50sea.html")
    info = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    assert info["type"] == "INCREMENTAL"
    counts = info["counts"]
    assert counts["new"] >= 1
    assert counts["renamed"] + counts["moved"] + counts["deleted"] + counts["modified"] >= 1
    assert MasterStore(cfg.backup_destination).head_generation() == 2


def test_database_unchanged_skips_dump(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh1 = LocalMasterSSH(tmp_path / "remote")
    enable_backup(cfg, ssh1)
    BackupEngine(cfg, ssh=ssh1).run()
    ssh2 = LocalMasterSSH(tmp_path / "remote")
    ssh2.db_fingerprint = "fp-journal-1"
    info = BackupEngine(cfg, ssh=ssh2).run()
    assert info["type"] == "NO_CHANGE"
    assert "dump-databases" not in ssh2.calls


def test_database_changed_dumps_and_advances_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.db_fingerprint = "fp-journal-2"
    info = BackupEngine(cfg, ssh=ssh).run()
    assert info["type"] == "INCREMENTAL"
    assert info["database"] in {"OK", "CHANGED"}
    assert "dump-databases" in ssh.calls
    assert MasterStore(cfg.backup_destination).head_generation() == 2


def test_database_failure_does_not_advance_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.db_fingerprint = "fp-changed"
    ssh.fail_database = True
    try:
        BackupEngine(cfg, ssh=ssh).run()
        assert False
    except BackupError as exc:
        assert "Database" in str(exc) or "fingerprint" in str(exc).lower() or "dump" in str(exc).lower()
    assert MasterStore(cfg.backup_destination).head_generation() == 1


def test_interrupted_transfer_does_not_advance_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.truncate_stream = True
    try:
        BackupEngine(cfg, ssh=ssh).run()
        assert False
    except BackupError:
        pass
    assert not MasterStore(cfg.backup_destination).has_head()


def test_corrupt_object_stream_does_not_advance_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.corrupt_stream = True
    try:
        BackupEngine(cfg, ssh=ssh).run()
        assert False
    except BackupError:
        pass
    assert not MasterStore(cfg.backup_destination).has_head()


def test_failed_hash_does_not_advance_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.fail_hash = True
    try:
        BackupEngine(cfg, ssh=ssh).run()
        assert False
    except BackupError:
        pass
    assert not MasterStore(cfg.backup_destination).has_head()


def test_cancel_leaves_legacy_and_does_not_create_head(tmp_path: Path):
    cfg = make_config(tmp_path)
    dest = Path(cfg.backup_destination)
    ids = _seed_five(dest)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    original_begin = engine.progress.begin

    def begin_then_cancel(**kwargs):
        result = original_begin(**kwargs)
        engine.progress.request_cancel()
        return result

    engine.progress.begin = begin_then_cancel  # type: ignore[method-assign]
    try:
        engine.run()
        assert False, "should cancel"
    except BackupCancelled:
        pass
    remaining = [p.name for p in list_successful_backups(dest)]
    assert remaining == ids
    assert not MasterStore(dest).has_head()


def test_concurrent_backup_prevented(tmp_path: Path):
    cfg = make_config(tmp_path)
    from app.backup.lock import BackupAlreadyRunning, BackupLock

    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="running")
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="scheduled")
    try:
        engine.run()
        assert False, "scheduled backup should skip"
    except BackupAlreadyRunning as exc:
        assert "Scheduled backup skipped" in str(exc)
    lock.release()


def test_insufficient_disk_space(tmp_path: Path):
    cfg = make_config(tmp_path, min_free_disk_gb=10**9)
    engine = BackupEngine(cfg, ssh=FakeSSH())
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
    try:
        engine.run()
        assert False, "should fail SSH login"
    except BackupError as exc:
        assert "Permission denied" in str(exc)
    assert sleeps == []


def test_temporary_ssh_error_is_retried(tmp_path: Path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.engine.backup_engine.time.sleep", lambda seconds: sleeps.append(seconds))
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote, retry_count=3, retry_delay_seconds=7)

    class FlakySSH(LocalMasterSSH):
        def test_login(self):
            self.calls.append("login")
            if self.calls.count("login") < 3:
                from app.ssh.client import SSHError

                raise SSHError("Cannot reach 192.168.18.18 port 22")
            return super().test_login()

    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    engine = BackupEngine(cfg, ssh=FlakySSH(tmp_path / "remote"), mode="manual")
    info = engine.run()
    assert info["status"] == "SUCCESS"
    assert sleeps == [7, 7]


def test_redaction_in_logs(tmp_path: Path):
    from app.security.redact import redact_secrets

    text = redact_secrets("password=supersecret token=abc -----BEGIN OPENSSH PRIVATE KEY-----abc-----END OPENSSH PRIVATE KEY-----")
    assert "supersecret" not in text
    assert "PRIVATE KEY" not in text or "[REDACTED]" in text


def test_test_connection_sends_check_to_installed_helper(tmp_path: Path):
    class RecordingSSH(FakeSSH):
        def __init__(self) -> None:
            super().__init__()
            self.script_path = ""
            self.payload = {}

        def run_script(self, script_path: str, payload, *, timeout=None, use_sudo: bool = True):
            self.script_path = script_path
            self.payload = dict(payload)
            return super().run_script(script_path, payload, timeout=timeout, use_sudo=use_sudo)

    cfg = make_config(tmp_path)
    ssh = RecordingSSH()
    result = BackupEngine(cfg, ssh=ssh).test_connection()
    assert result["login"] is True
    assert result["script"] is True
    assert ssh.script_path == "/usr/local/lib/serverbackup/prepare-backup.sh"
    assert "ensure-backup-mysql-user" in ssh.calls
    assert "check" in ssh.calls
    assert ssh.payload["action"] == "check"
    assert "backup" != ssh.payload["action"]
    account = result.get("database_account") or {}
    assert account.get("configured_user") == "serverbackup"
    assert account.get("using_root") is False
    assert "password" not in str(account).lower()


def test_dry_run_closes_ssh_session_and_previews_delta(tmp_path: Path):
    class TrackingSSH(FakeSSH):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    cfg = make_config(tmp_path)
    ssh = TrackingSSH()
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    assert result["ok"] is True
    assert ssh.closed is True
    assert "dry-run" in ssh.calls
    assert "discover-applications" in ssh.calls
    assert "backup" not in ssh.calls
    assert "hash-files" not in ssh.calls
    assert "stream-objects" not in ssh.calls
    assert "master" in result
    assert "HEAD: unchanged" in (result.get("report_text") or "")
    assert "sateye.xdgen.com" in (result.get("report_text") or "")
    assert "NOT ACTIVE IN CURRENT SERVER CONFIGURATION" in (result.get("report_text") or "")
    assert "citation.xdgen.com" in (result.get("report_text") or "")
    assert "none configured" not in (result.get("report_text") or "")
    assert "EXPECTED FULL BASELINE SIZE:" in (result.get("report_text") or "")
    assert not MasterStore(cfg.backup_destination).has_head()


def test_rebuild_master_replaces_head_after_verification(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    Path(remote["xdgen.com"], "extra.txt").write_text("x\n", encoding="utf-8")
    info = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).rebuild_master()
    assert info["type"] == "FULL"
    assert MasterStore(cfg.backup_destination).head_generation() == 2


def test_engine_never_calls_apply_retention(tmp_path: Path, monkeypatch):
    called = []
    monkeypatch.setattr("app.backup.retention.apply_retention", lambda *a, **k: called.append(True))
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    assert called == []


def test_missing_ojs_files_dir_fails_backup(tmp_path: Path):
    import shutil

    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    shutil.rmtree(remote["ojs50"])
    try:
        BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
        assert False
    except BackupError as exc:
        assert "files_dir" in str(exc) or "OJS" in str(exc)
    assert not MasterStore(cfg.backup_destination).has_head()
