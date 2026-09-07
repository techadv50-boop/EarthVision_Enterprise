from __future__ import annotations

import json
import tarfile
from pathlib import Path

from app.config.schema import AppConfig
from app.ssh.client import SSHResult


def make_config(tmp_path: Path, **overrides) -> AppConfig:
    cfg = AppConfig(
        backup_destination=str(tmp_path / "ServerBackups"),
        log_directory=str(tmp_path / "logs"),
        min_free_disk_gb=0.001,
        min_remote_free_disk_gb=0.001,
        retry_count=1,
        retry_delay_seconds=1,
        retention_count=5,
        ssh_private_key_path="",
        selected_databases=["journal"],
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    Path(cfg.log_directory).mkdir(parents=True, exist_ok=True)
    return cfg


def write_success_backup(root: Path, backup_id: str, size: int = 100) -> Path:
    directory = root / backup_id
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "server-backup.tar.gz"
    archive.write_bytes(b"x" * size)
    info = {
        "backup_id": backup_id,
        "status": "SUCCESS",
        "backup_size": size,
        "sha256": "abc",
        "timestamp": backup_id.replace("_", " "),
        "duration_seconds": 60,
    }
    (directory / "backup-info.json").write_text(json.dumps(info), encoding="utf-8")
    (directory / "backup.log").write_text("ok\n", encoding="utf-8")
    return directory


def make_valid_archive(path: Path, *, databases: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    databases = databases or ["journal"]
    with tarfile.open(path, "w:gz") as archive:
        manifest = path.parent / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        archive.add(manifest, arcname="manifest.json")
        nginx_conf = path.parent / "nginx.conf"
        nginx_conf.write_text("events {}\n", encoding="utf-8")
        archive.add(nginx_conf, arcname="nginx/nginx.conf")
        for name in ["journal.50sea.com", "journal.xdgen.com", "xdgen.com"]:
            site = path.parent / name
            site.write_text("site", encoding="utf-8")
            archive.add(site, arcname=f"websites/{name}")
        ojs = path.parent / "ojs-files"
        ojs.write_text("ojs", encoding="utf-8")
        archive.add(ojs, arcname="ojs/ojs-files")
        for db in databases:
            dump = path.parent / f"{db}.sql.gz"
            dump.write_bytes(b"sql")
            archive.add(dump, arcname=f"databases/{db}.sql.gz")
    return path


class FakeSSH:
    def __init__(self, *, login_ok: bool = True, check_ok: bool = True, free_gb: float = 80.0) -> None:
        self.login_ok = login_ok
        self.check_ok = check_ok
        self.free_gb = free_gb
        self.calls: list[str] = []

    def test_login(self) -> SSHResult:
        self.calls.append("login")
        if self.login_ok:
            return SSHResult(0, "ok", "")
        return SSHResult(255, "", "Permission denied")

    def run_script(self, script_path: str, payload, *, timeout=None, use_sudo: bool = True) -> SSHResult:
        action = payload.get("action")
        self.calls.append(action)
        if action in {"check", "dry-run"}:
            body = {
                "ok": self.check_ok,
                "hostname": "ubuntu-server",
                "free_gb": self.free_gb,
                "checks": [
                    {"name": "website", "ok": True},
                    {"name": "OJS private files", "ok": True},
                    {"name": "Nginx", "ok": True},
                    {"name": "MariaDB ping", "ok": True},
                ],
            }
            stdout = json.dumps(body)
            return SSHResult(0 if self.check_ok else 1, stdout, "" if self.check_ok else "check failed")
        if action == "cleanup":
            return SSHResult(0, json.dumps({"ok": True}), "")
        if action == "discover-databases":
            return SSHResult(
                0,
                json.dumps({"ok": True, "databases": ["journal", "information_schema"]}),
                "",
            )
        return SSHResult(0, "{}", "")
