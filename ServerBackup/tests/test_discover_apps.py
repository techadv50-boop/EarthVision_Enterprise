from __future__ import annotations

import json
import sys
from pathlib import Path

from app.discover.engine import discover_applications
from app.discover.policy import apply_policy, approve_all_applications, save_snapshot, set_approval
from app.discover.report import format_discovery_report
from app.security.allowlist import is_allowed_remote_action
from tests.helpers import FakeSSH, UBUNTU_SCRIPTS, make_config

if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))
import discover_apps as da  # noqa: E402


NGINX_T = """
# configuration file /etc/nginx/nginx.conf:
user www-data;
http {
# configuration file /etc/nginx/sites-enabled/journal.50sea.com:
server {
    listen 80;
    listen 443 ssl;
    server_name journal.50sea.com;
    root /var/www/journal.50sea.com;
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }
    location /files {
        alias /var/lib/ojs-journal50;
    }
}
# configuration file /etc/nginx/sites-enabled/journal.xdgen.com:
server {
    listen 80;
    server_name journal.xdgen.com;
    root /var/www/journal.xdgen.com;
}
# configuration file /etc/nginx/sites-enabled/static.conf:
server {
    listen 80;
    server_name xdgen.com www.xdgen.com;
    root /var/www/xdgen.com;
    location / {
        index index.html;
    }
}
# configuration file /etc/nginx/sites-enabled/50sea.conf:
server {
    listen 80;
    server_name 50sea.com;
    root /var/www/50sea.com;
}
# configuration file /etc/nginx/sites-enabled/sateye.conf:
server {
    listen 80;
    server_name sateye.xdgen.com;
    root /var/www/50sea.com;
}
# configuration file /etc/nginx/sites-enabled/default:
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    root /var/www/html;
}
# configuration file /etc/nginx/sites-enabled/citation.conf:
server {
    listen 80;
    server_name citation.xdgen.com;
    location / {
        proxy_pass http://citation_web:8000;
    }
}
# configuration file /etc/nginx/sites-enabled/future.conf:
server {
    listen 80;
    server_name future-site.example.com;
    root /var/www/future-site.example.com;
}
# configuration file /etc/nginx/sites-enabled/dup.conf:
server {
    listen 80;
    server_name duplicate.example.com;
    root /var/www/dup-a;
}
server {
    listen 443 ssl;
    server_name duplicate.example.com;
    root /var/www/dup-b;
}
# configuration file /etc/nginx/sites-enabled/missing.conf:
server {
    listen 80;
    server_name missing.example.com;
    root /var/www/does-not-exist;
}
# configuration file /etc/nginx/sites-enabled/docker-internal.conf:
server {
    listen 80;
    server_name overlay.example.com;
    root /var/lib/docker/overlay2/abc;
}
}
"""


def _probe(root: str):
    files = {
        "/var/www/journal.50sea.com": (
            {"config.inc.php": True, "index.php": True},
            {
                "config.inc.php": "files_dir = /var/lib/ojs-journal50\n[database]\nname = ojs50\npassword = secret\n"
            },
        ),
        "/var/www/journal.xdgen.com": (
            {"config.inc.php": True, "index.php": True},
            {"config.inc.php": "files_dir = /var/www/ojs-files\n[database]\nname = ojsxd\n"},
        ),
        "/var/www/xdgen.com": ({"index.html": True}, {}),
        "/var/www/50sea.com": (
            {"index.php": True, "wp-config.php": True, "wp-includes": True},
            {"wp-config.php": "define('DB_NAME', 'sea_tedb');\n"},
        ),
        "/var/www/html": ({"index.html": True}, {}),
        "/var/www/future-site.example.com": ({"index.html": True}, {}),
        "/var/www/dup-a": ({"index.html": True}, {}),
        "/var/www/dup-b": ({"index.html": True}, {}),
    }
    return files.get(root, ({}, {}))


def _exists(path: str) -> bool:
    return path not in {"/var/www/does-not-exist", "/missing/ojs-files"}


def _by_host(apps):
    mapping = {}
    for app in apps:
        names = list(app.get("hostnames") or [])
        if app.get("hostname") and app.get("hostname") not in names:
            names.insert(0, app.get("hostname"))
        for name in names:
            mapping[name] = app
    return mapping


