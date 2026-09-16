"""Server-wide discovery must not be limited to nginx -T or a fixed hostname list."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.discover.engine import discover_applications
from app.discover.report import format_discovery_report
from tests.helpers import UBUNTU_SCRIPTS, LocalMasterSSH, master_config, seed_remote_tree

if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))
import discover_apps as da  # noqa: E402


def _traefik_container(
    *,
    name: str,
    hostname: str,
    project: str,
    workdir: str = "",
    env: list[str] | None = None,
    mounts: list[dict] | None = None,
    running: bool = True,
    extra_labels: dict[str, str] | None = None,
) -> dict:
    labels = {
        "com.docker.compose.project": project,
        "com.docker.compose.service": "web",
        "com.docker.compose.project.working_dir": workdir,
        "com.docker.compose.project.config_files": f"{workdir}/docker-compose.yml" if workdir else "",
        f"traefik.http.routers.{project}.rule": f"Host(`{hostname}`)",
        f"traefik.http.routers.{project}.tls": "true",
    }
    labels.update(extra_labels or {})
    return {
        "Id": name * 2,
        "Name": f"/{name}",
        "State": {"Running": running},
        "Config": {
            "Image": f"{project}:latest",
            "Labels": labels,
            "Env": list(env or []),
        },
        "HostConfig": {"PortBindings": {}},
        "Mounts": list(mounts or []),
    }


def test_traefik_host_label_discovers_website_without_nginx():
    servers = da.parse_nginx_t(
        """
# configuration file /etc/nginx/nginx.conf:
http {
# configuration file /etc/nginx/sites-enabled/only.conf:
server {
    listen 80;
    server_name already.example.com;
    root /var/www/already;
}
}
"""
    )
    docker = [
        _traefik_container(
            name="sateye_web",
            hostname="sateye.example.com",
            project="sateye",
            workdir="/opt/sateye",
            env=["MYSQL_DATABASE=sateye_db"],
            mounts=[{"Type": "bind", "Source": "/opt/sateye/app", "Destination": "/app"}],
        )
    ]
    apps = da.applications_from_servers(servers, docker_containers=docker, path_exists=lambda _p: True)
    extras, leftovers = da.applications_from_unmatched_docker(apps, docker, path_exists=lambda _p: True)
    assert leftovers == []
    hosts = {name for app in extras for name in (app.get("hostnames") or [])}
    assert "sateye.example.com" in hosts
    assert extras[0]["discovery_source"] == "docker labels"
    assert extras[0]["classification"] == da.CLASSIFICATION_ACTIVE
    assert extras[0]["docker"]["compose_project"] == "sateye"
    assert extras[0]["database_name"] == "sateye_db"
    source = Path(__file__).resolve().parents[1].joinpath("scripts/ubuntu/discover_apps.py").read_text(encoding="utf-8")
    assert "sateye.xdgen.com" not in source
    assert "satpass.xdgen.com" not in source
    assert "citation.xdgen.com" not in source


def test_virtual_host_env_discovers_website_without_nginx():
    docker = [
        {
            "Id": "satpass1",
            "Name": "/satpass_web",
            "State": {"Running": True},
            "Config": {
                "Image": "satpass:latest",
                "Labels": {
                    "com.docker.compose.project": "satpass",
                    "com.docker.compose.service": "web",
                    "com.docker.compose.project.working_dir": "/opt/satpass",
                },
                "Env": ["VIRTUAL_HOST=satpass.example.com"],
            },
            "HostConfig": {"PortBindings": {}},
            "Mounts": [],
        }
    ]
    extras, _leftovers = da.applications_from_unmatched_docker([], docker, path_exists=lambda _p: True)
    assert extras[0]["hostnames"] == ["satpass.example.com"]
    assert extras[0]["type"] == "Docker"


def test_stopped_docker_hostname_is_legacy_not_application():
    docker = [
        _traefik_container(
            name="old_web",
            hostname="legacy.example.com",
            project="legacyapp",
            running=False,
        )
    ]
    extras, leftovers = da.applications_from_unmatched_docker([], docker, path_exists=lambda _p: True)
    assert extras == []
    assert leftovers[0]["hostname"] == "legacy.example.com"
    assert leftovers[0]["classification"] == da.CLASSIFICATION_LEGACY
    assert "not running" in leftovers[0]["evidence"][0]["detail"]


def test_named_app_volume_is_copy_data_and_postgres_volume_is_sql_dump():
    docker = [
        {
            "Id": "web1",
            "Name": "/uploads_web",
            "State": {"Running": True},
            "Config": {
                "Image": "app:latest",
                "Labels": {
                    "com.docker.compose.project": "uploadsapp",
                    "com.docker.compose.service": "web",
                    "traefik.http.routers.uploadsapp.rule": "Host(`uploads.example.com`)",
                },
                "Env": ["POSTGRES_DB=uploads_db"],
            },
            "HostConfig": {"PortBindings": {}},
            "Mounts": [
                {"Type": "volume", "Name": "uploads_files", "Destination": "/var/www/html/uploads"},
                {"Type": "volume", "Name": "uploads_pgdata", "Destination": "/var/lib/postgresql/data"},
            ],
        }
    ]
    extras, _leftovers = da.applications_from_unmatched_docker([], docker, path_exists=lambda _p: True)
    persist = extras[0]["persistent_data_paths"]
    assert "volume:uploads_files" in persist
    assert "/var/lib/docker/volumes/uploads_files/_data" in persist
    assert "/var/lib/docker/volumes/uploads_files/_data" in extras[0]["source_paths"]
    assert "volume:uploads_pgdata" in persist
    assert "/var/lib/docker/volumes/uploads_pgdata/_data" not in extras[0]["source_paths"]
    volumes = da.inventory_docker_volumes(docker, extras)
    by_name = {row["name"]: row for row in volumes}
    assert by_name["uploads_files"]["backup_status"] == "COPY_DATA"
    assert by_name["uploads_pgdata"]["backup_status"] == "SQL_DUMP"
    assert by_name["uploads_files"]["website"] == "uploads.example.com"


def test_ssl_certificate_paths_are_parsed_from_nginx():
    servers = da.parse_nginx_t(
        """
