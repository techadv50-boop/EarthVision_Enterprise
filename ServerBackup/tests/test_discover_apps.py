from __future__ import annotations

import json
import sys
from pathlib import Path

from app.discover.engine import discover_applications
from app.discover.gate import assess_backup_gate
from app.discover.policy import apply_policy, approve_all_applications, save_snapshot, set_approval
from app.discover.report import format_discovery_report
from app.engine.backup_engine import BackupEngine, BackupError
from app.master.store import MasterStore
from app.security.allowlist import is_allowed_remote_action
from tests.helpers import FakeSSH, UBUNTU_SCRIPTS, make_config, LocalMasterSSH, seed_remote_tree, master_config, enable_backup

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
    server_name 50sea.com www.50sea.com;
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
    assert "www.50sea.com" in names
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
    audit = (Path(__file__).resolve().parents[1] / "scripts" / "ubuntu" / "discover_audit.py").read_text(encoding="utf-8")
    assert "future-site.example.com" not in source
    assert "sateye.xdgen.com" not in source
    assert "sateye.xdgen.com" not in audit
    assert "xdgen_db" not in source
    assert "xdgen_db" not in audit


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
    assert set(sea["hostnames"]) == {"50sea.com", "www.50sea.com", "sateye.xdgen.com"}
    assert sea["database_name"] == "sea_tedb"
    assert sea["type"] == "WordPress"
    assert sum(1 for app in _apps() if app.get("root") == "/var/www/50sea.com") == 1


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
    assert "DISCOVERED APPLICATIONS" in report
    assert "HOSTNAME ALIASES" in report
    assert "EXCLUDED ROOTS" in report
    assert "REQUIRES REVIEW" in report
    assert "sateye.xdgen.com" in report


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


def _wp_probe(root: str):
    if root.rstrip("/") == "/var/www/50sea.com":
        return (
            {"index.php": True, "wp-config.php": True, "wp-includes": True},
            {"wp-config.php": "define('DB_NAME', 'sea_tedb');\n"},
        )
    if root.rstrip("/") == "/var/www/other":
        return (
            {"index.php": True, "wp-config.php": True, "wp-includes": True},
            {"wp-config.php": "define('DB_NAME', 'other_db');\n"},
        )
    return ({"index.html": True}, {})


def test_sateye_is_alias_of_50sea_wordpress_not_a_duplicate_backup():
    hosts = _by_host(_apps())
    sea = hosts["sateye.xdgen.com"]
    assert hosts["50sea.com"] is sea
    assert hosts["www.50sea.com"] is sea
    assert sea["application_id"] == "wordpress:/var/www/50sea.com"
    assert sea["database_name"] == "sea_tedb"
    assert "/var/www/50sea.com" in (sea.get("source_paths") or [sea.get("root")])
    report = format_discovery_report(
        {
            "applications": _apps(),
            "nginx_ok": True,
            "hostname": "ubuntu",
            "nginx_inventory": da.nginx_inventory(da.parse_nginx_t(NGINX_T)),
            "parsed_hostnames": da.parsed_hostnames(da.parse_nginx_t(NGINX_T)),
        }
    )
    assert "sateye.xdgen.com" in report
    assert "HOSTNAME ALIASES" in report
    assert report.split("HOSTNAME ALIASES", 1)[1].split("EXCLUDED ROOTS", 1)[0].count("sateye.xdgen.com") >= 1
    assert "wordpress:/var/www/50sea.com" in report


def test_normalization_does_not_drop_any_nginx_server_name():
    servers = da.parse_nginx_t(NGINX_T)
    apps = _apps()
    found = {name.lower() for app in apps for name in (app.get("hostnames") or [])}
    for name in da.parsed_hostnames(servers):
        assert name.lower() in found, f"{name} vanished during normalization"


def test_multiline_and_second_server_name_directive_keep_sateye():
    text = """
# configuration file /etc/nginx/sites-enabled/50sea.conf:
server {
    listen 443 ssl;
    server_name 50sea.com
                www.50sea.com;
    server_name sateye.xdgen.com;
    root /var/www/50sea.com;
}
"""
    servers = da.parse_nginx_t(text)
    names = {name for block in servers for name in block["server_name"]}
    assert names == {"50sea.com", "www.50sea.com", "sateye.xdgen.com"}
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    sea = _by_host(apps)["sateye.xdgen.com"]
    assert sea is _by_host(apps)["50sea.com"]
    assert set(sea["hostnames"]) == {"50sea.com", "www.50sea.com", "sateye.xdgen.com"}
    assert sea["type"] == "WordPress"
    assert sea["database_name"] == "sea_tedb"