def _apps(**kwargs):
    servers = da.parse_nginx_t(NGINX_T)
    docker = [
        {
            "Id": "abc123def456",
            "Name": "/citation_web",
            "Config": {
                "Image": "citation:latest",
                "Labels": {
                    "com.docker.compose.project": "citation",
                    "com.docker.compose.service": "citation_web",
                    "com.docker.compose.project.working_dir": "/opt/citation",
                    "com.docker.compose.project.config_files": "/opt/citation/docker-compose.yml",
                },
                "Env": ["POSTGRES_DB=citation", "POSTGRES_PASSWORD=nope"],
            },
            "HostConfig": {"PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}},
            "Mounts": [
                {"Type": "bind", "Source": "/opt/citation/data", "Destination": "/data"},
                {"Type": "volume", "Name": "citation_pgdata", "Destination": "/var/lib/postgresql/data"},
            ],
        }
    ]
    return da.applications_from_servers(
        servers,
        probe=_probe,
        path_exists=_exists,
        docker_containers=docker,
        mariadb=["ojs50", "ojsxd", "sea_tedb", "mysql"],
        **kwargs,
    )


def test_parses_multiple_server_names_and_roots():
    servers = da.parse_nginx_t(NGINX_T)
    names = {name for block in servers for name in block["server_name"]}
    assert "journal.50sea.com" in names
    assert "journal.xdgen.com" in names
    assert "xdgen.com" in names
    assert "www.xdgen.com" in names
    assert "50sea.com" in names
    assert "sateye.xdgen.com" in names
    assert "citation.xdgen.com" in names
    assert "future-site.example.com" in names
    by_host = {block["server_name"][0]: block for block in servers}
    assert by_host["journal.50sea.com"]["root"] == "/var/www/journal.50sea.com"
    assert "/var/lib/ojs-journal50" in by_host["journal.50sea.com"]["alias"]
    assert by_host["citation.xdgen.com"]["proxy_pass"] == ["http://citation_web:8000"]
    assert not any(block.get("root") == "/var/www" for block in servers)


def test_alias_and_proxy_pass_and_docker():
    apps = _by_host(_apps())
    assert apps["journal.50sea.com"]["type"] == "OJS"
    assert apps["journal.50sea.com"]["ojs_files_dir"] == "/var/lib/ojs-journal50"
    assert apps["citation.xdgen.com"]["type"] == "Docker"
    assert apps["citation.xdgen.com"]["docker"]["compose_project"] == "citation"
    assert "volume:citation_pgdata" in apps["citation.xdgen.com"]["persistent_data_paths"]
    assert "/opt/citation/data" in apps["citation.xdgen.com"]["persistent_data_paths"]
    assert "/var/lib/docker" not in str(apps["citation.xdgen.com"]["source_paths"])
    assert apps["citation.xdgen.com"]["database_type"] == "PostgreSQL"
    assert apps["citation.xdgen.com"]["database_name"] == "citation"


def test_ojs_files_dir_and_no_silent_fallback():
    servers = [
        {
            "server_name": ["journal.example.com"],
            "root": "/var/www/journal.example.com",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/sites-enabled/journal",
            "listen": ["80"],
            "http": True,
            "https": False,
        }
    ]

    def probe(_root):
        return (
            {"config.inc.php": True},
            {"config.inc.php": "version = 3.4.0\nbase_url = https://journal.example.com\n"},
        )

    apps = da.applications_from_servers(
        servers,
        probe=probe,
        path_exists=lambda p: p != "/var/www/ojs-files",
    )
    assert apps[0]["type"] == "OJS"
    assert apps[0]["status"] == "REQUIRES REVIEW"
    assert any("fallback" in note or "does not exist" in note or "files_dir" in note for note in apps[0]["notes"])
    assert apps[0]["ojs_files_dir"] != "/var/www/ojs-files" or "fallback" in " ".join(apps[0]["notes"])


def test_missing_ojs_files_dir_requires_review():
    servers = [
        {
            "server_name": ["journal.example.com"],
            "root": "/var/www/journal.example.com",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/x",
            "listen": ["80"],
            "http": True,
            "https": False,
        }
    ]
    apps = da.applications_from_servers(
        servers,
        probe=lambda _r: ({"config.inc.php": True}, {"config.inc.php": "version = 3.4.0\n"}),
        path_exists=lambda _p: True,
    )
    assert apps[0]["status"] == "REQUIRES REVIEW"
    assert any("files_dir" in note for note in apps[0]["notes"])


def test_classification_wordpress_python_node_static_php():
    def make(files, texts=None, proxy=None, docker=None):
        servers = [
            {
                "server_name": ["app.example.com"],
                "root": "/var/www/app",
                "alias": [],
                "proxy_pass": proxy or [],
                "source_file": "/etc/nginx/x",
                "listen": ["80"],
                "http": True,
                "https": False,
            }
        ]
        return da.applications_from_servers(
            servers,
            probe=lambda _r: (files, texts or {}),
            path_exists=lambda _p: True,
            docker_containers=docker or [],
        )[0]["type"]

    assert make({"wp-config.php": True}) == "WordPress"
    assert make({"requirements.txt": True}, {"requirements.txt": "fastapi\nuvicorn\n"}) == "Python/FastAPI"
    assert make({"package.json": True}) == "Node"
    assert make({"index.html": True}) == "Static"
    assert make({"index.php": True}) == "PHP"
    assert make({}, proxy=["http://127.0.0.1:9000"]) == "Reverse Proxy"


def test_new_and_removed_sites(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    first = [
        {
            "application_id": "static:/var/www/a",
            "hostname": "a.example.com",
            "hostnames": ["a.example.com"],
            "type": "Static",
            "root": "/var/www/a",
            "status": "READY",
        }
    ]
    save_snapshot(dest, {"applications": first})
    set_approval(dest, "static:/var/www/a", approved=True)
    current = [
        {
            "application_id": "static:/var/www/b",
            "hostname": "b.example.com",
            "hostnames": ["b.example.com"],
            "type": "Static",
            "root": "/var/www/b",
            "status": "READY",
        }
    ]
    rows = apply_policy(current, dest)
    hosts = {row["hostname"]: row for row in rows}
    assert hosts["b.example.com"]["status"] == "NEW SITE DETECTED — REQUIRES APPROVAL"
    assert hosts["a.example.com"]["status"] == "SITE REMOVED — REQUIRES REVIEW"
    assert hosts["a.example.com"]["change"] == "removed"


def test_invalid_root_and_duplicate_hostname_and_excluded_docker_storage():
    apps = _apps()
    missing = [app for app in apps if "missing.example.com" in (app.get("hostnames") or [app.get("hostname")])][0]
    assert missing["status"] == "REQUIRES REVIEW"
    assert any("invalid root" in note for note in missing["notes"])
    dups = [app for app in apps if "duplicate.example.com" in (app.get("hostnames") or [app.get("hostname")])]
    assert len(dups) == 2
    assert all(app["status"] == "REQUIRES REVIEW" for app in dups)
    overlay = [app for app in apps if "overlay.example.com" in (app.get("hostnames") or [app.get("hostname")])][0]
    assert overlay["excluded"] is True or overlay["status"] == "REQUIRES REVIEW"
    assert overlay.get("root") in {"", "/var/lib/docker/overlay2/abc"}
    sources = [p for app in apps for p in app.get("source_paths") or []]
    assert all(not str(p).startswith("/var/lib/docker") for p in sources)
    assert all(not str(p).startswith("/var/www/") or p != "/var/www" for p in sources)


def test_tmp_scratch_is_excluded_but_nested_app_trees_are_not():
    assert da.is_excluded_path("/tmp") is True
    assert da.is_excluded_path("/tmp/server-backup-work-abc/databases") is True
    assert da.is_excluded_path("/tmp/pytest-of-ubuntu/remote/var/www/journal.50sea.com") is False
    assert da.is_excluded_path("/var/lib/docker/overlay2/abc") is True


def test_database_association_and_secret_redaction():
    apps = _by_host(_apps())
    assert apps["journal.50sea.com"]["database_name"] == "ojs50"
    assert apps["journal.50sea.com"]["database_type"] == "MariaDB"
    blob = json.dumps(apps["journal.50sea.com"])
    assert "secret" not in blob
    report = format_discovery_report({"applications": list(apps.values()), "nginx_ok": True, "hostname": "ubuntu"})
    assert "DISCOVERY REPORT" in report
    assert "journal.50sea.com" in report
    assert "NEW SITE DETECTED" in report or "OJS" in report
    assert "secret" not in report


def test_future_site_is_discovered_without_hardcoded_list():
    hosts = set(_by_host(_apps()))
    assert "future-site.example.com" in hosts
    assert "sateye.xdgen.com" in hosts
    source = (Path(__file__).resolve().parents[1] / "scripts" / "ubuntu" / "discover_apps.py").read_text(encoding="utf-8")
    assert "future-site.example.com" not in source
    assert "sateye.xdgen.com" not in source


def test_helper_allows_discover_applications():
    assert is_allowed_remote_action("discover-applications")
    from app.ssh.client import bundled_ubuntu_scripts
    import subprocess

    script = bundled_ubuntu_scripts() / "prepare-backup.sh"
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps({"action": "discover-applications"}),
        text=True,
        capture_output=True,
        cwd=str(script.parent),
    )
    assert "action not allowed" not in (result.stderr + result.stdout)


def test_windows_engine_uses_helper_and_does_not_write_head(tmp_path: Path):
    cfg = make_config(tmp_path)
    ssh = FakeSSH()
    result = discover_applications(cfg, ssh=ssh, persist=True)
    assert "discover-applications" in ssh.calls
    assert "backup" not in ssh.calls
    assert result.get("report_text")
    assert not (Path(cfg.backup_destination) / "master" / "HEAD").exists()


def test_www_alias_in_same_server_block_is_one_application():
    apps = _apps()
    hosts = _by_host(apps)
    xdgen = hosts["xdgen.com"]
    www = hosts["www.xdgen.com"]
    assert xdgen is www
    assert xdgen["application_id"] == "static:/var/www/xdgen.com"
    assert set(xdgen["hostnames"]) == {"xdgen.com", "www.xdgen.com"}
    assert sum(1 for app in apps if app.get("root") == "/var/www/xdgen.com") == 1


def test_shared_root_and_database_merges_hostnames():
    hosts = _by_host(_apps())
    sea = hosts["50sea.com"]
    sateye = hosts["sateye.xdgen.com"]
    assert sea is sateye
    assert sea["application_id"] == "wordpress:/var/www/50sea.com"
    assert set(sea["hostnames"]) == {"50sea.com", "sateye.xdgen.com"}
    assert sea["database_name"] == "sea_tedb"
    assert sea["type"] == "WordPress"


def test_same_root_different_database_is_not_merged():
    servers = [
        {
            "server_name": ["a.example.com"],
            "root": "/var/www/shared",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/a",
            "listen": ["80"],
            "http": True,
            "https": False,
        },
        {
            "server_name": ["b.example.com"],
            "root": "/var/www/shared",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/b",
            "listen": ["80"],
            "http": True,
            "https": False,
        },
    ]
    queue = ["db_a", "db_b"]

    def probe(_root):
        name = queue.pop(0)
        return ({"wp-config.php": True, "wp-includes": True}, {"wp-config.php": f"define('DB_NAME', '{name}');\n"})

    apps = da.applications_from_servers(servers, probe=probe, path_exists=lambda _p: True)
    assert len([a for a in apps if a.get("root") == "/var/www/shared"]) == 2
    names = {name for app in apps for name in (app.get("hostnames") or [])}
    assert names == {"a.example.com", "b.example.com"}
    dbs = {app.get("database_name") for app in apps if app.get("root") == "/var/www/shared"}
    assert dbs == {"db_a", "db_b"}


def test_unused_default_html_is_excluded():
    html = _by_host(_apps()).get("_") or next(
        app for app in _apps() if app.get("unused_default_root") or is_default_html_root(app.get("root") or "")
    )
    assert html["root"] == "/var/www/html"
    assert html["status"] == "EXCLUDED — UNUSED DEFAULT ROOT"
    assert html["excluded"] is True
    assert html["default_server"] is True
    assert any("default_server" in note or "unused default" in note.lower() for note in html.get("notes") or [])
    report = format_discovery_report({"applications": _apps(), "nginx_ok": True, "hostname": "ubuntu"})
    assert "EXCLUDED APPLICATIONS" in report
    assert "UNUSED DEFAULT ROOT" in report
    assert "DISCOVERED HOSTNAMES" in report
    assert "REQUIRES REVIEW" in report


def is_default_html_root(root: str) -> bool:
    return da.is_default_html_root(root)


def test_application_id_is_independent_of_hostname():
    sea = _by_host(_apps())["sateye.xdgen.com"]
    assert sea["application_id"] == "wordpress:/var/www/50sea.com"
    assert sea["application_id"].startswith("wordpress:")
    assert "sateye.xdgen.com" not in sea["application_id"]


def test_new_hostname_alias_requires_approval(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    save_snapshot(
        dest,
        {
            "applications": [
                {
                    "application_id": "wordpress:/var/www/50sea.com",
                    "hostname": "50sea.com",
                    "hostnames": ["50sea.com"],
                    "type": "WordPress",
                    "root": "/var/www/50sea.com",
                    "status": "READY",
                }
            ]
        },
    )
    set_approval(dest, "wordpress:/var/www/50sea.com", approved=True)
    current = [
        {
            "application_id": "wordpress:/var/www/50sea.com",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "sateye.xdgen.com"],
            "type": "WordPress",
            "root": "/var/www/50sea.com",
            "status": "READY",
        }
    ]
    rows = apply_policy(current, dest)
    assert rows[0]["status"] == "NEW HOSTNAME DETECTED — REQUIRES APPROVAL"
    assert rows[0]["included"] is False
    assert "sateye.xdgen.com" in " ".join(rows[0].get("notes") or [])


def test_approve_all_skips_unused_default_and_does_not_auto_approve_before_click(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    apps = _apps()
    pending = apply_policy(apps, dest)
    assert all(not row.get("included") for row in pending if row.get("change") != "removed")
    approved = approve_all_applications(dest, pending)
    assert approved
    assert all("html" not in ident for ident in approved)
    after = apply_policy(apps, dest)
    html = next(row for row in after if row.get("unused_default_root") or str(row.get("root") or "").endswith("/www/html"))
    assert html["included"] is False
    assert html["excluded"] is True
    live = [row for row in after if row.get("change") != "removed" and not row.get("excluded")]
    assert all(row.get("included") for row in live)
