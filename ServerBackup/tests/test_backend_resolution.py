from __future__ import annotations

import sys

from tests.helpers import UBUNTU_SCRIPTS

if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))
import discover_apps as da  # noqa: E402

from app.backup.preflight import build_preflight, format_attribution_report  # noqa: E402


class _Result:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


WEB_CONTAINER_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f900112233445566778899aabbccddeeff0"


def _fake_run(mapping):
    def run(cmd, timeout=10):
        joined = " ".join(cmd)
        for key, value in mapping.items():
            if key in joined:
                return _Result(value)
        return _Result("", returncode=1)

    return run


def test_resolve_backend_owners_parses_ss_and_proc():
    ss_output = (
        "LISTEN 0 511 127.0.0.1:8084 0.0.0.0:* users:((\"php-fpm\",pid=1234,fd=8))\n"
        "LISTEN 0 128 [::]:8085 [::]:* users:((\"docker-proxy\",pid=999,fd=4))\n"
        "LISTEN 0 4096 0.0.0.0:80 0.0.0.0:* users:((\"nginx\",pid=42,fd=6))\n"
    )
    run = _fake_run(
        {
            "ss -ltnpH": ss_output,
            "/proc/1234/cgroup": f"0::/system.slice/docker-{WEB_CONTAINER_ID}.scope\n",
            "/proc/1234/cwd": "/var/www/50sea.com\n",
            "/proc/1234/exe": "/usr/sbin/php-fpm8.2\n",
            "-p 1234": "php8.2-fpm.service\n",
            "/proc/999/cgroup": "0::/system.slice/docker.service\n",
            "/proc/999/cwd": "/\n",
            "-p 999": "docker.service\n",
        }
    )
    owners = da.resolve_backend_owners(run)
    assert owners["8084"]["container_id"] == WEB_CONTAINER_ID
    assert owners["8084"]["cwd"] == "/var/www/50sea.com"
    assert owners["8084"]["comm"] == "php-fpm"
    assert owners["8084"]["unit"] == "php8.2-fpm.service"
    # docker-proxy on 8085 has no container cgroup; still recorded as a backend.
    assert "8085" in owners
    assert owners["8085"]["container_id"] == ""


def _dokploy_container(name, project, *, container_id="", env=None):
    labels = {
        "com.docker.compose.project": project,
        "com.docker.compose.service": name.rsplit("-", 2)[-2] if name.count("-") >= 2 else name,
        "com.docker.compose.project.config_files": f"/etc/dokploy/compose/{project}/docker-compose.yml",
    }
    return {
        "Id": container_id or (name + "0" * 64)[:64],
        "Name": f"/{name}",
        "Config": {"Image": "app:latest", "Labels": labels, "Env": env or []},
        # Host networking: no PortBindings, so published-port match cannot work.
        "HostConfig": {"PortBindings": {}, "NetworkMode": "host"},
        "Mounts": [
            {"Type": "bind", "Source": f"/etc/dokploy/compose/{project}/files", "Destination": "/var/www/html"}
        ],
    }


def test_localhost_backend_resolves_container_via_socket_owner():
    nginx = """
# configuration file /etc/nginx/sites-enabled/50sea.com:
server {
    listen 80;
    server_name 50sea.com www.50sea.com;
    location / { proxy_pass http://127.0.0.1:8084; }
}
"""
    servers = da.parse_nginx_t(nginx)
    containers = [
        _dokploy_container("sea50-cyfdw1-web-1", "sea50-cyfdw1", container_id=WEB_CONTAINER_ID),
        _dokploy_container("sea50-cyfdw1-db-1", "sea50-cyfdw1", env=["MYSQL_DATABASE=sea_tecdb"]),
    ]
    # No published port matches 8084; only the listening-socket owner points at the web container.
    backend_owners = {"8084": {"port": "8084", "pid": "1234", "comm": "apache2", "container_id": WEB_CONTAINER_ID}}
    apps = da.applications_from_servers(
        servers,
        docker_containers=containers,
        backend_owners=backend_owners,
        path_exists=lambda _p: True,
        probe=lambda _root: ({}, {}),
    )
    by_host = {name: app for app in apps for name in (app.get("hostnames") or [])}
    sea = by_host["50sea.com"]
    assert sea["type"] == "Docker"
    assert sea["application_id"] == "docker:sea50-cyfdw1"
    assert sea["database_name"] == "sea_tecdb"
    assert sea["docker"]["db_container"] == "sea50-cyfdw1-db-1"


def test_localhost_backend_resolves_non_docker_host_process():
    nginx = """
# configuration file /etc/nginx/sites-enabled/xdgen.com:
server {
    listen 80;
    server_name xdgen.com www.xdgen.com;
    location / { proxy_pass http://127.0.0.1:8085; }
}
"""
    servers = da.parse_nginx_t(nginx)

    def probe(root):
        if root.rstrip("/") == "/var/www/xdgen.com":
            return (
                {"index.php": True, "wp-config.php": True, "wp-includes": True},
                {"wp-config.php": "define('DB_NAME', 'xdgen_db');\n"},
            )
        return ({}, {})

    backend_owners = {
        "8085": {
            "port": "8085",
            "pid": "4321",
            "comm": "php-fpm",
            "container_id": "",
            "cwd": "/var/www/xdgen.com",
            "unit": "php8.2-fpm.service",
        }
    }
    apps = da.applications_from_servers(
        servers,
        docker_containers=[],
        backend_owners=backend_owners,
        path_exists=lambda _p: True,
        probe=probe,
    )
    by_host = {name: app for app in apps for name in (app.get("hostnames") or [])}
    xdgen = by_host["xdgen.com"]
    assert xdgen["type"] == "WordPress"
    assert xdgen["root"] == "/var/www/xdgen.com"
    assert xdgen["database_name"] == "xdgen_db"
    assert "/var/www/xdgen.com" in (xdgen.get("source_paths") or [])
    assert any("traced to host process php-fpm" in note for note in xdgen.get("notes") or [])