def test_http_https_split_does_not_drop_sateye_alias():
    text = """
# configuration file /etc/nginx/sites-enabled/50sea.conf:
server {
    listen 80;
    server_name 50sea.com
                www.50sea.com
                sateye.xdgen.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name 50sea.com www.50sea.com;
    root /var/www/50sea.com;
}
"""
    servers = da.parse_nginx_t(text)
    assert "sateye.xdgen.com" in da.parsed_hostnames(servers)
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    found = {name.lower() for app in apps for name in (app.get("hostnames") or [])}
    assert "sateye.xdgen.com" in found
    sea = _by_host(apps)["sateye.xdgen.com"]
    assert sea["application_id"] == "wordpress:/var/www/50sea.com"
    assert set(sea["hostnames"]) == {"50sea.com", "www.50sea.com", "sateye.xdgen.com"}
    assert sum(1 for app in apps if app.get("root") == "/var/www/50sea.com") == 1


def test_redirect_only_hostname_becomes_alias_of_redirect_target():
    text = """
# configuration file /etc/nginx/sites-enabled/50sea.conf:
server {
    listen 443 ssl;
    server_name 50sea.com www.50sea.com;
    root /var/www/50sea.com;
}
# configuration file /etc/nginx/sites-enabled/sateye.conf:
server {
    listen 80;
    server_name sateye.xdgen.com;
    return 301 https://50sea.com$request_uri;
}
"""
    servers = da.parse_nginx_t(text)
    sateye_block = next(block for block in servers if "sateye.xdgen.com" in block["server_name"])
    assert sateye_block["root"] == ""
    assert sateye_block["redirect_to"] == "50sea.com"
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    sea = _by_host(apps)["sateye.xdgen.com"]
    assert sea is _by_host(apps)["50sea.com"]
    assert sea["database_name"] == "sea_tedb"
    assert sea["type"] == "WordPress"
    assert sum(1 for app in apps if "sateye.xdgen.com" in (app.get("hostnames") or [])) == 1


def test_redirect_to_unknown_host_is_not_merged_and_requires_review():
    text = """
server {
    listen 80;
    server_name orphan.example.com;
    return 301 https://missing.example.net$request_uri;
}
server {
    listen 80;
    server_name 50sea.com;
    root /var/www/50sea.com;
}
"""
    servers = da.parse_nginx_t(text)
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    orphan = _by_host(apps)["orphan.example.com"]
    sea = _by_host(apps)["50sea.com"]
    assert orphan is not sea
    assert "orphan.example.com" in (orphan.get("hostnames") or [])
    assert orphan["status"] == "REQUIRES REVIEW"


def test_duplicate_roots_different_hostnames_merge_when_type_and_database_match():
    servers = [
        {
            "server_name": ["50sea.com", "www.50sea.com"],
            "root": "/var/www/50sea.com",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/sites-enabled/50sea.conf",
            "listen": ["443 ssl"],
            "http": False,
            "https": True,
        },
        {
            "server_name": ["sateye.xdgen.com"],
            "root": "/var/www/50sea.com",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/sites-enabled/sateye.conf",
            "listen": ["80"],
            "http": True,
            "https": False,
        },
    ]
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    assert len([app for app in apps if app.get("root") == "/var/www/50sea.com"]) == 1
    sea = _by_host(apps)["sateye.xdgen.com"]
    assert set(sea["hostnames"]) == {"50sea.com", "www.50sea.com", "sateye.xdgen.com"}
    assert sea["database_name"] == "sea_tedb"


def test_sateye_stays_separate_when_root_and_database_differ():
    servers = [
        {
            "server_name": ["50sea.com"],
            "root": "/var/www/50sea.com",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/a",
            "listen": ["80"],
            "http": True,
            "https": False,
        },
        {
            "server_name": ["sateye.xdgen.com"],
            "root": "/var/www/other",
            "alias": [],
            "proxy_pass": [],
            "source_file": "/etc/nginx/b",
            "listen": ["80"],
            "http": True,
            "https": False,
        },
    ]
    apps = da.applications_from_servers(servers, probe=_wp_probe, path_exists=lambda _p: True)
    sea = _by_host(apps)["50sea.com"]
    sateye = _by_host(apps)["sateye.xdgen.com"]
    assert sea is not sateye
    assert sea["database_name"] == "sea_tedb"
    assert sateye["database_name"] == "other_db"
    assert "sateye.xdgen.com" not in (sea.get("hostnames") or [])
    assert "50sea.com" not in (sateye.get("hostnames") or [])


