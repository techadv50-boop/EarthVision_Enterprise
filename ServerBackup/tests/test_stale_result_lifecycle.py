"""Stale last-result vs current master. No modal on IDLE/startup."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.backup.live import format_idle_backup_panel, format_last_result_panel
from app.backup.operation import KIND_BACKUP
from app.backup.progress import ProgressReporter
from app.engine.backup_engine import BackupEngine, BackupError
from app.engine.status import collect_dashboard_status, master_idle_facts, normalize_startup_progress, progress_path
from app.master.health import CORRUPTED, HEALTHY, MISSING, assess_health
from app.master.objects import has_object, write_object_from_bytes
from app.master.pipeline import staging_missing_object_error
from app.master.store import MasterStore
from app.master.tree import make_record
from tests.helpers import LocalMasterSSH, enable_backup, make_config, master_config, seed_remote_tree

STALE_MISSING = "Missing object for /var/www/journal.50sea.com/docs/manual/de/SUMMARY.md"


def test_startup_after_failed_backup_is_idle_without_popup(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    ProgressReporter(progress_path()).replace(
        {
            "status": "failed",
            "ui_stage": "FAILED",
            "operation": "BACKUP",
            "message": "BACKUP FAILED",
            "error": STALE_MISSING,
            "operation_id": "2026-09-08_202146-b7c35444",
            "head_state": "UNCHANGED",
        }
    )
    qt = QApplication.instance() or QApplication([])
    boxes: list[str] = []

    def fake_box(*args, **kwargs):
        boxes.append("shown")
        return QMessageBox.StandardButton.Ok

    cfg = make_config(tmp_path)
    with patch.object(QMessageBox, "critical", fake_box), patch.object(QMessageBox, "information", fake_box):
        window = MainWindow(cfg, ssh_password="in-memory")
        window.timer.stop()
        window.show()
        qt.processEvents()
    assert boxes == []
    live = window.dashboard.live_panel.text()
    assert "Status: IDLE" in live
    assert "NO BASELINE" in live
    assert "HEAD: MISSING" in live
    assert "BACKUP FAILED" not in live
    result = window.dashboard.result_panel.text()
    assert "LAST RESULT: FAILED" in result
    assert STALE_MISSING in result
    assert "2026-09-08_202146-b7c35444" in result
    assert not window.dashboard.details_button.isHidden()
    assert window.dashboard.progress_bar.format() == "—"
    assert window.dashboard.progress_bar.value() == 0
    assert window.operations.active_id() is None
    facts = master_idle_facts(cfg)
    assert facts["master_status"] == "NO BASELINE"
    assert facts["head_state"] == "MISSING"
    window.close()


def test_startup_after_cancelled_backup_is_idle_without_popup(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    ProgressReporter(progress_path()).replace(
        {
            "status": "cancelled",
            "ui_stage": "CANCELLED",
            "operation": "BACKUP",
            "message": "Backup cancelled.",
            "error": "Backup cancelled.",
            "operation_id": "op-cancel",
            "head_state": "UNCHANGED",
        }
    )
    qt = QApplication.instance() or QApplication([])
    boxes: list[str] = []

    def fake_box(*args, **kwargs):
        boxes.append("shown")
        return QMessageBox.StandardButton.Ok

    with patch.object(QMessageBox, "critical", fake_box), patch.object(QMessageBox, "information", fake_box):
        window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
        window.timer.stop()
        qt.processEvents()
    assert boxes == []
    assert "Status: IDLE" in window.dashboard.live_panel.text()
    assert "LAST RESULT: CANCELLED" in window.dashboard.result_panel.text()
    window.close()


def test_failed_result_displayed_without_popup_on_current_finish(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    qt = QApplication.instance() or QApplication([])
    window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
    window.timer.stop()
    state = window.operations.try_start(KIND_BACKUP)
    boxes: list[str] = []

    def fake_box(*args, **kwargs):
        boxes.append("shown")
        return QMessageBox.StandardButton.Ok

    with patch.object(QMessageBox, "critical", fake_box), patch.object(QMessageBox, "information", fake_box):
        window._on_backup_finished(state.operation_id, False, STALE_MISSING)
        qt.processEvents()
    assert boxes == []
    assert "Status: IDLE" in window.dashboard.live_panel.text()
    assert "LAST RESULT: FAILED" in window.dashboard.result_panel.text()
    assert STALE_MISSING in window.dashboard.result_panel.text()
    window.close()


def test_no_active_operation_plus_stale_error_stays_idle(tmp_path: Path):
    cfg = make_config(tmp_path)
    ProgressReporter(progress_path()).write(
        status="failed",
        error=STALE_MISSING,
        message="BACKUP FAILED",
        ui_stage="FAILED",
        operation_id="stale-op",
    )
    assert normalize_startup_progress(cfg) is True
    leftover = ProgressReporter(progress_path()).read()
    assert leftover["status"] == "idle"
    assert leftover["ui_stage"] == "IDLE"
    assert leftover.get("error") is None
    assert leftover["last_result"]["error"] == STALE_MISSING
    status = collect_dashboard_status(cfg)
    assert status["backup_running"] is False
    assert status["live_message"] == "Ready."
    assert status["progress"]["status"] == "idle"
    assert status["last_completed"]["error"] == STALE_MISSING
    assert status["master_status"] == "NO BASELINE"
    assert status["head_label"] == "MISSING"


def test_head_missing_plus_stale_failed_operation_does_not_become_master(tmp_path: Path):
    cfg = make_config(tmp_path)
    store = MasterStore(cfg.backup_destination)
    store.ensure_layout()
    store.write_history_only(
        {
            "operation_id": "2026-09-08_202146-b7c35444",
            "status": "FAILED",
            "type": "FULL",
            "error": STALE_MISSING,
        }
    )
    ProgressReporter(progress_path()).replace(
        {
            "status": "failed",
            "error": STALE_MISSING,
            "operation_id": "2026-09-08_202146-b7c35444",
            "head_state": "UNCHANGED",
        }
    )
    normalize_startup_progress(cfg)
    facts = master_idle_facts(cfg)
    assert facts["head_state"] == "MISSING"
    assert facts["master_status"] == "NO BASELINE"
    assert store.head_generation() is None
    health = assess_health(store)
    assert health["status"] == MISSING
    assert health["generation"] is None
    status = collect_dashboard_status(cfg)
    assert status["master_status"] == "NO BASELINE"
    assert status["last_completed"]["operation_id"] == "2026-09-08_202146-b7c35444"


def test_corrupt_committed_generation_is_not_no_baseline(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    digest = write_object_from_bytes(store.objects_root, b"ok")
    rec = make_record(source_root="/var/www/a", relative_path="f.txt", sha256=digest, size=2)
    store.commit(
        generation=1,
        tree={"files": [rec]},
        meta={"generation": 1, "database": "SKIPPED", "integrity": "OK"},
        history={"operation_id": "ok", "type": "FULL", "status": "SUCCESS"},
    )
    from app.master.objects import object_path

    object_path(store.objects_root, digest).unlink()
    health = assess_health(store)
    assert health["status"] == CORRUPTED
    assert health["generation"] == 1
    assert store.head_generation() == 1
    assert "f.txt" in health["detail"]


def test_missing_object_in_staging_does_not_write_head(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    store.ensure_layout()
    rec = {
        "source_root": "/var/www/journal.50sea.com",
        "relative_path": "docs/manual/de/SUMMARY.md",
        "sha256": "ab" * 32,
    }
    message = staging_missing_object_error(rec, generation=1)
    assert message.startswith("STAGING ERROR:")
    assert "SUMMARY.md" in message
    assert "sha256=" in message
    assert "generation=1" in message
    assert "HEAD unchanged" in message
    assert not store.has_head()
    health = assess_health(store)
    assert health["status"] == MISSING
    assert health.get("master_status") == "NO BASELINE"


def test_successful_generation_verifies_empty_and_nonempty_objects(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    summary = Path(remote["journal.50sea.com"]) / "docs/manual/de/SUMMARY.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_bytes(b"")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    info = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"), mode="manual").run()
    assert info["status"] == "SUCCESS"
    store = MasterStore(cfg.backup_destination)
    assert store.head_generation() == 1
    empty = hashlib.sha256(b"").hexdigest()
    assert has_object(store.objects_root, empty)
    health = assess_health(store, deep=True)
    assert health["status"] in {HEALTHY, "WARNING"}
    tree = store.load_tree(1)
    paths = [f"{item.get('source_root')}/{item.get('relative_path')}" for item in tree.get("files") or []]
    assert any(str(path).endswith("docs/manual/de/SUMMARY.md") for path in paths)


def test_transition_failed_cancelled_success_to_idle(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    qt = QApplication.instance() or QApplication([])
    window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
    window.timer.stop()
    boxes: list[str] = []

    def fake_box(*args, **kwargs):
        boxes.append("shown")
        return QMessageBox.StandardButton.Ok

    with patch.object(QMessageBox, "critical", fake_box), patch.object(QMessageBox, "information", fake_box):
        failed = window.operations.try_start(KIND_BACKUP)
        window._on_backup_finished(failed.operation_id, False, STALE_MISSING)
        qt.processEvents()
        assert boxes == []
        assert "Status: IDLE" in window.dashboard.live_panel.text()
        assert "LAST RESULT: FAILED" in window.dashboard.result_panel.text()

        cancelled = window.operations.try_start(KIND_BACKUP)
        window._on_backup_finished(cancelled.operation_id, False, "Backup cancelled.")
        qt.processEvents()
        assert boxes == []
        assert "Status: IDLE" in window.dashboard.live_panel.text()
        assert "LAST RESULT: CANCELLED" in window.dashboard.result_panel.text()

        success = window.operations.try_start(KIND_BACKUP)
        window._on_backup_finished(success.operation_id, True, "MASTER BACKUP STATUS=SUCCESS")
        qt.processEvents()
        assert boxes == []
        assert "Status: IDLE" in window.dashboard.live_panel.text()
        assert "LAST RESULT: SUCCESS" in window.dashboard.result_panel.text()
    window.close()


def test_backup_finished_source_does_not_auto_dialog():
    source = Path(__file__).resolve().parents[1] / "app" / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    finished = text.split("def _on_backup_finished", 1)[1].split("def cancel_backup", 1)[0]
    assert "QMessageBox.critical" not in finished
    assert "QMessageBox.information" not in finished
    assert "show_last_result_details" in text
    assert "VIEW DETAILS" in text


def test_format_last_result_panel_does_not_look_like_live_failure():
    panel = format_last_result_panel(
        {
            "status": "failed",
            "error": STALE_MISSING,
            "operation_id": "2026-09-08_202146-b7c35444",
            "head_state": "UNCHANGED",
        }
    )
    idle = format_idle_backup_panel({"master": {"head_state": "MISSING"}})
    assert "LAST RESULT: FAILED" in panel
    assert STALE_MISSING in panel
    assert "BACKUP FAILED" not in idle
    assert "Status: IDLE" in idle
    assert "NO BASELINE" in idle


def test_hashed_but_unstored_file_is_staging_error(tmp_path: Path):
    """hash-files digest on inventory is not proof the object was written."""
    remote = seed_remote_tree(tmp_path / "remote")
    summary = Path(remote["journal.50sea.com"]) / "docs/manual/de/SUMMARY.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("# summary\n", encoding="utf-8")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    ssh = LocalMasterSSH(tmp_path / "remote")
    original = ssh.popen_script

    def drop_summary(script_path, payload):
        if payload.get("action") == "stream-objects":
            files = [
                item
                for item in (payload.get("files") or [])
                if "SUMMARY.md" not in str(item.get("path") or item.get("absolute_path") or "")
            ]
            payload = dict(payload)
            payload["files"] = files
        return original(script_path, payload)

    ssh.popen_script = drop_summary  # type: ignore[method-assign]
    engine = BackupEngine(cfg, ssh=ssh, mode="manual")
    try:
        engine.run()
        raise AssertionError("expected staging failure")
    except BackupError as exc:
        text = str(exc)
        assert "STAGING ERROR" in text
        assert "SUMMARY.md" in text
    store = MasterStore(cfg.backup_destination)
    assert store.head_generation() is None
    assert assess_health(store)["status"] == MISSING
