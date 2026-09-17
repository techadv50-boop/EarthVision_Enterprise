from __future__ import annotations

import json
from pathlib import Path

from app.backup.lock import BackupLock
from app.config.schema import AppConfig
from app.serversec.classify import classify_change, overall_assessment
from app.serversec.credentials import proposed_rotation, rotate_local_token
from app.serversec.diff import compare_snapshots
from app.serversec.engine import SecurityEngine, SecurityError
from app.serversec.snapshot import SecurityStore
from app.ssh.client import SSHResult
from tests.helpers import FakeSSH, make_config


def _audit_payload(**overrides) -> dict:
    data = {
        "ok": True,
        "hostname": "ubuntu-server",
        "collected_at_unix": 1_700_000_000,
        "health": {
            "summary": "HEALTHY",
            "services": [
                {"name": "nginx", "active": True},
                {"name": "mariadb", "active": True},
                {"name": "ssh", "active": True},
            ],
        },
        "layer1": {
            "sshd": {
                "PasswordAuthentication": "no",
                "PermitRootLogin": "no",
                "Port": "22",
                "MaxAuthTries": "3",
            },
            "firewall_active": True,
            "listening_ports": ["0.0.0.0:22", "0.0.0.0:80", "0.0.0.0:443"],
            "fail2ban": "active",
        },
        "layer2": {
            "users": [{"name": "zhz", "uid": 1000, "shell": "/bin/bash"}],
            "sudo_unrestricted": False,
            "authorized_key_fps": ["aa:bb"],
        },
        "integrity": {"examined": 2, "hashed": 1},
        "files": [
            {
                "path": "/etc/nginx/nginx.conf",
                "mode": "0o644",
                "uid": 0,
                "gid": 0,
                "size": 100,
                "mtime": 10,
                "ino": 1,
                "dev": 1,
                "sha256": "abc",
            },
            {
                "path": "/var/www/xdgen.com/index.php",
                "mode": "0o644",
                "uid": 33,
                "gid": 33,
                "size": 20,
                "mtime": 10,
                "ino": 2,
                "dev": 1,
                "sha256": "def",
            },
        ],
    }
    data.update(overrides)
    return data


class SecuritySSH(FakeSSH):
    def __init__(self, payload: dict | None = None) -> None:
        super().__init__()
        self.payload = payload or _audit_payload()

    def run_script(self, script_path: str, payload, *, timeout=None, use_sudo: bool = True) -> SSHResult:
        action = payload.get("action")
        self.calls.append(action)
        if action == "security-audit":
            return SSHResult(0, json.dumps(self.payload), "")
        if action in {"security-rotate-token", "security-rollback"}:
            return SSHResult(0, json.dumps({"ok": True, "message": action}), "")
        return super().run_script(script_path, payload, timeout=timeout, use_sudo=use_sudo)


def test_default_security_mode_is_balanced():
    assert AppConfig().security_mode == "BALANCED"


def test_cache_change_is_expected():
    finding = classify_change({"kind": "modified", "path": "/var/www/site/cache/foo.tmp", "layer": "3"})
    assert finding["severity"] == "EXPECTED/APPROPRIATE"


def test_web_shell_is_critical():
    finding = classify_change({"kind": "created", "path": "/var/www/site/c99.php", "layer": "3"})
    assert finding["severity"] == "CRITICAL"


def test_compare_detects_hash_and_new_user():
    left = _audit_payload()
    right = _audit_payload()
    right["files"][0]["sha256"] = "changed"
    right["layer2"]["users"] = [{"name": "zhz", "uid": 1000}, {"name": "intruder", "uid": 0}]
    raw = compare_snapshots(left, right)
    kinds = {item["kind"] for item in raw}
    assert "hash_changed" in kinds
    assert "uid0_user_added" in kinds
    findings = [classify_change(item) for item in raw]
    assert overall_assessment(findings) == "CRITICAL"


def test_credential_rotation_requires_confirmation_and_omits_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    store = SecurityStore(tmp_path / "sec")
    try:
        rotate_local_token(store, confirmation="nope")
        assert False
    except ValueError:
        pass
    result = rotate_local_token(store, confirmation="ROTATE")
    assert result["new_token"]
    saved = (tmp_path / "cfg" / "ServerBackup" / "security-credentials.json").read_text(encoding="utf-8")
    assert result["new_token"] not in saved
    assert "password" not in saved
    points = store.list_rollback_points()
    assert points
    dumped = json.dumps(points)
    assert result["new_token"] not in dumped
    proposal = proposed_rotation()
    assert "MariaDB passwords" in proposal["will_not_change"]


def test_security_check_skips_when_backup_running(tmp_path):
    cfg = make_config(tmp_path, security_store=str(tmp_path / "sec"))
    lock = BackupLock(cfg.backup_destination)
    lock.acquire(mode="manual", backup_id="running")
    engine = SecurityEngine(cfg, ssh=SecuritySSH())
    try:
        engine.audit()
        assert False
    except SecurityError as exc:
        assert "backup is running" in str(exc).lower()
    lock.release()


def test_security_audit_creates_snapshot_and_report(tmp_path):
    cfg = make_config(tmp_path, security_store=str(tmp_path / "sec"))
    engine = SecurityEngine(cfg, ssh=SecuritySSH())
    report = engine.audit()
    assert report["enforcement"].startswith("audit-only")
    assert report["security_mode"] == "BALANCED"
    assert Path(cfg.security_store, "snapshots", f"{report['id']}.json.gz").is_file()
    store = SecurityStore(cfg.security_store)
    assert store.trusted_id() == report["id"]

    ssh = SecuritySSH(_audit_payload())
    ssh.payload["files"][1]["sha256"] = "newhash"
    engine2 = SecurityEngine(cfg, ssh=ssh)
    report2 = engine2.audit()
    kinds = {item["kind"] for item in report2["findings"]}
    assert "hash_changed" in kinds
    remaining = [p.name for p in Path(cfg.security_store, "snapshots").glob("*.json.gz")]
    assert len(remaining) == 2


def test_failed_security_operation_does_not_write_trusted(tmp_path):
    cfg = make_config(tmp_path, security_store=str(tmp_path / "sec"))

    class Boom(SecuritySSH):
        def run_script(self, script_path, payload, *, timeout=None, use_sudo=True):
            return SSHResult(1, "", "permission denied")

    engine = SecurityEngine(cfg, ssh=Boom())
    try:
        engine.audit()
        assert False
    except SecurityError:
        pass
    store = SecurityStore(cfg.security_store)
    assert store.list_snapshots() == []
    assert store.trusted_id() is None
