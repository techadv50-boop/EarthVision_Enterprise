from __future__ import annotations

from pathlib import Path

import pytest

from app.backup.manual_preflight import MANUAL_BACKUP_NEED_PASSWORD, manual_backup_password_error
from app.config.schema import AppConfig
from app.engine.backup_engine import BackupEngine, BackupError
from app.ssh.client import SSHClient
from tests.helpers import make_config


def test_manual_preflight_requires_in_memory_password():
    assert manual_backup_password_error(None) == MANUAL_BACKUP_NEED_PASSWORD
    assert manual_backup_password_error("") == MANUAL_BACKUP_NEED_PASSWORD
    assert manual_backup_password_error("   ") == MANUAL_BACKUP_NEED_PASSWORD
    assert manual_backup_password_error("secret") is None


def test_require_paramiko_rejects_empty_password():
    cfg = AppConfig()
    with pytest.raises(Exception) as caught:
        SSHClient(cfg, password=None, require_paramiko=True)
    assert MANUAL_BACKUP_NEED_PASSWORD in str(caught.value)


def test_gui_manual_backup_with_password_uses_paramiko(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    cfg = AppConfig(ssh_private_key_path="")
    client = SSHClient(cfg, password="in-memory-secret", require_paramiko=True)
    assert client.uses_paramiko() is True
    assert client.transport_name() == "paramiko"


def test_gui_manual_backup_without_password_does_not_use_openssh(tmp_path: Path):
    cfg = make_config(tmp_path)
    client = SSHClient(cfg, password=None)
    assert client.uses_paramiko() is False
    engine = BackupEngine(cfg, ssh=client, mode="manual")
    with pytest.raises(BackupError) as caught:
        engine.run()
    assert MANUAL_BACKUP_NEED_PASSWORD in str(caught.value)
    assert engine.progress.read().get("head_state") in {None, "UNCHANGED", "unchanged"} or True
    data = engine.progress.read()
    assert data.get("status") == "failed"
    assert data.get("head_state") == "UNCHANGED"


def test_manual_mode_skips_paramiko_gate_for_non_sshclient(tmp_path: Path):
    from tests.helpers import FakeSSH

    cfg = make_config(tmp_path)
    engine = BackupEngine(cfg, ssh=FakeSSH(), mode="manual")
    engine._assert_manual_paramiko()


def test_gui_backup_now_source_has_no_openssh_fallback():
    source = (Path(__file__).resolve().parents[1] / "app" / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "require_paramiko=True" in source
    assert "_require_manual_backup_password" in source
    assert "manual_backup_password_error" in source
    assert "ensure_password()" in source  # still used for dry-run / discover
    backup_fn = source.split("def confirm_backup")[1].split("def confirm_rebuild")[0]
    assert "ensure_password()" not in backup_fn
    assert "require_paramiko=True" in backup_fn
