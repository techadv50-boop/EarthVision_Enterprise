from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile
from pathlib import Path

from app.config.schema import AppConfig
from app.ssh.client import SSHResult

UBUNTU_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ubuntu"
if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))


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


def seed_remote_tree(base: Path) -> dict[str, str]:
    j50 = base / "var/www/journal.50sea.com"
    jxd = base / "var/www/journal.xdgen.com"
    xd = base / "var/www/xdgen.com"
    sea = base / "var/www/50sea.com"
    ojs50 = base / "var/lib/ojs-journal50"
    ojsxd = base / "var/www/ojs-files"
    nginx = base / "etc/nginx"
    for path in (j50, jxd, xd, sea, ojs50, ojsxd, nginx):
        path.mkdir(parents=True, exist_ok=True)
    (j50 / "config.inc.php").write_text(
        f"files_dir = {ojs50.as_posix()}\nversion = 3.4.0\n",
        encoding="utf-8",
    )
    (jxd / "config.inc.php").write_text(
        f"files_dir = {ojsxd.as_posix()}\nversion = 3.3.0\n",
        encoding="utf-8",
    )
    (j50 / "index.php").write_text("journal50-app\n", encoding="utf-8")
    (jxd / "index.php").write_text("journalxd-app\n", encoding="utf-8")
    (xd / "index.html").write_text("xdgen\n", encoding="utf-8")
    (sea / "index.html").write_text("50sea\n", encoding="utf-8")
    (ojs50 / "paper.pdf").write_bytes(b"%PDF-50sea")
    (ojsxd / "paper.pdf").write_bytes(b"%PDF-xdgen")
    (nginx / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    return {
        "journal.50sea.com": j50.as_posix(),
        "journal.xdgen.com": jxd.as_posix(),
        "xdgen.com": xd.as_posix(),
        "50sea.com": sea.as_posix(),
        "ojs50": ojs50.as_posix(),
        "ojsxd": ojsxd.as_posix(),
        "nginx": nginx.as_posix(),
    }


def master_config(tmp_path: Path, remote: dict[str, str], **overrides) -> AppConfig:
    return make_config(
        tmp_path,
        website_directories=[
            remote["journal.50sea.com"],
            remote["journal.xdgen.com"],
            remote["xdgen.com"],
            remote["50sea.com"],
        ],
        nginx_directory=remote["nginx"],
        ojs_private_files=remote["ojsxd"],
        **overrides,
    )


class _Proc:
    def __init__(self, data: bytes, returncode: int = 0) -> None:
        self.stdout = io.BytesIO(data)
        self.stderr = io.BytesIO(b"")
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode

    def poll(self) -> int:
        return self.returncode


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

    def ensure_remote_scripts(self) -> SSHResult:
        self.calls.append("ensure_scripts")
        return SSHResult(0, "", "already installed")

    def _discover_ojs(self, payload) -> dict:
        installs = []
        for app in payload.get("website_directories") or []:
            name = Path(str(app).rstrip("/")).name
            if name.startswith("journal."):
                files_dir = "/var/lib/ojs-journal50" if "50sea" in name else "/var/www/ojs-files"
                installs.append(
                    {
                        "domain": name,
                        "application_path": str(app).rstrip("/"),
                        "files_dir_raw": files_dir,
                        "files_dir": files_dir,
                        "exists": True,
                        "size_bytes": 1,
                        "file_count": 1,
                    }
                )
        return {"ok": True, "installations": installs, "errors": []}

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
        if action == "discover-ojs":
            return SSHResult(0, json.dumps(self._discover_ojs(payload)), "")
        if action == "discover-applications":
            return SSHResult(
                0,
                json.dumps(
                    {
                        "ok": True,
                        "nginx_ok": True,
                        "hostname": "ubuntu-server",
                        "discovery_source": "nginx -T",
                        "applications": [],
                        "databases": {"mariadb": ["journal"], "postgresql": []},
                        "errors": [],
                    }
                ),
                "",
            )
        if action == "inventory":
            return SSHResult(0, json.dumps({"ok": True, "files": [], "errors": []}), "")
        if action == "hash-files":
            return SSHResult(0, json.dumps({"ok": True, "hashes": [], "errors": []}), "")
        if action == "database-fingerprint":
            fps = [{"name": n, "sha256": "unchanged-fp"} for n in payload.get("databases") or []]
            return SSHResult(0, json.dumps({"ok": True, "fingerprints": fps, "errors": []}), "")
        if action == "dump-databases":
            return SSHResult(1, json.dumps({"ok": False, "error": "dump not stubbed"}), "dump not stubbed")
        if action == "restore-master":
            return SSHResult(0, json.dumps({"ok": True, "nginx_restarted": False, "message": "Restore completed. Nginx was not restarted."}), "")
        return SSHResult(0, "{}", "")

    def popen_script(self, script_path: str, payload):
        self.calls.append(payload.get("action"))
        return _Proc(b"")

    def scp_upload(self, local, remote) -> SSHResult:
        self.calls.append("scp")
        return SSHResult(0, "", "")

    def close(self) -> None:
        return None


class LocalMasterSSH(FakeSSH):
    """Runs discover/inventory/hash/stream against a local Unix tree."""

    def __init__(self, remote_root: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.remote_root = Path(remote_root)
        self.db_fingerprint = "fp-journal-1"
        self.fail_database = False
        self.fail_discover = False
        self.truncate_stream = False
        self.corrupt_stream = False
        self.fail_hash = False
        self.uploads: list[tuple[str, str]] = []

    def run_script(self, script_path: str, payload, *, timeout=None, use_sudo: bool = True) -> SSHResult:
        action = payload.get("action")
        self.calls.append(action)
        if action in {"check", "dry-run", "cleanup", "discover-databases"}:
            return super().run_script(script_path, payload, timeout=timeout, use_sudo=use_sudo)
        import prepare_master

        if action == "discover-ojs":
            if self.fail_discover:
                return SSHResult(
                    1,
                    json.dumps(
                        {
                            "ok": False,
                            "error": "discovery failed",
                            "installations": [],
                            "errors": ["discovery failed"],
                        }
                    ),
                    "discovery failed",
                )
            result = prepare_master.discover_ojs(payload)
            return SSHResult(0 if result.get("ok") else 1, json.dumps(result), result.get("error") or "")
        if action == "inventory":
            result = prepare_master.inventory(payload)
            return SSHResult(0 if result.get("ok") else 1, json.dumps(result), "")
        if action == "hash-files":
            if self.fail_hash:
                return SSHResult(1, json.dumps({"ok": False, "error": "hash failed", "hashes": [], "errors": ["hash failed"]}), "hash failed")
            result = prepare_master.hash_files(payload)
            return SSHResult(0 if result.get("ok") else 1, json.dumps(result), "")
        if action == "database-fingerprint":
            if self.fail_database:
                return SSHResult(
                    1,
                    json.dumps({"ok": False, "error": "fingerprint failed", "fingerprints": [], "errors": ["fingerprint failed"]}),
                    "fingerprint failed",
                )
            names = list(payload.get("databases") or [])
            fps = [{"name": n, "sha256": self.db_fingerprint} for n in names]
            return SSHResult(0, json.dumps({"ok": True, "fingerprints": fps, "errors": []}), "")
        if action == "dump-databases":
            if self.fail_database:
                return SSHResult(1, json.dumps({"ok": False, "error": "mysqldump failed"}), "mysqldump failed")
            work_id = "".join(ch for ch in str(payload.get("work_id") or "work") if ch.isalnum() or ch in "-_")
            dest = Path("/tmp") / f"server-backup-work-{work_id}" / "databases"
            dest.mkdir(parents=True, exist_ok=True)
            dumps = []
            for name in payload.get("databases") or []:
                path = dest / f"{name}.sql.gz"
                with gzip.open(path, "wb") as handle:
                    handle.write(b"SQL " + name.encode("utf-8") + b" " + self.db_fingerprint.encode("utf-8"))
                dumps.append({"name": name, "path": str(path), "size": path.stat().st_size})
            return SSHResult(0, json.dumps({"ok": True, "dumps": dumps}), "")
        if action == "restore-master":
            return SSHResult(
                0,
                json.dumps({"ok": True, "nginx_restarted": False, "message": "Restore completed. Nginx was not restarted."}),
                "",
            )
        return SSHResult(0, "{}", "")

    def popen_script(self, script_path: str, payload):
        self.calls.append(payload.get("action"))
        import prepare_master

        buf = io.BytesIO()

        class _Out:
            def __init__(self, buffer: io.BytesIO) -> None:
                self.buffer = buffer

            def write(self, _data) -> int:
                return 0

            def flush(self) -> None:
                return None

        old = sys.stdout
        sys.stdout = _Out(buf)  # type: ignore[assignment]
        try:
            prepare_master.stream_objects_lowmem(payload)
        finally:
            sys.stdout = old
        data = buf.getvalue()
        if self.truncate_stream:
            data = data[: max(4, len(data) // 2)]
        if self.corrupt_stream and len(data) > 50:
            data = data[:40] + b"\xff" + data[41:]
        return _Proc(data)

    def scp_upload(self, local, remote) -> SSHResult:
        self.calls.append("scp")
        self.uploads.append((str(local), str(remote)))
        Path(str(remote)).parent.mkdir(parents=True, exist_ok=True)
        Path(str(remote)).write_bytes(Path(local).read_bytes())
        return SSHResult(0, "", "")
