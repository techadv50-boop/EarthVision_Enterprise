from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from app.backup.live import (
    STAGE_COMPLETE,
    STAGE_DUMPING,
    STAGE_DUMP_PREPARING,
    STAGE_FINGERPRINT,
    BackupLiveSession,
    format_live_backup_panel,
    measurable_percent,
    progress_label,
)
from app.backup.progress import ProgressReporter
from app.master.pack import unpack_to_objects, write_begin, write_end, write_file
from app.master.pipeline import PipelineError, _consume_dump_progress
from tests.helpers import LocalMasterSSH, _Proc, enable_backup, master_config, seed_remote_tree


def test_measurable_percent_is_absent_without_a_real_total():
    assert measurable_percent(0, 0) is None
    assert measurable_percent(10, None) is None
    assert measurable_percent(None, 100) is None
    assert measurable_percent(-1, 100) is None
    assert measurable_percent(50, 100) == 50


def test_dump_percent_does_not_claim_complete_when_output_exceeds_estimate():
    assert measurable_percent(400, 300, stage=STAGE_DUMPING) == 99
    assert measurable_percent(300, 300, stage=STAGE_DUMPING) == 99
    assert measurable_percent(300, 300, stage=STAGE_COMPLETE) == 100


def test_progress_label_stays_preparing_until_bytes_are_known():
    assert progress_label(done=None, total=None, stage=STAGE_DUMP_PREPARING) == "Preparing..."
    assert progress_label(done=None, total=None, stage=STAGE_FINGERPRINT) == "Preparing..."
    assert progress_label(done=0, total=None, stage=STAGE_DUMPING) == "Calculating..."
    assert " / " in progress_label(done=180 * 1024 * 1024, total=319 * 1024 * 1024, stage=STAGE_DUMPING)
    assert "produced" in progress_label(done=400, total=300, stage=STAGE_DUMPING)


def test_live_panel_omits_invented_percent_and_shows_current_database():
    panel = format_live_backup_panel(
        {
            "operation": "BACKUP — FULL MASTER BASELINE",
            "application": "journal.50sea.com",
            "started_at": 1_000,
            "elapsed_seconds": 78,
            "database": {
                "name": "journal50_ojs",
                "type": "MariaDB",
                "stage": STAGE_DUMPING,
                "status": "running",
                "bytes_produced": 180 * 1024 * 1024,
                "bytes_estimated": 319 * 1024 * 1024,
                "progress_label": "180.0 MB / 319.0 MB",
                "speed_bps": 2.3 * 1024 * 1024,
            },
            "overall": {
                "percent": 34,
                "bytes_done": 180 * 1024 * 1024,
                "bytes_total": 500 * 1024 * 1024,
                "speed_bps": 2.3 * 1024 * 1024,
                "eta_seconds": 61,
                "files_done": 12,
                "files_total": 40,
                "objects_done": 12,
                "objects_total": 40,
            },
        },
        now=1_078,
    )
    assert "BACKUP — FULL MASTER BASELINE" in panel
    assert "Overall: 34%" in panel
    assert "Application: journal.50sea.com" in panel
    assert "Database: journal50_ojs" in panel
    assert "Stage: DATABASE DUMPING" in panel
    assert "180.0 MB / 319.0 MB" in panel
    assert "Elapsed: 00:01:18" in panel
    assert "ETA: 00:01:01" in panel
    assert "Files: 12 / 40" in panel
    assert "0%" not in panel.split("Overall:", 1)[1].splitlines()[0]

    preparing = format_live_backup_panel(
        {
            "operation": "BACKUP — FULL MASTER BASELINE",
            "database": {"name": "journal50_ojs", "stage": STAGE_DUMP_PREPARING, "type": "MariaDB"},
            "overall": {"percent": None, "label": "Preparing...", "bytes_done": 0, "bytes_total": 0},
        }
    )
    assert "Overall: Preparing..." in preparing
    assert "Overall: 0%" not in preparing