def test_assemble_discovery_traces_proxy_backend_end_to_end():
    nginx = """
# configuration file /etc/nginx/sites-enabled/50sea.com:
server {
    listen 80;
    server_name 50sea.com www.50sea.com;
    location / { proxy_pass http://127.0.0.1:8084; }
}
"""
    servers = da.parse_nginx_t(nginx)
    containers = [
        _dokploy_container("sea50-cyfdw1-web-1", "sea50-cyfdw1", container_id=WEB_CONTAINER_ID),
        _dokploy_container("sea50-cyfdw1-db-1", "sea50-cyfdw1", env=["MYSQL_DATABASE=sea_tecdb"]),
    ]
    ss_output = (
        f"LISTEN 0 511 127.0.0.1:8084 0.0.0.0:* users:((\"apache2\",pid=1234,fd=8))\n"
    )
    run = _fake_run(
        {
            "ss -ltnpH": ss_output,
            "/proc/1234/cgroup": f"0::/system.slice/docker-{WEB_CONTAINER_ID}.scope\n",
            "/proc/1234/cwd": "/\n",
            "/proc/1234/exe": "/usr/sbin/apache2\n",
            "-p 1234": "docker-sea50.scope\n",
            "SHOW DATABASES": "",
        }
    )
    result = da.assemble_discovery(
        servers=servers,
        docker_containers=containers,
        mariadb=[],
        run=run,
        path_exists=lambda _p: True,
        probe=lambda _root: ({}, {}),
    )
    by_host = {name: app for app in result["applications"] for name in (app.get("hostnames") or [])}
    sea = by_host["50sea.com"]
    assert sea["application_id"] == "docker:sea50-cyfdw1"
    assert sea["database_name"] == "sea_tecdb"
    assert result["backend_owners"]["8084"]["container_id"] == WEB_CONTAINER_ID

    preflight = build_preflight(
        applications=result["applications"],
        database_inventory=result["database_inventory"],
        inventory=[],
    )
    report = format_attribution_report(preflight)
    assert "DOMAIN: 50sea.com" in report
    assert "DATABASE: sea_tecdb" in report
    assert "DOCKER PROJECT: sea50-cyfdw1" in report


def test_attribution_report_has_all_required_fields():
    apps = [
        {
            "application_id": "docker:sea50-cyfdw1",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "www.50sea.com"],
            "type": "WordPress",
            "root": "",
            "included": True,
            "status": "READY",
            "database_name": "sea_tecdb",
            "database_type": "MariaDB",
            "estimated_bytes": 1024,
            "source_paths": ["/etc/dokploy/compose/sea50-cyfdw1/files"],
            "persistent_data_paths": ["/etc/dokploy/compose/sea50-cyfdw1/files"],
            "configuration_paths": ["/etc/nginx/sites-enabled/50sea.com"],
            "source_file": "/etc/nginx/sites-enabled/50sea.com",
            "https": True,
            "ssl": {
                "mechanism": "letsencrypt",
                "storage_paths": ["/etc/letsencrypt/live/50sea.com/fullchain.pem"],
                "restore_procedure": "restore /etc/letsencrypt/live/50sea.com",
            },
            "docker": {
                "compose_project": "sea50-cyfdw1",
                "container": "sea50-cyfdw1-web-1",
                "db_container": "sea50-cyfdw1-db-1",
                "compose_file": "/etc/dokploy/compose/sea50-cyfdw1/docker-compose.yml",
                "mounts": [
                    {
                        "type": "bind",
                        "source": "/etc/dokploy/compose/sea50-cyfdw1/files",
                        "destination": "/var/www/html",
                        "named_volume": False,
                        "purpose": "application-data",
                    }
                ],
            },
        }
    ]
    inventory = [
        {
            "name": "sea_tecdb",
            "type": "MariaDB",
            "application_id": "docker:sea50-cyfdw1",
            "status": "ASSOCIATED WITH APPLICATION",
            "system": False,
            "docker_container": "sea50-cyfdw1-db-1",
            "references": [{"path": "docker:sea50-cyfdw1-db-1", "kind": "docker-db"}],
            "reason": "schema lives in Docker container sea50-cyfdw1-db-1",
        }
    ]
    preflight = build_preflight(applications=apps, database_inventory=inventory, inventory=[])
    report = format_attribution_report(preflight)
    for field in [
        "DOMAIN: 50sea.com",
        "APPLICATION:",
        "ACTUAL SOURCE PATHS:",
        "DOCKER PROJECT: sea50-cyfdw1",
        "CONTAINERS:",
        "PERSISTENT VOLUMES/BIND MOUNTS:",
        "DATABASE: sea_tecdb",
        "DATABASE CONTAINER: sea50-cyfdw1-db-1",
        "DATABASE CONFIG EVIDENCE:",
        "NGINX CONFIG:",
        "SSL: letsencrypt",
        "ESTIMATED SIZE:",
        "RESTORE STATUS:",
    ]:
        assert field in report, f"missing field: {field}"
    assert "docker:sea50-cyfdw1-db-1" in report
    assert "sea50-cyfdw1-db-1" in report
