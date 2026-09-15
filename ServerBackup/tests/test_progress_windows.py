"""Windows progress.json must never abort a backup with WinError 5."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.backup.progress import ProgressReporter, _replace_with_retry
from app.engine.backup_engine import BackupEngine
from tests.helpers import FakeSSH, make_config


def _access_denied() -> PermissionError:
    exc = PermissionError(13, "Access is denied")
    exc.winerror = 5  # type: ignore[attr-defined]
    return exc


def test_replace_retries_then_succeeds(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.tmp"
    dest = tmp_path / "a.json"
    src.write_text("ok", encoding="utf-8")
    dest.write_text("old", encoding="utf-8")
    calls = {"n": 0}
    real = os.replace

    def flaky(source, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _access_denied()
        return real(source, target)

    monkeypatch.setattr("app.backup.progress.os.replace", flaky)
    _replace_with_retry(src, dest)
    assert dest.read_text(encoding="utf-8") == "ok"
    assert calls["n"] == 3


def test_replace_falls_back_to_inplace_write(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.tmp"
    dest = tmp_path / "progress.json"
    src.write_text('{"status": "running"}', encoding="utf-8")
    dest.write_text("{}", encoding="utf-8")

    def boom(_source, _target):
        raise _access_denied()

    monkeypatch.setattr("app.backup.progress.os.replace", boom)
    _replace_with_retry(src, dest)
    assert json.loads(dest.read_text(encoding="utf-8"))["status"] == "running"


def test_begin_survives_persistent_replace_failure(tmp_path: Path, monkeypatch):
    real = os.replace

    def boom(source, target):
        if Path(target).name == "progress.json":
            raise _access_denied()
        return real(source, target)

    monkeypatch.setattr("app.backup.progress.os.replace", boom)
    reporter = ProgressReporter(tmp_path / "progress.json")
    data = reporter.begin(operation_id="op-win5", operation="BACKUP")
    assert data["status"] == "running"
    assert data["operation_id"] == "op-win5"
    assert reporter.read()["status"] == "running"
    other = ProgressReporter(tmp_path / "progress.json")
    assert other.read()["operation_id"] == "op-win5"


def test_engine_begin_does_not_fail_backup_on_winerror_5(tmp_path: Path, monkeypatch):
    real = os.replace

    def boom(source, target):
        if Path(target).name == "progress.json":
            raise _access_denied()
        return real(source, target)

    monkeypatch.setattr("app.backup.progress.os.replace", boom)
    cfg = make_config(tmp_path)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    original = engine.progress.begin
    seen = {"began": False}

    def begin_and_stop(**kwargs):
        result = original(**kwargs)
        seen["began"] = True
        engine.progress.request_cancel()
        return result

    engine.progress.begin = begin_and_stop  # type: ignore[method-assign]
    try:
        engine.run()
    except Exception as exc:
        assert "Access is denied" not in str(exc)
        assert "WinError 5" not in str(exc)
    assert seen["began"] is True
    assert engine.progress.read()["operation_id"]