def test_progress_begin_clears_leftover_fake_percent(tmp_path: Path):
    reporter = ProgressReporter(tmp_path / "progress.json")
    reporter.write(status="success", bytes_done=0, bytes_total=100, message="Dry run complete.")
    reporter.begin(backup_id="op1", operation="BACKUP")
    data = reporter.read()
    assert data["bytes_done"] == 0
    assert data["bytes_total"] == 0
    assert data["overall"]["percent"] is None
    assert data["overall"]["label"] == "Preparing..."


def test_live_session_publishes_real_dump_events(tmp_path: Path):
    reporter = ProgressReporter(tmp_path / "progress.json")
    reporter.begin(operation="BACKUP — FULL MASTER BASELINE")
    live = BackupLiveSession(
        reporter,
        operation="BACKUP — FULL MASTER BASELINE",
        applications=[{"hostname": "journal.50sea.com", "database_name": "journal50_ojs"}],
    )
    live.apply_dump_estimates({"journal50_ojs": 319 * 1024 * 1024})
    live.database_event(
        name="journal50_ojs",
        stage=STAGE_DUMPING,
        status="running",
        bytes_produced=180 * 1024 * 1024,
        bytes_estimated=319 * 1024 * 1024,
    )
    data = reporter.read()
    assert data["application"] == "journal.50sea.com"
    assert data["database"]["stage"] == STAGE_DUMPING
    assert data["database"]["name"] == "journal50_ojs"
    assert data["overall"]["percent"] is not None
    assert data["overall"]["percent"] < 100
    assert "MB /" in data["database"]["progress_label"]


def test_consume_dump_progress_reads_ndjson_events():
    events = [
        {
            "event": "progress",
            "stage": "DATABASE DISCOVERY",
            "databases": [{"name": "journal50_ojs", "estimated_bytes": 1024, "type": "MariaDB"}],
        },
        {
            "event": "progress",
            "stage": "DATABASE DUMPING",
            "name": "journal50_ojs",
            "type": "MariaDB",
            "bytes_produced": 512,
            "estimated_bytes": 1024,
        },
        {
            "event": "ok",
            "ok": True,
            "dumps": [{"name": "journal50_ojs", "path": "/tmp/journal50_ojs.sql.gz", "size": 200}],
        },
    ]
    payload = "".join(json.dumps(item) + "\n" for item in events).encode("utf-8")
    dumps = _consume_dump_progress(_Proc(payload), live=None)
    assert dumps[0]["name"] == "journal50_ojs"
    assert dumps[0]["size"] == 200


def test_consume_dump_progress_raises_on_failed_stage():
    events = [
        {
            "event": "progress",
            "stage": "DATABASE FAILED",
            "name": "journal50_ojs",
            "error": "mysqldump failed",
        },
        {"ok": False, "error": "mysqldump failed"},
    ]
    payload = "".join(json.dumps(item) + "\n" for item in events).encode("utf-8")
    with pytest.raises(PipelineError, match="mysqldump failed"):
        _consume_dump_progress(_Proc(payload, returncode=1), live=None)


def test_dump_one_database_emits_ndjson_from_real_stdout_chunks(tmp_path: Path, monkeypatch):
    import prepare_backup

    class FakeDump:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = io.BytesIO(b"x" * (1024 * 1024 + 20))
            self.stderr = io.BytesIO(b"")

        def wait(self) -> int:
            return 0

    captured: list[dict] = []

    def fake_emit(payload: dict) -> None:
        captured.append(payload)

    monkeypatch.setattr(prepare_backup, "emit_dump_progress", fake_emit)
    out = tmp_path / "journal50_ojs.sql.gz"
    result = prepare_backup.dump_one_database(
        "journal50_ojs",
        out,
        1,
        mysqldump="mysqldump",
        emit_progress=True,
        estimated_bytes=2 * 1024 * 1024,
        run_dump=FakeDump,
    )
    stages = [item.get("stage") for item in captured]
    assert "DATABASE DUMP PREPARING" in stages
    assert "DATABASE DUMPING" in stages
    assert result["bytes_produced"] == 1024 * 1024 + 20
    assert out.is_file()
    assert any(item.get("bytes_produced", 0) >= 1024 * 1024 for item in captured)