# configuration file /etc/nginx/sites-enabled/secure.conf:
server {
    listen 443 ssl;
    server_name secure.example.com;
    root /var/www/secure;
    ssl_certificate /etc/letsencrypt/live/secure.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/secure.example.com/privkey.pem;
}
"""
    )
    assert servers[0]["ssl_certificate"] == ["/etc/letsencrypt/live/secure.example.com/fullchain.pem"]
    assert servers[0]["ssl_mechanism"] == "letsencrypt"
    apps = da.applications_from_servers(servers, path_exists=lambda _p: True)
    ssl = apps[0]["ssl"]
    assert ssl["mechanism"] == "letsencrypt"
    assert "/etc/letsencrypt/live/secure.example.com/fullchain.pem" in apps[0]["configuration_paths"]


def test_apache_vhost_is_discovered_when_missing_from_nginx():
    apache = da.parse_apache_vhosts(
        """
<VirtualHost *:80>
    ServerName extra.example.com
    DocumentRoot /var/www/extra
</VirtualHost>
""",
        "/etc/apache2/sites-enabled/extra.conf",
    )
    extras = da.applications_from_apache_servers(apache, [], path_exists=lambda _p: True)
    assert extras[0]["hostnames"] == ["extra.example.com"]
    assert extras[0]["discovery_source"] == "apache"
    assert extras[0]["root"] == "/var/www/extra"


def test_assemble_discovers_docker_only_and_classifies_sites_available_leftover(tmp_path: Path):
    servers = da.parse_nginx_t(
        """