def test_nginx_filesystem_alias_is_not_a_separate_application():
    apps = _by_host(_apps())
    journal = apps["journal.50sea.com"]
    assert "/var/lib/ojs-journal50" in (journal.get("alias") or [])
    assert journal["ojs_files_dir"] == "/var/lib/ojs-journal50"
    assert all(app.get("root") != "/var/lib/ojs-journal50" for app in _apps())


def test_unassociated_database_is_visible_and_requires_review():
    import discover_audit as audit

    apps = [
        {
            "application_id": "wordpress:/var/www/50sea.com",
            "root": "/var/www/50sea.com",
            "database_name": "sea_tedb",
        },
        {
            "application_id": "php:/var/www/xdgen.com",
            "root": "/var/www/xdgen.com",
            "database_name": "",
        },
    ]
    inventory = audit.build_database_inventory(
        ["sea_tedb", "xdgen_db", "information_schema"],
        apps,
        details={
            "sea_tedb": {"table_count": 12, "size_bytes": 4096},
            "xdgen_db": {"table_count": 3, "size_bytes": 2048},
            "information_schema": {"table_count": 1, "size_bytes": 0},
        },
    )
    by_name = {row["name"]: row for row in inventory}
    assert by_name["sea_tedb"]["status"] == "ASSOCIATED WITH APPLICATION"
    assert by_name["xdgen_db"]["status"] == "UNASSOCIATED DATABASE — REQUIRES REVIEW"
    assert by_name["xdgen_db"]["application_id"] == ""
    assert by_name["information_schema"]["status"] == "SYSTEM DATABASE — EXCLUDED"
    report = format_discovery_report(
        {
            "applications": [
                {
                    "application_id": "wordpress:/var/www/50sea.com",
                    "hostname": "50sea.com",
                    "hostnames": ["50sea.com", "www.50sea.com"],
                    "type": "WordPress",
                    "root": "/var/www/50sea.com",
                    "database_type": "MariaDB",
                    "database_name": "sea_tedb",
                    "status": "NEW SITE DETECTED — REQUIRES APPROVAL",
                }
            ],
            "database_inventory": inventory,
            "databases": {"mariadb": ["sea_tedb", "xdgen_db"], "postgresql": []},
            "nginx_ok": True,
            "hostname": "ubuntu",
        }
    )
    unassociated = report.split("UNASSOCIATED DATABASES", 1)[1].split("EXCLUDED DATABASES", 1)[0]
    assert "xdgen_db" in unassociated
    assert "REQUIRES REVIEW" in unassociated
    assert "no application association discovered" in unassociated
    assert "database xdgen_db" in report.split("REQUIRES REVIEW", 1)[1]
    gate = assess_backup_gate(
        [
            {
                "application_id": "wordpress:/var/www/50sea.com",
                "included": True,
                "status": "READY",
            }
        ],
        inventory,
    )
    assert gate["databases_unresolved"] == 1
    assert gate["unresolved_database_names"] == ["xdgen_db"]
    assert gate["block_complete_backup"] is True


def test_empty_database_is_excluded_but_still_listed():
    import discover_audit as audit

    inventory = audit.build_database_inventory(
        ["empty_db"],
        [{"application_id": "php:/var/www/xdgen.com", "root": "/var/www/xdgen.com"}],
        details={"empty_db": {"table_count": 0, "size_bytes": 0}},
    )
    assert inventory[0]["status"] == "UNUSED/EMPTY DATABASE — EXCLUDED"
    report = format_discovery_report(
        {
            "applications": [],
            "database_inventory": inventory,
            "databases": {"mariadb": ["empty_db"]},
            "nginx_ok": True,
            "hostname": "ubuntu",
        }
    )
    discovered = report.split("DISCOVERED DATABASES", 1)[1].split("UNASSOCIATED DATABASES", 1)[0]
    assert "empty_db" in discovered
    assert "UNUSED/EMPTY DATABASE — EXCLUDED" in discovered
    unassociated = report.split("UNASSOCIATED DATABASES", 1)[1].split("EXCLUDED DATABASES", 1)[0]
    assert "empty_db" not in unassociated
    gate = assess_backup_gate([], inventory)
    assert gate["databases_discovered"] == 1
    assert gate["databases_unresolved"] == 0
    assert gate["block_complete_backup"] is False