def test_legacy_stream_backup_dump_does_not_emit_ndjson(tmp_path: Path, monkeypatch):
    import prepare_backup

    emitted: list[dict] = []
    monkeypatch.setattr(prepare_backup, "emit_dump_progress", emitted.append)
    monkeypatch.setattr(prepare_backup, "schema_size_bytes", lambda _name: 99)
    monkeypatch.setattr(prepare_backup.shutil, "which", lambda _name: "/usr/bin/mysqldump")

    class FakeDump:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = io.BytesIO(b"sql")
            self.stderr = io.BytesIO(b"")

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(prepare_backup.subprocess, "Popen", FakeDump)
    dumped = prepare_backup.dump_databases(tmp_path, ["journal50_ojs"], 1, emit_progress=False)
    assert dumped == ["journal50_ojs"]
    assert emitted == []


def test_unpack_to_objects_reports_chunk_progress(tmp_path: Path):
    payload = b"abcdefghijklmnopqrstuvwxyz" * 80
    digest = hashlib.sha256(payload).hexdigest()
    buf = io.BytesIO()
    write_begin(buf)
    write_file(buf, "/var/www/app/index.html", [payload], len(payload), digest)
    write_end(buf)
    buf.seek(0)
    seen: list[dict] = []
    stored = unpack_to_objects(
        buf,
        tmp_path,
        lambda tmp, expected: tmp.replace(tmp_path / expected),
        on_progress=seen.append,
    )
    assert stored[0]["sha256"] == digest
    assert seen
    assert seen[-1]["files_done"] == 1
    assert seen[-1]["bytes_done"] == len(payload)
    assert any(item["bytes_done"] > 0 for item in seen)


def test_changed_database_progress_ends_complete(tmp_path: Path):
    from app.engine.backup_engine import BackupEngine

    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    ssh = LocalMasterSSH(tmp_path / "remote")
    ssh.db_fingerprint = "fp-journal-2"
    engine = BackupEngine(cfg, ssh=ssh)
    info = engine.run()
    assert info["type"] == "INCREMENTAL"
    assert "dump-databases" in ssh.calls
    data = engine.progress.read()
    assert data.get("database", {}).get("stage") == STAGE_COMPLETE
    assert data.get("database", {}).get("name") == "journal"


def test_dashboard_does_not_show_zero_percent_when_bytes_are_unknown(tmp_path: Path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow
    from tests.helpers import make_config

    qt = QApplication.instance() or QApplication([])
    cfg = make_config(tmp_path)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    window = MainWindow(cfg, ssh_password="in-memory")
    window.timer.stop()
    window.show()
    qt.processEvents()
    window.dashboard.render(
        {
            "backup_running": True,
            "live_message": "Dumping changed MariaDB databases…",
            "progress": {
                "status": "running",
                "operation": "BACKUP — FULL MASTER BASELINE",
                "application": "journal.50sea.com",
                "bytes_done": 0,
                "bytes_total": 0,
                "database": {
                    "name": "journal50_ojs",
                    "type": "MariaDB",
                    "stage": STAGE_DUMP_PREPARING,
                    "status": "running",
                },
                "overall": {"percent": None, "label": "Preparing...", "bytes_done": 0, "bytes_total": 0},
            },
        }
    )
    qt.processEvents()
    assert not window.dashboard.live_panel.isHidden()
    text = window.dashboard.live_panel.text()
    assert "BACKUP — FULL MASTER BASELINE" in text
    assert "journal50_ojs" in text
    assert "DATABASE DUMP PREPARING" in text
    assert "Overall: Preparing..." in text
    assert "Overall: 0%" not in text
    assert window.dashboard.progress_bar.format() == "Preparing..."
    window.close()