# configuration file /etc/nginx/sites-enabled/main.conf:
server {
    listen 80;
    server_name main.example.com;
    root /tmp/main;
}
"""
    )
    docker = [
        _traefik_container(
            name="citation_app",
            hostname="citation.example.com",
            project="citationapp",
            workdir="/opt/citationapp",
            env=["POSTGRES_DB=citation"],
        )
    ]
    leftover = "server {\n    listen 80;\n    server_name leftover.example.com;\n    root /old/path;\n}\n"
    result = da.assemble_discovery(
        servers=servers,
        docker_containers=docker,
        extra_scan_files={"/etc/nginx/sites-available/leftover.conf": leftover},
        nginx_ok=True,
        hostname="ubuntu-test",
        path_exists=lambda _p: True,
    )
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "main.example.com" in hosts
    assert "citation.example.com" in hosts
    assert "leftover.example.com" not in hosts
    inactive = {row["hostname"]: row for row in result["inactive_hostnames"]}
    assert "leftover.example.com" in inactive
    assert inactive["leftover.example.com"]["verdict"] == "NOT ACTIVE IN CURRENT SERVER CONFIGURATION"
    classified = {row["hostname"]: row for row in result["classified"] if row.get("kind") == "hostname"}
    assert classified["citation.example.com"]["classification"] == da.CLASSIFICATION_ACTIVE
    assert classified["leftover.example.com"]["classification"] == da.CLASSIFICATION_LEGACY
    report = format_discovery_report(result)
    assert "SERVER-WIDE DISCOVERY REPORT" in report
    assert "TOTAL HOSTNAMES DISCOVERED" in report
    assert "citation.example.com" in report
    assert "leftover.example.com" in report
    assert "WHY NGINX-ONLY AND LABEL-ONLY DISCOVERY MISSED WEBSITES" in report


def test_dry_run_discovers_traefik_sites_and_keeps_sites_available_out_of_applications(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    sateye = tmp_path / "remote/opt/sateye"
    sateye.mkdir(parents=True, exist_ok=True)
    leftover = (
        "server {\n"
        "    listen 80;\n"
        "    server_name leftover-only.example.com;\n"
        f"    root {remote['50sea.com']};\n"
        "}\n"
    )
    ssh = LocalMasterSSH(
        tmp_path / "remote",
        extra_scan_files={
            "/etc/nginx/sites-available/leftover.conf": leftover,
            "/etc/dokploy/traefik/dynamic/orbital.yml": _dokploy_traefik_yaml("orbital.example.com", "orbital"),
        },
        extra_docker_containers=[
            _traefik_container(
                name="sateye_web",
                hostname="sateye.xdgen.com",
                project="sateye",
                workdir=sateye.as_posix(),
                env=["MYSQL_DATABASE=sateye_db"],
            ),
            _traefik_container(
                name="satpass_web",
                hostname="satpass.xdgen.com",
                project="satpass",
                workdir="/opt/satpass",
                env=["MYSQL_DATABASE=satpass_db"],
            ),
            _unlabeled_web_container(name="orbital-web-1", project="orbital", env=["POSTGRES_DB=orbital_db"]),
        ],
    )
    result = discover_applications(cfg, ssh=ssh, persist=True)
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "sateye.xdgen.com" in hosts
    assert "satpass.xdgen.com" in hosts
    assert "citation.xdgen.com" in hosts
    assert "orbital.example.com" in hosts
    assert "leftover-only.example.com" not in hosts
    report = result["report_text"]
    assert "SERVER-WIDE DISCOVERY REPORT" in report
    assert "sateye.xdgen.com" in report.split("SERVER-WIDE DISCOVERY REPORT", 1)[1]
    assert "satpass.xdgen.com" in report
    assert "orbital.example.com" in report
    discovered_hosts = report.split("DISCOVERED HOSTNAMES", 1)[1].split("DISCOVERED APPLICATIONS", 1)[0]
    assert "sateye.xdgen.com" in discovered_hosts
    assert "orbital.example.com" in discovered_hosts
    assert "leftover-only.example.com" not in discovered_hosts
    not_active = report.split("NOT ACTIVE IN CURRENT SERVER CONFIGURATION", 1)[1].split("OJS FILES_DIR", 1)[0]
    assert "leftover-only.example.com" in not_active
    totals = result.get("discovery_totals") or {}
    assert totals.get("unique_websites", 0) >= 6


def test_volume_inventory_tolerates_unreadable_docker_paths(monkeypatch):
    docker = [
        {
            "Id": "web1",
            "Name": "/uploads_web",
            "State": {"Running": True},
            "Config": {
                "Image": "app:latest",
                "Labels": {
                    "com.docker.compose.project": "uploadsapp",
                    "traefik.http.routers.uploadsapp.rule": "Host(`uploads.example.com`)",
                },
                "Env": [],
            },
            "HostConfig": {"PortBindings": {}},
            "Mounts": [{"Type": "volume", "Name": "uploads_files", "Destination": "/var/www/html/uploads"}],
        }
    ]
    extras, _leftovers = da.applications_from_unmatched_docker([], docker, path_exists=lambda _p: True)

    def boom(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_dir", boom)
    volumes = da.inventory_docker_volumes(docker, extras)
    assert volumes[0]["name"] == "uploads_files"
    assert volumes[0]["backup_status"] == "COPY_DATA"
    assert volumes[0]["size_bytes"] == 0
    names = da.hostnames_from_traefik_rule("Host(`a.example.com`) || Host(`www.a.example.com`)")
    assert names == ["a.example.com", "www.a.example.com"]
    assert da.looks_like_hostname("citation_web") is False
    assert da.looks_like_hostname("sateye.xdgen.com") is True


def _unlabeled_web_container(*, name: str, project: str, env: list[str] | None = None, mounts: list[dict] | None = None) -> dict:
    return {
        "Id": name * 2,
        "Name": f"/{name}",
        "State": {"Running": True},
        "Config": {
            "Image": f"{project}:latest",
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": "web",
                "com.docker.compose.project.working_dir": f"/etc/dokploy/applications/{project}",
            },
            "Env": list(env or []),
        },
        "NetworkSettings": {"Networks": {"dokploy-network": {"Aliases": [project, f"{project}-web"]}}},
        "HostConfig": {"PortBindings": {}},
        "Mounts": list(mounts or [{"Type": "bind", "Source": f"/opt/{project}/app", "Destination": "/app"}]),
    }


def _dokploy_traefik_yaml(hostname: str, backend: str, port: int = 3000) -> str:
    return (
        "http:\n"
        "  routers:\n"
        f"    {backend}-websecure:\n"
        f"      rule: Host(`{hostname}`)\n"
        f"      service: {backend}-web\n"
        "      tls:\n"
        "        certResolver: letsencrypt\n"
        "  services:\n"
        f"    {backend}-web:\n"
        "      loadBalancer:\n"
        "        servers:\n"
        f"          - url: http://{backend}:{port}\n"
    )


def test_dokploy_traefik_yaml_without_labels_becomes_application():
    docker = [
        _unlabeled_web_container(name="orbital-web-1", project="orbital", env=["POSTGRES_DB=orbital_db"]),
    ]
    result = da.assemble_discovery(
        servers=da.parse_nginx_t(
            """