def test_config_reference_associates_unassociated_database():
    import discover_audit as audit

    apps = [
        {
            "application_id": "php:/var/www/xdgen.com",
            "root": "/var/www/xdgen.com",
            "database_name": "",
        }
    ]
    references = {
        "xdgen_db": [{"path": "/var/www/xdgen.com/.env", "kind": ".env"}],
    }
    inventory = audit.build_database_inventory(
        ["xdgen_db"],
        apps,
        details={"xdgen_db": {"table_count": 4, "size_bytes": 1024}},
        references=references,
    )
    assert inventory[0]["status"] == "ASSOCIATED WITH APPLICATION"
    assert inventory[0]["application_id"] == "php:/var/www/xdgen.com"


def test_env_file_on_disk_associates_database(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    Path(remote["xdgen.com"], ".env").write_text("DB_NAME=xdgen_db\n", encoding="utf-8")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote", extra_mariadb=["xdgen_db"])
    result = discover_applications(cfg, ssh=ssh, persist=True)
    by_name = {row["name"]: row for row in result.get("database_inventory") or []}
    assert by_name["xdgen_db"]["status"] == "ASSOCIATED WITH APPLICATION"
    assert "xdgen.com" in by_name["xdgen_db"]["application_id"]
    xdgen = next(app for app in result["applications"] if app.get("root") == remote["xdgen.com"])
    assert xdgen.get("database_name") == "xdgen_db"
    gate = result.get("backup_gate") or {}
    assert "xdgen_db" not in (gate.get("unresolved_database_names") or [])


def test_inactive_hostname_in_sites_available_is_not_an_application(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    leftover = (
        "server {\n"
        "    listen 80;\n"
        "    server_name sateye.xdgen.com;\n"
        f"    root {remote['50sea.com']};\n"
        "}\n"
    )
    ssh = LocalMasterSSH(
        tmp_path / "remote",
        extra_scan_files={"/etc/nginx/sites-available/sateye.conf": leftover},
    )
    result = discover_applications(cfg, ssh=ssh, persist=True)
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "sateye.xdgen.com" not in hosts
    inactive = {row["hostname"]: row for row in result.get("inactive_hostnames") or []}
    assert "sateye.xdgen.com" in inactive
    assert inactive["sateye.xdgen.com"]["verdict"] == "NOT ACTIVE IN CURRENT SERVER CONFIGURATION"
    assert any("sites-available" in str(item.get("source") or "") for item in inactive["sateye.xdgen.com"]["evidence"])
    report = result["report_text"]
    not_active = report.split("NOT ACTIVE IN CURRENT SERVER CONFIGURATION", 1)[1].split("OJS FILES_DIR", 1)[0]
    assert "sateye.xdgen.com" in not_active
    discovered_hosts = report.split("DISCOVERED HOSTNAMES", 1)[1].split("DISCOVERED APPLICATIONS", 1)[0]
    assert "sateye.xdgen.com" not in discovered_hosts


def test_inactive_hostname_from_previous_snapshot_is_not_added(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    save_snapshot(
        cfg.backup_destination,
        {
            "applications": [
                {
                    "application_id": "wordpress:/var/www/50sea.com",
                    "hostname": "50sea.com",
                    "hostnames": ["50sea.com", "www.50sea.com", "sateye.xdgen.com"],
                    "type": "WordPress",
                    "root": remote["50sea.com"],
                }
            ]
        },
    )
    result = discover_applications(cfg, ssh=LocalMasterSSH(tmp_path / "remote"), persist=True)
    hosts = {name for app in result["applications"] if app.get("change") != "removed" for name in (app.get("hostnames") or [])}
    assert "sateye.xdgen.com" not in hosts
    inactive = {row["hostname"] for row in result.get("inactive_hostnames") or []}
    assert "sateye.xdgen.com" in inactive
    report = result["report_text"]
    assert "NOT ACTIVE IN CURRENT SERVER CONFIGURATION" in report
    assert "sateye.xdgen.com" in report.split("NOT ACTIVE IN CURRENT SERVER CONFIGURATION", 1)[1]


def test_active_nginx_hostname_is_still_an_alias_when_present():
    hosts = _by_host(_apps())
    assert hosts["sateye.xdgen.com"] is hosts["50sea.com"]


def test_future_nginx_site_requires_approval_without_default_json(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    newsite = Path(tmp_path / "remote" / "var/www/newsite.example.com")
    newsite.mkdir(parents=True, exist_ok=True)
    (newsite / "index.html").write_text("new\n", encoding="utf-8")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(
        tmp_path / "remote",
        extra_nginx_sites=[("newsite.example.com", newsite.as_posix())],
    )
    result = discover_applications(cfg, ssh=ssh, persist=True)
    found = next(app for app in result["applications"] if "newsite.example.com" in (app.get("hostnames") or []))
    assert "NEW SITE DETECTED — REQUIRES APPROVAL" in str(found.get("status") or "")
    assert found.get("included") is False
    default_json = (Path(__file__).resolve().parents[1] / "config" / "default.json").read_text(encoding="utf-8")
    assert "newsite.example.com" not in default_json
    assert "NEW SITE DETECTED — REQUIRES APPROVAL" in result["report_text"]
    assert "NEW APPLICATIONS" in result["report_text"]


def test_backup_now_blocked_when_applications_pending(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    try:
        BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
        assert False, "pending applications must block BACKUP NOW"
    except BackupError as exc:
        text = str(exc)
        assert "BLOCK COMPLETE BACKUP" in text
        assert "Applications pending:" in text
    assert not MasterStore(cfg.backup_destination).has_head()


def test_backup_now_blocked_when_unassociated_database_after_approval(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote", extra_mariadb=["xdgen_db"])
    enable_backup(cfg, ssh)
    try:
        BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote", extra_mariadb=["xdgen_db"])).run()
        assert False, "unassociated database must block COMPLETE backup"
    except BackupError as exc:
        text = str(exc)
        assert "BLOCK COMPLETE BACKUP" in text
        assert "xdgen_db" in text
        assert "Databases unresolved:" in text
    assert not MasterStore(cfg.backup_destination).has_head()


def test_empty_unassociated_database_does_not_block_backup_after_approval(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(
        tmp_path / "remote",
        extra_mariadb=["empty_db"],
        extra_mariadb_details={"empty_db": {"table_count": 0, "size_bytes": 0}},
    )
    enable_backup(cfg, ssh)
    info = BackupEngine(
        cfg,
        ssh=LocalMasterSSH(
            tmp_path / "remote",
            extra_mariadb=["empty_db"],
            extra_mariadb_details={"empty_db": {"table_count": 0, "size_bytes": 0}},
        ),
    ).run()
    assert info["status"] == "SUCCESS"


def test_zero_row_unreferenced_database_is_unused_legacy():
    import discover_audit as audit

    inventory = audit.build_database_inventory(
        ["legacy_db"],
        [{"application_id": "php:/var/www/xdgen.com", "root": "/var/www/xdgen.com"}],
        details={
            "legacy_db": {
                "table_count": 2,
                "size_bytes": 16384,
                "row_count": 0,
                "tables": [{"name": "old_sessions", "rows": 0}, {"name": "tmp", "rows": 0}],
            }
        },
    )
    assert inventory[0]["status"] == "EXCLUDED — UNUSED/LEGACY"
    assert "leftover schema" in inventory[0]["reason"]
    report = format_discovery_report(
        {
            "applications": [],
            "database_inventory": inventory,
            "databases": {"mariadb": ["legacy_db"]},
            "nginx_ok": True,
            "hostname": "ubuntu",
        }
    )
    assert "EXCLUDED DATABASES" in report
    assert "legacy_db" in report.split("EXCLUDED DATABASES", 1)[1]
    assert "EXCLUDED — UNUSED/LEGACY" in report
    gate = assess_backup_gate([], inventory)
    assert gate["databases_unresolved"] == 0
    assert gate["block_complete_backup"] is False


def test_unreferenced_database_with_rows_stays_requires_review():
    import discover_audit as audit

    inventory = audit.build_database_inventory(
        ["legacy_db"],
        [{"application_id": "php:/var/www/xdgen.com", "root": "/var/www/xdgen.com"}],
        details={
            "legacy_db": {
                "table_count": 3,
                "size_bytes": 1_000_000,
                "row_count": 120,
                "tables": [
                    {"name": "wp_posts", "rows": 80},
                    {"name": "wp_users", "rows": 40},
                ],
                "identifying_hints": ["wp_posts", "wp_users"],
            }
        },
    )
    assert inventory[0]["status"] == "UNASSOCIATED DATABASE — REQUIRES REVIEW"
    assert "120 rows" in inventory[0]["reason"]
    assert "wp_posts" in inventory[0]["reason"]
    gate = assess_backup_gate(
        [{"application_id": "php:/var/www/xdgen.com", "included": True, "status": "READY"}],
        inventory,
    )
    assert gate["databases_unresolved"] == 1
    assert gate["block_complete_backup"] is True


def test_mysql_account_report_omits_password(tmp_path: Path):
    import discover_audit as audit

    cnf = tmp_path / "my.cnf"
    cnf.write_text("[client]\nuser=root\npassword=supersecret\n", encoding="utf-8")
    info = audit.configured_mysql_user(str(cnf))
    assert info["configured_user"] == "root"
    assert "supersecret" not in str(info)

    class _Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def run(cmd, timeout=15):
        joined = " ".join(cmd)
        if "CURRENT_USER" in joined:
            return _Result("root@localhost\troot@localhost\n")
        if "SHOW GRANTS" in joined:
            return _Result("GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost` IDENTIFIED BY 'supersecret'\n")
        return _Result("")

    account = audit.mariadb_account_info(run, lambda: [], cnf_path=str(cnf))
    blob = str(account)
    assert account["using_root"] is True
    assert account["configured_user"] == "root"
    assert account["current_user"] == "root@localhost"
    assert "supersecret" not in blob
    assert "***" in blob or "IDENTIFIED BY" not in blob
    report = format_discovery_report(
        {
            "applications": [],
            "database_inventory": [],
            "database_account": account,
            "nginx_ok": True,
            "hostname": "ubuntu",
        }
    )
    assert "DATABASE ACCOUNT" in report
    assert "using root: yes" in report
    assert "supersecret" not in report
    assert "least-privilege" in report.lower() or "least-privilege later" in report


def test_php_file_reference_associates_database(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    Path(remote["xdgen.com"], "config.php").write_text("<?php $dbname = 'xdgen_db';\n", encoding="utf-8")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote", extra_mariadb=["xdgen_db"])
    result = discover_applications(cfg, ssh=ssh, persist=True)
    by_name = {row["name"]: row for row in result.get("database_inventory") or []}
    assert by_name["xdgen_db"]["status"] == "ASSOCIATED WITH APPLICATION"
    assert "xdgen.com" in by_name["xdgen_db"]["application_id"]


def test_legacy_zero_row_database_does_not_block_backup(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    details = {
        "legacy_db": {
            "table_count": 1,
            "size_bytes": 16,
            "row_count": 0,
            "tables": [{"name": "old", "rows": 0}],
        }
    }
    ssh = LocalMasterSSH(tmp_path / "remote", extra_mariadb=["legacy_db"], extra_mariadb_details=details)
    enable_backup(cfg, ssh)
    info = BackupEngine(
        cfg,
        ssh=LocalMasterSSH(tmp_path / "remote", extra_mariadb=["legacy_db"], extra_mariadb_details=details),
    ).run()
    assert info["status"] == "SUCCESS"


def test_inspect_database_contents_is_read_only_counts():
    import discover_audit as audit

    calls: list[str] = []

    class _Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def run(cmd, timeout=15):
        joined = " ".join(cmd)
        calls.append(joined)
        if "information_schema.tables" in joined:
            return _Result("users\tInnoDB\t5\t4096\t\n")
        if "COUNT(*)" in joined:
            return _Result("5\n")
        if "information_schema.columns" in joined:
            return _Result("users\tid\nusers\temail\n")
        return _Result("")

    inspected = audit.inspect_database_contents(run, lambda: [], "app_db")
    assert inspected["row_count"] == 5
    assert inspected["tables"][0]["name"] == "users"
    assert any("COUNT(*)" in item for item in calls)
    assert not any("SELECT *" in item.upper().replace(" ", "") and "COUNT" not in item.upper() for item in calls)
    assert not any("DELETE" in item.upper() or "DROP" in item.upper() or "UPDATE" in item.upper() for item in calls)

