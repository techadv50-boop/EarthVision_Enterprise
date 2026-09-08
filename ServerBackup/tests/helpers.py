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
        f"files_dir = {ojs50.as_posix()}\nversion = 3.4.0\n[database]\nname = ojs50\n",
        encoding="utf-8",
    )
    (jxd / "config.inc.php").write_text(
        f"files_dir = {ojsxd.as_posix()}\nversion = 3.3.0\n[database]\nname = ojsxd\n",
        encoding="utf-8",
    )
    (j50 / "index.php").write_text("journal50-app\n", encoding="utf-8")
    (jxd / "index.php").write_text("journalxd-app\n", encoding="utf-8")
    (xd / "index.html").write_text("xdgen\n", encoding="utf-8")
    (sea / "index.html").write_text("50sea\n", encoding="utf-8")
    (sea / "wp-config.php").write_text("define('DB_NAME', 'sea_tedb');\n", encoding="utf-8")
    html = base / "var/www/html"
    html.mkdir(parents=True, exist_ok=True)
    (html / "index.nginx-debian.html").write_text("nginx default\n", encoding="utf-8")
    (ojs50 / "paper.pdf").write_bytes(b"%PDF-50sea")
    (ojsxd / "paper.pdf").write_bytes(b"%PDF-xdgen")
    (nginx / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    sateye = base / "opt/sateye/frontend"
    citation = base / "opt/citation/data"
    sateye.mkdir(parents=True, exist_ok=True)
    citation.mkdir(parents=True, exist_ok=True)
    return {
        "journal.50sea.com": j50.as_posix(),
        "journal.xdgen.com": jxd.as_posix(),
        "xdgen.com": xd.as_posix(),
        "50sea.com": sea.as_posix(),
        "ojs50": ojs50.as_posix(),
        "ojsxd": ojsxd.as_posix(),
        "nginx": nginx.as_posix(),
        "sateye.xdgen.com": sateye.as_posix(),
        "citation.xdgen.com": citation.as_posix(),
        "html": html.as_posix(),
    }


def master_config(tmp_path: Path, remote: dict[str, str], **overrides) -> AppConfig:
    values = {
        "website_directories": [
            remote["journal.50sea.com"],
            remote["journal.xdgen.com"],
            remote["xdgen.com"],
            remote["50sea.com"],
        ],
        "nginx_directory": remote["nginx"],
        "ojs_private_files": remote["ojsxd"],
    }
    values.update(overrides)
    return make_config(tmp_path, **values)


def enable_backup(cfg: AppConfig, ssh) -> dict:
    """Approve discovered applications so BACKUP NOW tests can pass the completeness gate."""
    from app.discover.engine import discover_applications
    from app.discover.policy import approve_all_applications

    result = discover_applications(cfg, ssh=ssh, persist=True)
    approve_all_applications(cfg.backup_destination, list(result.get("applications") or []))
    return result


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

    def _discover_applications(self) -> dict:
        def app(
            hostname: str,
            app_type: str,
            root: str = "",
            **extra,
        ) -> dict:
            persist = list(extra.get("persistent_data_paths") or [])
            sources = list(extra.get("source_paths") or ([root] if root else []) + persist)
            sources = [p for p in sources if p and not str(p).startswith("volume:")]
            hostnames = list(extra.get("hostnames") or [hostname])
            slug = app_type.lower().replace(" ", "-").replace("/", "-")
            ident = extra.get("application_id") or (f"{slug}:{root}" if root else hostname)
            row = {
                "application_id": ident,
                "hostname": hostname,
                "hostnames": hostnames,
                "type": app_type,
                "discovery_source": "nginx -T",
                "root": root,
                "alias": extra.get("alias") or [],
                "proxy_pass": extra.get("proxy_pass") or [],
                "database_type": extra.get("database_type") or "",
                "database_name": extra.get("database_name") or "",
                "persistent_data_paths": persist,
                "source_paths": list(dict.fromkeys(sources)),
                "docker": extra.get("docker"),
                "ojs_files_dir": extra.get("ojs_files_dir") or "",
                "estimated_bytes": extra.get("estimated_bytes", 2048),
                "status": extra.get("status") or "READY",
                "notes": extra.get("notes") or [],
                "included": False,
                "excluded": bool(extra.get("excluded")),
                "unused_default_root": bool(extra.get("unused_default_root")),
            }
            return row

        apps = [
            app(
                "journal.50sea.com",
                "OJS",
                "/var/www/journal.50sea.com",
                ojs_files_dir="/var/lib/ojs-journal50",
                database_type="MariaDB",
                database_name="ojs50",
                persistent_data_paths=["/var/lib/ojs-journal50"],
                estimated_bytes=4096,
            ),
            app(
                "journal.xdgen.com",
                "OJS",
                "/var/www/journal.xdgen.com",
                ojs_files_dir="/var/www/ojs-files",
                database_type="MariaDB",
                database_name="ojsxd",
                persistent_data_paths=["/var/www/ojs-files"],
            ),
            app(
                "xdgen.com",
                "Static",
                "/var/www/xdgen.com",
                hostnames=["xdgen.com", "www.xdgen.com"],
            ),
            app(
                "50sea.com",
                "WordPress",
                "/var/www/50sea.com",
                hostnames=["50sea.com", "www.50sea.com"],
                database_type="MariaDB",
                database_name="sea_tedb",
            ),
            app(
                "_",
                "Other",
                "/var/www/html",
                hostnames=["_"],
                status="EXCLUDED — UNUSED DEFAULT ROOT",
                excluded=True,
                unused_default_root=True,
                estimated_bytes=64,
            ),
            app(
                "citation.xdgen.com",
                "Docker",
                "",
                proxy_pass=["http://citation_web:8000"],
                database_type="PostgreSQL",
                database_name="citation",
                persistent_data_paths=["volume:citation_pgdata"],
                docker={
                    "compose_project": "citation",
                    "compose_file": "/opt/citation/docker-compose.yml",
                    "service": "citation_web",
                    "container": "citation_web",
                    "workdir": "/opt/citation",
                },
                source_paths=[],
                estimated_bytes=512,
            ),
        ]
        return {
            "ok": True,
            "nginx_ok": True,
            "hostname": "ubuntu-server",
            "discovery_source": "nginx -T",
            "applications": apps,
            "databases": {"mariadb": ["journal", "ojs50", "ojsxd", "sea_tedb", "xdgen_db"], "postgresql": ["citation"]},
            "database_inventory": [
                {"name": "journal", "type": "MariaDB", "application_id": "ojs:/var/www/journal.50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
                {"name": "ojs50", "type": "MariaDB", "application_id": "ojs:/var/www/journal.50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
                {"name": "ojsxd", "type": "MariaDB", "application_id": "ojs:/var/www/journal.xdgen.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
                {"name": "sea_tedb", "type": "MariaDB", "application_id": "wordpress:/var/www/50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
                {
                    "name": "xdgen_db",
                    "type": "MariaDB",
                    "application_id": "",
                    "status": "UNASSOCIATED DATABASE — REQUIRES REVIEW",
                    "reason": "no application association discovered",
                    "system": False,
                    "table_count": 3,
                    "size_bytes": 4096,
                },
            ],
            "inactive_hostnames": [
                {
                    "hostname": "sateye.xdgen.com",
                    "in_active_nginx": False,
                    "verdict": "NOT ACTIVE IN CURRENT SERVER CONFIGURATION",
                    "evidence": [
                        {
                            "source": "previous-discovery",
                            "file": "",
                            "detail": "seen in a previous discovery snapshot; not in active nginx -T or scanned configs",
                        }
                    ],
                }
            ],
            "database_account": {
                "configured_user": "root",
                "current_user": "root@localhost",
                "session_user": "root@localhost",
                "source": "/etc/serverbackup/my.cnf",
                "file_present": True,
                "using_root": True,
                "grants": ["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`"],
                "least_privilege": "A dedicated least-privilege backup account can replace root by updating /etc/serverbackup/my.cnf user=; credentials were not changed.",
            },
            "errors": [],
        }

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
                json.dumps({"ok": True, "databases": ["journal", "ojs50", "ojsxd", "sea_tedb", "xdgen_db", "information_schema"]}),
                "",
            )
        if action == "discover-ojs":
            return SSHResult(0, json.dumps(self._discover_ojs(payload)), "")
        if action == "discover-applications":
            return SSHResult(0, json.dumps(self._discover_applications()), "")
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

    def __init__(
        self,
        remote_root: Path,
        extra_mariadb: list[str] | None = None,
        extra_nginx_sites: list[tuple[str, str]] | None = None,
        extra_nginx_text: str = "",
        extra_scan_files: dict[str, str] | None = None,
        extra_config_files: dict[str, str] | None = None,
        extra_mariadb_details: dict | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.remote_root = Path(remote_root)
        self.extra_mariadb = list(extra_mariadb or [])
        self.extra_nginx_sites = list(extra_nginx_sites or [])
        self.extra_nginx_text = extra_nginx_text
        self.extra_scan_files = dict(extra_scan_files or {})
        self.extra_config_files = dict(extra_config_files or {})
        self.extra_mariadb_details = dict(extra_mariadb_details or {})
        self.db_fingerprint = "fp-journal-1"
        self.fail_database = False
        self.fail_discover = False
        self.truncate_stream = False
        self.corrupt_stream = False
        self.fail_hash = False
        self.uploads: list[tuple[str, str]] = []
        self._previous_hostnames: list[str] = []

    def _local_discover_applications(self) -> dict:
        import discover_apps as da

        root = self.remote_root
        www = root / "var/www"
        lines = ["# configuration file /etc/nginx/nginx.conf:", "http {"]
        for name in ("journal.50sea.com", "journal.xdgen.com"):
            child = www / name
            if not child.is_dir():
                continue
            lines.extend(
                [
                    f"# configuration file /etc/nginx/sites-enabled/{name}:",
                    "server {",
                    "    listen 80;",
                    f"    server_name {name};",
                    f"    root {child.as_posix()};",
                    "}",
                ]
            )
        xdgen = www / "xdgen.com"
        if xdgen.is_dir():
            lines.extend(
                [
                    "# configuration file /etc/nginx/sites-enabled/xdgen.com:",
                    "server {",
                    "    listen 80;",
                    "    server_name xdgen.com www.xdgen.com;",
                    f"    root {xdgen.as_posix()};",
                    "}",
                ]
            )
        sea = www / "50sea.com"
        if sea.is_dir():
            lines.extend(
                [
                    "# configuration file /etc/nginx/sites-enabled/50sea.com:",
                    "server {",
                    "    listen 80;",
                    "    server_name 50sea.com www.50sea.com;",
                    f"    root {sea.as_posix()};",
                    "}",
                ]
            )
        html = www / "html"
        if html.is_dir():
            lines.extend(
                [
                    "# configuration file /etc/nginx/sites-enabled/default:",
                    "server {",
                    "    listen 80 default_server;",
                    "    listen [::]:80 default_server;",
                    "    server_name _;",
                    f"    root {html.as_posix()};",
                    "}",
                ]
            )
        for hostname, site_root in self.extra_nginx_sites:
            lines.extend(
                [
                    f"# configuration file /etc/nginx/sites-enabled/{hostname}:",
                    "server {",
                    "    listen 80;",
                    f"    server_name {hostname};",
                    f"    root {site_root};",
                    "}",
                ]
            )
        if self.extra_nginx_text:
            lines.append(self.extra_nginx_text)
        citation_data = root / "opt/citation/data"
        lines.extend(
            [
                "# configuration file /etc/nginx/sites-enabled/citation:",
                "server {",
                "    listen 80;",
                "    server_name citation.xdgen.com;",
                "    location / {",
                "        proxy_pass http://citation_web:8000;",
                "    }",
                "}",
                "}",
            ]
        )
        docker = [
            {
                "Id": "abc123def456",
                "Name": "/citation_web",
                "Config": {
                    "Image": "citation:latest",
                    "Labels": {
                        "com.docker.compose.project": "citation",
                        "com.docker.compose.service": "citation_web",
                        "com.docker.compose.project.working_dir": str((root / "opt/citation").as_posix()),
                        "com.docker.compose.project.config_files": str((root / "opt/citation/docker-compose.yml").as_posix()),
                    },
                    "Env": ["POSTGRES_DB=citation"],
                },
                "HostConfig": {"PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}},
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": citation_data.as_posix(),
                        "Destination": "/data",
                    },
                    {"Type": "volume", "Name": "citation_pgdata", "Destination": "/var/lib/postgresql/data"},
                ],
            }
        ]
        mariadb = ["ojs50", "ojsxd", "sea_tedb", *self.extra_mariadb]
        for name in self.extra_mariadb_details:
            if name not in mariadb:
                mariadb.append(name)
        import discover_audit as audit

        servers = da.parse_nginx_t("\n".join(lines))
        apps = da.applications_from_servers(
            servers,
            docker_containers=docker,
            mariadb=mariadb,
        )
        postgres = sorted(
            {
                str(app.get("database_name"))
                for app in apps
                if app.get("database_type") == "PostgreSQL" and app.get("database_name")
            }
        )
        details = {
            name: {
                "size_bytes": 1024,
                "table_count": 4,
                "created": "",
                "updated": "",
                "grants": ["GRANT SELECT ON *.* TO 'backup'@'localhost'"],
            }
            for name in mariadb
        }
        for name in self.extra_mariadb:
            details[name]["table_count"] = 2
            details[name]["size_bytes"] = 4096
        for name, meta in self.extra_mariadb_details.items():
            details.setdefault(
                name,
                {"size_bytes": 0, "table_count": 0, "created": "", "updated": "", "grants": []},
            )
            details[name].update(meta)
        extra_texts = dict(self.extra_config_files)
        extra_texts.update(audit.docker_database_texts(docker))
        search_roots = [str(app.get("root") or "") for app in apps if app.get("root")]
        references = audit.find_database_references(
            mariadb,
            search_roots,
            extra_texts=extra_texts,
            extra_roots=(),
        )
        inventory = audit.build_database_inventory(mariadb, apps, details=details, references=references)
        by_id = {str(app.get("application_id") or ""): app for app in apps}
        for row in inventory:
            ident = str(row.get("application_id") or "")
            app = by_id.get(ident)
            if app and row.get("name") and not app.get("database_name") and str(row.get("status") or "").startswith("ASSOCIATED"):
                app["database_name"] = row["name"]
                app["database_type"] = "MariaDB"
        previous = list(getattr(self, "_previous_hostnames", []) or [])
        return {
            "ok": True,
            "nginx_ok": True,
            "hostname": "ubuntu-test",
            "discovery_source": "nginx -T",
            "applications": apps,
            "nginx_inventory": da.nginx_inventory(servers),
            "parsed_hostnames": da.parsed_hostnames(servers),
            "inactive_hostnames": audit.scan_inactive_hostnames(
                da.parsed_hostnames(servers),
                previous_hostnames=previous,
                parse_nginx_t=da.parse_nginx_t,
                extra_files=self.extra_scan_files,
            ),
            "database_inventory": inventory,
            "database_account": {
                "configured_user": "backup",
                "current_user": "backup@localhost",
                "source": "/etc/serverbackup/my.cnf",
                "file_present": True,
                "using_root": False,
                "grants": ["GRANT SELECT ON *.* TO 'backup'@'localhost'"],
                "least_privilege": "least-privilege backup account in use",
            },
            "databases": {"mariadb": mariadb, "postgresql": postgres},
            "errors": [],
        }

    def run_script(self, script_path: str, payload, *, timeout=None, use_sudo: bool = True) -> SSHResult:
        action = payload.get("action")
        self.calls.append(action)
        if action in {"check", "dry-run", "cleanup", "discover-databases"}:
            return super().run_script(script_path, payload, timeout=timeout, use_sudo=use_sudo)
        import prepare_master

        if action == "discover-applications":
            if self.fail_discover:
                return SSHResult(
                    1,
                    json.dumps(
                        {
                            "ok": False,
                            "error": "discovery failed",
                            "applications": [],
                            "errors": ["discovery failed"],
                            "nginx_ok": False,
                        }
                    ),
                    "discovery failed",
                )
            self._previous_hostnames = list(payload.get("previous_hostnames") or [])
            result = self._local_discover_applications()
            return SSHResult(0 if result.get("ok") else 1, json.dumps(result), result.get("error") or "")

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