# configuration file /etc/nginx/sites-enabled/only.conf:
server {
    listen 80;
    server_name already.example.com;
    root /var/www/already;
}
"""
        ),
        docker_containers=docker,
        extra_scan_files={
            "/etc/dokploy/traefik/dynamic/orbital.yml": _dokploy_traefik_yaml("orbital.example.com", "orbital"),
        },
        nginx_ok=True,
        hostname="ubuntu-test",
        path_exists=lambda _p: True,
    )
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "orbital.example.com" in hosts
    assert "already.example.com" in hosts
    app = next(item for item in result["applications"] if "orbital.example.com" in (item.get("hostnames") or []))
    assert app["discovery_source"] == "traefik dynamic" or "traefik dynamic" in str(app.get("discovery_sources") or [])
    assert app["classification"] == da.CLASSIFICATION_ACTIVE
    assert app["database_name"] == "orbital_db"
    assert app["https"] is True
    inactive = {row["hostname"] for row in result["inactive_hostnames"]}
    assert "orbital.example.com" not in inactive
    report = format_discovery_report(result)
    discovered = report.split("DISCOVERED HOSTNAMES", 1)[1].split("DISCOVERED APPLICATIONS", 1)[0]
    assert "orbital.example.com" in discovered
    source = Path(__file__).resolve().parents[1].joinpath("scripts/ubuntu/discover_apps.py").read_text(encoding="utf-8")
    assert "sateye.xdgen.com" not in source
    assert "satpass.xdgen.com" not in source
    assert "citation.xdgen.com" not in source


def test_new_traefik_host_is_discovered_without_known_list():
    docker = [_unlabeled_web_container(name="newsite-web-1", project="newsite")]
    result = da.assemble_discovery(
        servers=[],
        docker_containers=docker,
        extra_scan_files={
            "/etc/dokploy/traefik/dynamic/newsite.yml": _dokploy_traefik_yaml("newsite.example.com", "newsite"),
        },
        nginx_ok=True,
        path_exists=lambda _p: True,
    )
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "newsite.example.com" in hosts
    assert result["applications"][0]["classification"] == da.CLASSIFICATION_ACTIVE


def test_live_traefik_route_without_container_is_still_an_application():
    result = da.assemble_discovery(
        servers=[],
        docker_containers=[],
        extra_scan_files={
            "/etc/dokploy/traefik/dynamic/orphan.yml": _dokploy_traefik_yaml("orphan.example.com", "orphan"),
        },
        nginx_ok=True,
        path_exists=lambda _p: True,
    )
    hosts = {name for app in result["applications"] for name in (app.get("hostnames") or [])}
    assert "orphan.example.com" in hosts
    app = result["applications"][0]
    assert app["status"] == "REQUIRES REVIEW"
    assert app["database_status"] == "UNRESOLVED"


def test_acme_json_attaches_ssl_to_traefik_application():
    acme = json.dumps(
        {
            "letsencrypt": {
                "Certificates": [
                    {"domain": {"main": "orbital.example.com", "sans": ["www.orbital.example.com"]}}
                ]
            }
        }
    )
    result = da.assemble_discovery(
        servers=[],
        docker_containers=[_unlabeled_web_container(name="orbital-web-1", project="orbital")],
        extra_scan_files={
            "/etc/dokploy/traefik/dynamic/orbital.yml": _dokploy_traefik_yaml("orbital.example.com", "orbital"),
            "/etc/dokploy/traefik/acme.json": acme,
        },
        nginx_ok=True,
        path_exists=lambda _p: True,
    )
    app = result["applications"][0]
    assert app["ssl"]["mechanism"] in {"traefik-acme", "traefik"}
    assert app["ssl"].get("acme_file") == "/etc/dokploy/traefik/acme.json"


def test_parse_show_table_status_sums_data_and_index():
    from docker_db import parse_show_table_status

    stdout = "posts\tInnoDB\t10\tDynamic\t12\t100\t4096\t0\t2048\t0\n"
    parsed = parse_show_table_status(stdout)
    assert parsed["table_count"] == 1
    assert parsed["size_bytes"] == 6144
    assert parsed["row_count"] == 12


def test_docker_schema_probe_fills_zero_byte_docker_database():
    from docker_db import docker_mysql_argv

    called: list[list[str]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "wp_posts\tInnoDB\t10\tDynamic\t5\t100\t8000\t0\t2000\t0\n"
            self.stderr = ""

    def fake_run(cmd, timeout=30):
        called.append(list(cmd))
        return Result()

    apps = [
        {
            "application_id": "docker:sea50",
            "database_name": "sea50_db",
            "database_type": "MariaDB",
            "docker": {"compose_project": "sea50", "mysql_database": "sea50_db", "db_container": "sea50-db-1"},
        }
    ]
    inventory = da.attach_docker_only_databases(apps, [], [])
    assert inventory[0]["size_bytes"] is None
    da._probe_docker_schema_sizes(inventory, run=fake_run, details_override=None, errors=[])
    assert inventory[0]["size_bytes"] == 10000
    assert inventory[0]["table_count"] == 1
    assert inventory[0]["dump_capable"] is True
    assert docker_mysql_argv("sea50-db-1", "sea50_db", "SHOW TABLE STATUS") == called[0]

