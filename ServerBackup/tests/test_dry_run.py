"""DRY RUN must preview a master backup without hashing, writing HEAD, or hanging."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.backup.lock import BackupAlreadyRunning, BackupLock
from app.engine.backup_engine import BackupCancelled, BackupEngine, BackupError
from app.engine.status import collect_dashboard_status
from app.master.delta import compute_delta, promote_unhashed_for_preview
from app.master.store import MasterStore
from tests.helpers import FakeSSH, LocalMasterSSH, make_config, master_config, seed_remote_tree


def _log_text(engine: BackupEngine) -> str:
    return engine.logger.path.read_text(encoding="utf-8")


def test_promote_unhashed_first_run_all_new():
    inventory = [
        {"source_root": "/var/www/a", "relative_path": "index.html", "size": 12, "mtime": 1},
        {"source_root": "/var/www/a", "relative_path": "logo.png", "size": 40, "mtime": 1},
    ]
    changes = compute_delta(None, inventory, hashes={})
    assert changes.hash_candidates
    assert not changes.new
    promote_unhashed_for_preview(changes)
    assert changes.hash_candidates == []
    assert len(changes.new) == 2
    assert changes.estimated_transfer_bytes() == 52


def test_first_run_dry_run_with_no_master_is_full_baseline_preview(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote")
    engine = BackupEngine(cfg, ssh=ssh)
    result = engine.dry_run()
    master = result["master"]
    text = result["report_text"]
    assert result["ok"] is True
    assert master["type"] == "FULL"
    assert master["hashed"] is False
    assert master["head_unchanged"] is True
    assert master["counts"]["new"] >= 1
    assert master["estimated_transfer_bytes"] > 0
    assert "hash-files" not in ssh.calls
    assert "stream-objects" not in ssh.calls
    assert "dump-databases" not in ssh.calls
    assert "backup" not in ssh.calls
    assert not MasterStore(cfg.backup_destination).has_head()
    assert not (Path(cfg.backup_destination) / "master" / "HEAD").exists()
    assert "MASTER STATUS: NO BASELINE" in text
    assert "MODE: FULL BASELINE PREVIEW" in text
    assert "EXPECTED ACTION: FULL MASTER BASELINE" in text
    assert "HEAD: unchanged" in text
    assert "DATABASES: discovered" in text
    assert "none configured" not in text
    assert "sateye.xdgen.com" in text
    assert "citation.xdgen.com" in text
    assert "NEW SITE DETECTED — REQUIRES APPROVAL" in text
    assert "EXPECTED FULL BASELINE SIZE:" in text
    assert "APPROVED" in text or "pending_approval=" in text
    assert "MariaDB:" in text
    assert "ojs50" in text or "journal" in text
    assert "PostgreSQL:" in text
    assert "citation" in text
    assert "discover-applications" in ssh.calls
    assert "discover-databases" in ssh.calls
    assert remote["journal.50sea.com"] in text
    assert remote["ojs50"] in text
    log = _log_text(engine)
    for token in (
        "DRY_RUN_START",
        "DRY_RUN_PASSWORD_CHECK",
        "DRY_RUN_SSH_CONNECT_START",
        "DRY_RUN_SSH_CONNECTED",
        "DRY_RUN_DISCOVERY_START",
        "DRY_RUN_DISCOVERY_COMPLETE",
        "DRY_RUN_INVENTORY_START",
        "DRY_RUN_INVENTORY_COMPLETE",
        "DRY_RUN_DELTA_START",
        "DRY_RUN_DELTA_COMPLETE",
        "DRY_RUN_DB_FINGERPRINT_START",
        "DRY_RUN_DB_FINGERPRINT_COMPLETE",
        "DRY_RUN_RESULT",
    ):
        assert token in log
    assert "supersecret" not in log


def test_existing_master_dry_run_is_incremental_preview_and_does_not_hash(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    store = MasterStore(cfg.backup_destination)
    assert store.head_generation() == 1
    Path(remote["xdgen.com"], "index.html").write_text("changed-preview\n", encoding="utf-8")
    ssh = LocalMasterSSH(tmp_path / "remote")
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    master = result["master"]
    assert result["ok"] is True
    assert master["type"] == "INCREMENTAL"
    assert master["counts"]["modified"] >= 1
    assert "hash-files" not in ssh.calls
    assert store.head_generation() == 1
    assert "MASTER STATUS: GENERATION 1" in result["report_text"]
    assert "MODE: INCREMENTAL PREVIEW" in result["report_text"]
    assert "HEAD: unchanged" in result["report_text"]


def test_existing_master_unchanged_files_keep_head_and_still_show_discovery(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    ssh = LocalMasterSSH(tmp_path / "remote")
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    master = result["master"]
    text = result["report_text"]
    assert result["ok"] is True
    assert master["counts"]["new"] == 0
    assert master["counts"]["modified"] == 0
    assert master["counts"]["deleted"] == 0
    assert "hash-files" not in ssh.calls
    assert MasterStore(cfg.backup_destination).head_generation() == 1
    assert "HEAD: unchanged" in text
    assert "sateye.xdgen.com" in text
    assert "citation.xdgen.com" in text
    assert "none configured" not in text
    # BACKUP NOW still only fingerprints selected_databases. Newly discovered
    # MariaDB names therefore appear on DRY RUN without writing HEAD.
    assert master["type"] in {"NO_CHANGE", "INCREMENTAL"}


def test_dry_run_ssh_failure_is_reported_without_hashing(tmp_path: Path):
    cfg = make_config(tmp_path)
    ssh = FakeSSH(login_ok=False)
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    assert result["ok"] is False
    assert "Permission denied" in (result.get("report_text") or result.get("error") or "")
    assert "discover-applications" not in ssh.calls
    assert "discover-ojs" not in ssh.calls
    assert "hash-files" not in ssh.calls
    assert not MasterStore(cfg.backup_destination).has_head()


def test_dry_run_ojs_discovery_failure_is_reported(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.fail_discover = True
    engine = BackupEngine(cfg, ssh=ssh)
    result = engine.dry_run()
    assert result["ok"] is False
    text = result.get("report_text") or result.get("error") or ""
    assert "OJS" in text or "discovery" in text.lower()
    assert "hash-files" not in ssh.calls
    assert not MasterStore(cfg.backup_destination).has_head()
    assert "DRY_RUN_ERROR" in _log_text(engine)


def test_dry_run_db_fingerprint_failure_is_reported_without_writing_head(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.fail_database = True
    engine = BackupEngine(cfg, ssh=ssh)
    result = engine.dry_run()
    assert result["ok"] is False
    master = result["master"]
    assert master["database"] == "FAILED"
    assert "fingerprint failed" in result["report_text"]
    assert master["counts"]["new"] >= 1
    assert "hash-files" not in ssh.calls
    assert not MasterStore(cfg.backup_destination).has_head()
    assert "DRY_RUN_ERROR" in _log_text(engine)


def test_dry_run_cancellation(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    engine = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"))
    engine.progress.request_cancel()
    try:
        engine.dry_run()
        assert False, "cancelled dry run should raise"
    except BackupCancelled:
        pass
    assert not MasterStore(cfg.backup_destination).has_head()
    assert BackupLock(cfg.backup_destination).is_locked() is False


def test_dry_run_worker_exception_is_not_swallowed(tmp_path: Path, monkeypatch):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)

    def boom(*_args, **_kwargs):
        raise RuntimeError("worker boom")

    monkeypatch.setattr("app.engine.backup_engine.run_master_backup", boom)
    engine = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"))
    try:
        engine.dry_run()
        assert False, "unexpected exception should propagate"
    except BackupError as exc:
        assert "worker boom" in str(exc)
    log = _log_text(engine)
    assert "DRY_RUN_ERROR" in log
    assert "worker boom" in log
    assert BackupLock(cfg.backup_destination).is_locked() is False
    assert not MasterStore(cfg.backup_destination).has_head()


def test_dry_run_holds_lock_so_dashboard_shows_live_progress(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    seen = {"locked": False, "message": "", "percent": 0}

    class LockAwareSSH(LocalMasterSSH):
        def run_script(self, script_path, payload, *, timeout=None, use_sudo: bool = True):
            if payload.get("action") == "inventory":
                status = collect_dashboard_status(cfg)
                seen["locked"] = bool(status["backup_running"])
                seen["message"] = str(status["live_message"])
                progress = status.get("progress") or {}
                total = int(progress.get("bytes_total") or 0)
                done = int(progress.get("bytes_done") or 0)
                seen["percent"] = int(done * 100 / total) if total else 0
            return super().run_script(script_path, payload, timeout=timeout, use_sudo=use_sudo)

    result = BackupEngine(cfg, ssh=LockAwareSSH(tmp_path / "remote")).dry_run()
    assert result["ok"] is True
    assert seen["locked"] is True
    assert seen["message"]
    assert seen["percent"] > 0
    assert BackupLock(cfg.backup_destination).is_locked() is False


def test_dry_run_does_not_run_while_backup_lock_held(tmp_path: Path):
    cfg = make_config(tmp_path)
    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="other")
    try:
        try:
            BackupEngine(cfg, ssh=FakeSSH()).dry_run()
            assert False, "should refuse when backup already running"
        except BackupAlreadyRunning:
            pass
    finally:
        lock.release()


def test_dry_run_does_not_require_prior_test_connection():
    source = Path(__file__).resolve().parents[1] / "app" / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    dry_run_fn = text.split("def dry_run(self)", 1)[1].split("def _on_dry_run_finished", 1)[0]
    finished = text.split("def _on_dry_run_finished", 1)[1].split("def test_integrity", 1)[0]
    assert "test_connection" not in dry_run_fn
    assert "_ssh_state" not in dry_run_fn
    assert "ensure_password" in dry_run_fn
    assert "_dry_run_finished.emit" in dry_run_fn
    assert "except" in dry_run_fn and "Exception" in dry_run_fn
    assert "_dry_run_finished = Signal(bool, str)" in text
    assert "QueuedConnection" in text
    assert "QMessageBox.information" in finished
    assert "QMessageBox.critical" in finished


def test_gui_dry_run_surfaces_result_and_worker_exceptions(tmp_path: Path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    cfg = make_config(tmp_path)
    window = MainWindow(cfg, ssh_password="in-memory")
    window.timer.stop()
    boxes: list[tuple[str, str, str]] = []

    def fake_info(_parent, title, text):
        boxes.append(("info", str(title), str(text)))
        return QMessageBox.StandardButton.Ok

    def fake_critical(_parent, title, text):
        boxes.append(("critical", str(title), str(text)))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    monkeypatch.setattr(QMessageBox, "critical", fake_critical)

    monkeypatch.setattr(
        "app.engine.backup_engine.BackupEngine.dry_run",
        lambda self: {"ok": True, "report_text": "MASTER STATUS: NO BASELINE\nHEAD: unchanged"},
    )
    window.dry_run()
    deadline = time.time() + 5
    while time.time() < deadline and not boxes:
        app.processEvents()
        time.sleep(0.05)
    assert boxes
    assert boxes[0][0] == "info"
    assert "NO BASELINE" in boxes[0][2]
    boxes.clear()

    def boom(self):
        raise RuntimeError("silent-thread-failure")

    monkeypatch.setattr("app.engine.backup_engine.BackupEngine.dry_run", boom)
    window.dry_run()
    deadline = time.time() + 5
    while time.time() < deadline and not boxes:
        app.processEvents()
        time.sleep(0.05)
    assert boxes
    assert boxes[0][0] == "critical"
    assert "silent-thread-failure" in boxes[0][2]
    window.close()


def test_dry_run_discovers_databases_when_selected_list_is_empty(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote, selected_databases=[])
    ssh = LocalMasterSSH(tmp_path / "remote")
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    text = result["report_text"]
    assert result["ok"] is True
    assert cfg.databases_for_backup() == []
    assert "none configured" not in text
    assert "DATABASES: discovered" in text
    assert "MariaDB:" in text
    assert "journal" in text
    assert "ojs50" in text
    assert "PostgreSQL:" in text
    assert "citation" in text
    assert "sateye.xdgen.com" in text
    assert "citation.xdgen.com" in text
    assert "EXPECTED FULL BASELINE SIZE:" in text
    assert "pending_approval=" in text
    assert "hash-files" not in ssh.calls
    assert "dump-databases" not in ssh.calls
    assert not MasterStore(cfg.backup_destination).has_head()


def test_dry_run_does_not_use_hardcoded_website_list(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(
        tmp_path,
        remote,
        website_directories=[remote["xdgen.com"]],
        selected_databases=[],
    )
    result = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).dry_run()
    text = result["report_text"]
    assert "sateye.xdgen.com" in text
    assert "citation.xdgen.com" in text
    assert "journal.50sea.com" in text
    assert "journal.xdgen.com" in text
    assert "50sea.com" in text
    assert "NEW SITE DETECTED — REQUIRES APPROVAL" in text
    assert "none configured" not in text


def test_dry_run_removed_site_requires_review_and_keeps_master(tmp_path: Path):
    from app.discover.policy import save_snapshot, set_approval

    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    store = MasterStore(cfg.backup_destination)
    assert store.head_generation() == 1
    save_snapshot(
        cfg.backup_destination,
        {
            "applications": [
                {
                    "application_id": "gone.example.com:/var/www/gone",
                    "hostname": "gone.example.com",
                    "type": "Static",
                    "root": "/var/www/gone",
                    "status": "READY",
                }
            ]
        },
    )
    set_approval(cfg.backup_destination, "gone.example.com:/var/www/gone", approved=True)
    assert store.head_generation() == 1
    assert store.has_head() is True
    ssh = LocalMasterSSH(tmp_path / "remote")
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    text = result["report_text"]
    assert "gone.example.com" in text
    assert "SITE REMOVED — REQUIRES REVIEW" in text
    assert store.head_generation() == 1
    assert "hash-files" not in ssh.calls


def test_format_dry_run_report_never_says_none_configured_after_empty_discovery():
    from app.master.pipeline import format_dry_run_report

    text = format_dry_run_report(
        has_master=False,
        generation=None,
        op_type="FULL",
        ojs=[],
        sources=[],
        db_names=[],
        db_result="NONE",
        applications=[],
        postgres_names=[],
    )
    assert "none configured" not in text
    assert "none discovered" in text
    assert "EXPECTED FULL BASELINE SIZE:" in text
