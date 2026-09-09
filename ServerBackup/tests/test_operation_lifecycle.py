"""Operation lifecycle: idle startup, per-op cancel, stale-signal isolation."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.backup.live import format_idle_backup_panel, format_live_backup_panel
from app.backup.operation import KIND_BACKUP, KIND_DRY_RUN, OperationRegistry
from app.backup.progress import ProgressReporter
from app.engine.backup_engine import BackupCancelled, BackupEngine
from app.engine.status import collect_dashboard_status, normalize_startup_progress, progress_path
from app.master.store import MasterStore
from tests.helpers import FakeSSH, LocalMasterSSH, make_config, master_config, seed_remote_tree


def test_begin_does_not_inherit_previous_cancel_flag(tmp_path: Path):
    reporter = ProgressReporter(tmp_path / "progress.json")
    reporter.begin(operation_id="backup-a", operation="BACKUP")
    reporter.request_cancel()
    assert reporter.cancel_requested() is True
    reporter.begin(operation_id="dry-b", operation="DRY RUN")
    assert reporter.read()["cancel_requested"] is False
    assert reporter.cancel_requested() is False
    assert reporter.read()["operation_id"] == "dry-b"
    assert reporter.read()["ui_stage"] == "STARTING"
    assert reporter.read()["elapsed_seconds"] == 0


def test_cancel_backup_does_not_cancel_next_dry_run(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    backup = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    original = backup.progress.begin

    def begin_then_cancel(**kwargs):
        result = original(**kwargs)
        backup.progress.request_cancel()
        return result

    backup.progress.begin = begin_then_cancel  # type: ignore[method-assign]
    try:
        backup.run()
        raise AssertionError("expected cancel")
    except BackupCancelled:
        pass
    dry = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"))
    result = dry.dry_run()
    assert result["ok"] is True
    assert "cancelled" not in str(result.get("error") or "").lower()
    assert dry.progress.read().get("status") != "cancelled"


def test_cancel_dry_run_does_not_cancel_next_backup_preflight(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    dry = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote"))
    original = dry.progress.begin

    def begin_then_cancel(**kwargs):
        result = original(**kwargs)
        dry.progress.request_cancel()
        return result

    dry.progress.begin = begin_then_cancel  # type: ignore[method-assign]
    try:
        dry.dry_run()
        raise AssertionError("expected cancel")
    except BackupCancelled:
        pass
    backup = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    backup.progress.begin(operation_id=backup.backup_id, operation="BACKUP")
    assert backup.progress.cancel_requested() is False


def test_stale_progress_write_is_ignored(tmp_path: Path):
    path = tmp_path / "progress.json"
    current = ProgressReporter(path)
    current.begin(operation_id="op-b", operation="BACKUP")
    stale = ProgressReporter(path)
    stale._operation_id = "op-a"
    stale.write(status="cancelled", message="stale cancel", ui_stage="CANCELLED", operation_id="op-a")
    data = current.read()
    assert data["operation_id"] == "op-b"
    assert data["status"] == "running"
    assert data["ui_stage"] != "CANCELLED"


def test_elapsed_starts_at_zero_for_new_operation(tmp_path: Path):
    reporter = ProgressReporter(tmp_path / "progress.json")
    reporter.write(started_at=time.time() - 1288, elapsed_seconds=1288, status="cancelled", ui_stage="PREPARING")
    reporter.begin(operation_id="fresh", operation="BACKUP")
    data = reporter.read()
    assert data["elapsed_seconds"] == 0
    panel = format_live_backup_panel(data, now=float(data["started_at"]))
    assert "Elapsed: 00:00:00" in panel


def test_idle_panel_does_not_use_old_elapsed():
    panel = format_idle_backup_panel({"master": {"current_size": 0, "head_state": "MISSING"}})
    assert "Status: IDLE" in panel
    assert "Overall: Ready" in panel
    assert "Elapsed: —" in panel
    assert "PREPARING" not in panel
    assert "cancelled" not in panel.lower()


def test_startup_normalizes_cancelled_preparing_cache(tmp_path: Path):
    cfg = make_config(tmp_path)
    reporter = ProgressReporter(progress_path())
    reporter.replace(
        {
            "status": "cancelled",
            "ui_stage": "PREPARING",
            "operation": "BACKUP",
            "message": "Backup cancelled.",
            "cancel_requested": True,
            "started_at": time.time() - 1288,
            "elapsed_seconds": 1288,
            "overall": {"label": "Preparing...", "percent": None, "bytes_done": 0, "bytes_total": 0},
        }
    )
    assert normalize_startup_progress(cfg) is True
    leftover = ProgressReporter(progress_path()).read()
    assert leftover["status"] == "idle"
    assert leftover["ui_stage"] == "IDLE"
    assert leftover["cancel_requested"] is False
    assert leftover["elapsed_seconds"] is None
    status = collect_dashboard_status(cfg)
    assert status["backup_running"] is False
    assert status["live_message"] == "Ready."
    assert status["progress"]["status"] == "idle"


def test_failed_and_cancelled_operations_leave_head_unchanged(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    original = engine.progress.begin

    def begin_then_cancel(**kwargs):
        result = original(**kwargs)
        engine.progress.request_cancel()
        return result

    engine.progress.begin = begin_then_cancel  # type: ignore[method-assign]
    try:
        engine.run()
    except BackupCancelled:
        pass
    assert not MasterStore(cfg.backup_destination).has_head()
    data = engine.progress.read()
    assert data.get("head_state") == "UNCHANGED"


def test_registry_allows_only_one_active_operation():
    registry = OperationRegistry()
    first = registry.try_start(KIND_BACKUP)
    assert first is not None
    assert registry.try_start(KIND_BACKUP) is None
    assert registry.try_start(KIND_DRY_RUN) is None
    registry.finish(first.operation_id)
    second = registry.try_start(KIND_DRY_RUN)
    assert second is not None
    assert second.operation_id != first.operation_id
    assert second.cancel_event is not first.cancel_event
    first.request_cancel()
    assert second.is_cancelled() is False


def test_gui_starts_idle_with_no_fake_progress_bar(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    ProgressReporter(progress_path()).replace(
        {
            "status": "cancelled",
            "ui_stage": "PREPARING",
            "operation": "BACKUP",
            "message": "Backup cancelled.",
            "cancel_requested": True,
            "started_at": time.time() - 2000,
            "elapsed_seconds": 2000,
            "overall": {"label": "Preparing...", "bytes_done": 0, "bytes_total": 0},
        }
    )
    qt = QApplication.instance() or QApplication([])
    window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
    window.timer.stop()
    window.show()
    qt.processEvents()
    text = window.dashboard.live_panel.text()
    assert "Status: IDLE" in text
    assert "Overall: Ready" in text
    assert "Stage: —" in text
    assert "Elapsed: —" in text
    assert "PREPARING" not in text
    assert window.dashboard.progress_bar.maximum() == 100
    assert window.dashboard.progress_bar.value() == 0
    assert window.dashboard.progress_bar.format() == "—"
    assert window.operations.active_id() is None
    window.close()


def test_gui_ignores_stale_worker_finish_and_does_not_dialog(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui.main_window import MainWindow

    qt = QApplication.instance() or QApplication([])
    window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
    window.timer.stop()
    old = window.operations.try_start(KIND_BACKUP)
    window.operations.finish(old.operation_id)
    new = window.operations.try_start(KIND_DRY_RUN)
    assert new is not None
    boxes: list[str] = []

    def fake_box(*args, **kwargs):
        boxes.append("shown")
        return QMessageBox.StandardButton.Ok

    with patch.object(QMessageBox, "critical", fake_box), patch.object(QMessageBox, "information", fake_box):
        window._on_backup_finished(old.operation_id, False, "Backup cancelled.")
        window._on_dry_run_finished(old.operation_id, False, "cancelled")
    assert boxes == []
    assert window.operations.active_id() == new.operation_id
    window.operations.finish(new.operation_id)
    window.close()


def test_gui_new_operation_elapsed_and_single_worker(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    qt = QApplication.instance() or QApplication([])
    window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
    window.timer.stop()
    first = window.operations.try_start(KIND_BACKUP)
    assert first is not None
    window.refresh()
    qt.processEvents()
    text = window.dashboard.live_panel.text()
    assert "STARTING" in text
    assert "Elapsed: 00:00:00" in text or "Elapsed: 00:00:01" in text
    assert window.operations.try_start(KIND_DRY_RUN) is None
    assert window._busy() is True
    window.operations.finish(first.operation_id)
    window.refresh()
    qt.processEvents()
    assert "Status: IDLE" in window.dashboard.live_panel.text()
    window.close()


def test_gui_does_not_show_failure_dialog_on_startup(tmp_path: Path):
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
            "error": "Backup cancelled.",
        }
    )
    qt = QApplication.instance() or QApplication([])
    boxes: list[str] = []

    def fake_critical(*args, **kwargs):
        boxes.append("critical")
        return QMessageBox.StandardButton.Ok

    with patch.object(QMessageBox, "critical", fake_critical):
        window = MainWindow(make_config(tmp_path), ssh_password="in-memory")
        window.timer.stop()
        qt.processEvents()
    assert boxes == []
    assert "Status: IDLE" in window.dashboard.live_panel.text()
    window.close()
