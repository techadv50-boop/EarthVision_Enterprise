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


def test_published_port_match_uses_networksettings_ports():
    # Dokploy/runtime-published container: only NetworkSettings.Ports is set,
    # HostConfig.PortBindings is empty. This must still match nginx -> 8084.
    web = {
        "Id": WEB_CONTAINER_ID,
        "Name": "/sea50-cyfdw1-web-1",
        "Config": {"Image": "wp:latest", "Labels": {"com.docker.compose.project": "sea50-cyfdw1", "com.docker.compose.service": "web"}, "Env": []},
        "HostConfig": {"PortBindings": {}},
        "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8084"}]}},
        "Mounts": [],
    }
    db = _dokploy_container("sea50-cyfdw1-db-1", "sea50-cyfdw1", env=["MYSQL_DATABASE=sea_tecdb"])
    servers = da.parse_nginx_t(
        "# configuration file /etc/nginx/sites-enabled/50sea.com:\n"
        "server { listen 80; server_name 50sea.com; location / { proxy_pass http://127.0.0.1:8084; } }\n"
    )
    apps = da.applications_from_servers(
        servers, docker_containers=[web, db], backend_owners={},
        path_exists=lambda _p: True, probe=lambda _r: ({}, {}),
    )
    by_host = {n: a for a in apps for n in (a.get("hostnames") or [])}
    assert by_host["50sea.com"]["application_id"] == "docker:sea50-cyfdw1"
    assert by_host["50sea.com"]["database_name"] == "sea_tecdb"


def test_docker_database_texts_surfaces_connection_string_dbname():
    import discover_audit as audit

    containers = [
        {
            "Name": "/sateye-fz2ic4-web-1",
            "Config": {"Env": ["DATABASE_URL=postgresql://app:secret@db:5432/xdgen_db", "OTHER=1"]},
        },
        {
            "Name": "/sea50-web-1",
            "Config": {"Env": ["DB_DATABASE=sea_tecdb", "DB_PASSWORD=secret"]},
        },
    ]
    texts = audit.docker_database_texts(containers)
    assert "xdgen_db" in texts["docker:sateye-fz2ic4-web-1"]
    assert "secret" not in texts["docker:sateye-fz2ic4-web-1"]
    assert "sea_tecdb" in texts["docker:sea50-web-1"]
    assert "secret" not in texts["docker:sea50-web-1"]


def test_db_from_env_parses_connection_strings_and_framework_keys():
    assert da._db_from_env({"DATABASE_URL": "postgres://u:p@db:5432/xdgen_db?sslmode=require"}) == (
        "PostgreSQL",
        "xdgen_db",
        "",
    )
    assert da._db_from_env({"DB_CONNECTION": "mysql", "DB_DATABASE": "sea_tecdb", "DB_USERNAME": "wp"}) == (
        "MariaDB",
        "sea_tecdb",
        "wp",
    )
    assert da._db_from_env({"DB_DSN": "Host=db;Database=app_db;User Id=x;Password=secret"})[1] == "app_db"
    # A bare postgres:// with no db path should not invent one.
    assert da._db_from_env({"DATABASE_URL": "postgres://u:p@db:5432"})[1] == ""


def test_docker_summary_extracts_db_from_database_url():
    inspect = {
        "Id": WEB_CONTAINER_ID,
        "Name": "/xdgen-infgdf-web-1",
        "Config": {
            "Image": "app:latest",
            "Labels": {"com.docker.compose.project": "xdgen-infgdf", "com.docker.compose.service": "web"},
            "Env": ["DATABASE_URL=postgresql://app:secret@db:5432/xdgen_db", "SECRET_KEY=nope"],
        },
        "HostConfig": {"PortBindings": {}},
        "Mounts": [],
    }
    summary = da._docker_summary(inspect)
    assert summary["postgres_db"] == "xdgen_db"
    assert "secret" not in json_dumps(summary)


def json_dumps(obj):
    import json

    return json.dumps(obj)


def test_project_fallback_from_container_name():
    assert da._project_from_container_name("sateye-fz2ic4-redis-1") == "sateye-fz2ic4"
    assert da._project_from_container_name("journal50seacom-bkuksm-db-1") == "journal50seacom-bkuksm"
    assert da._project_from_container_name("standalone") == ""


def test_docker_proxy_container_ip_resolution():
    ss_output = 'LISTEN 0 511 127.0.0.1:8084 0.0.0.0:* users:(("docker-proxy",pid=555,fd=4))\n'
    run = _fake_run(
        {
            "ss -ltnpH": ss_output,
            "/proc/555/cgroup": "0::/system.slice/docker.service\n",
            "/proc/555/cmdline": "/usr/bin/docker-proxy\x00-proto\x00tcp\x00-host-ip\x00127.0.0.1\x00-host-port\x008084\x00-container-ip\x00172.18.0.5\x00-container-port\x0080\x00",
            "/proc/555/cwd": "/\n",
        }
    )
    owners = da.resolve_backend_owners(run)
    assert owners["8084"]["container_ip"] == "172.18.0.5"
    assert owners["8084"]["container_id"] == ""

    web = {
        "Id": WEB_CONTAINER_ID,
        "Name": "/sea50-cyfdw1-web-1",
        "Config": {"Image": "wp:latest", "Labels": {"com.docker.compose.project": "sea50-cyfdw1", "com.docker.compose.service": "web"}, "Env": []},
        "HostConfig": {"PortBindings": {}},
        "Mounts": [],
        "NetworkSettings": {"Networks": {"dokploy-network": {"IPAddress": "172.18.0.5"}}},
    }
    db = _dokploy_container("sea50-cyfdw1-db-1", "sea50-cyfdw1", env=["MYSQL_DATABASE=sea_tecdb"])
    servers = da.parse_nginx_t(
        "# configuration file /etc/nginx/sites-enabled/50sea.com:\n"
        "server { listen 80; server_name 50sea.com; location / { proxy_pass http://127.0.0.1:8084; } }\n"
    )
    apps = da.applications_from_servers(
        servers, docker_containers=[web, db], backend_owners=owners,
        path_exists=lambda _p: True, probe=lambda _r: ({}, {}),
    )
    by_host = {n: a for a in apps for n in (a.get("hostnames") or [])}
    assert by_host["50sea.com"]["application_id"] == "docker:sea50-cyfdw1"
    assert by_host["50sea.com"]["database_name"] == "sea_tecdb"


def test_redis_cache_volume_records_owner_and_is_not_unresolved():
    redis = {
        "Id": "redis" + "0" * 59,
        "Name": "/sateye-fz2ic4-redis-1",
        "Config": {"Image": "redis:7", "Labels": {"com.docker.compose.project": "sateye-fz2ic4", "com.docker.compose.service": "redis"}, "Env": []},
        "HostConfig": {"PortBindings": {}},
        # Volume name is an opaque hash and dest is /data — only the container name reveals redis.
        "Mounts": [{"Type": "volume", "Name": "deadbeefcafe1234", "Destination": "/data"}],
    }
    apps = [
        {
            "application_id": "docker:sateye-fz2ic4",
            "hostname": "xdgen.com",
            "hostnames": ["xdgen.com"],
            "docker": {"compose_project": "sateye-fz2ic4", "container": "sateye-fz2ic4-web-1"},
        }
    ]
    vols = da.inventory_docker_volumes([redis], apps)
    row = next(v for v in vols if v["name"] == "deadbeefcafe1234")
    assert row["purpose"] == "cache"
    assert row["application"] == "xdgen.com"
    assert row["scope"] == "cache"
    assert row["classification"] != da.CLASSIFICATION_UNRESOLVED
    assert "xdgen.com" in row["notes"]


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


def test_dead_backend_falls_back_to_last_known_docker_source():
    from app.backup.domain_map import build_domain_map

    apps = [
        {
            "application_id": "reverse-proxy:proxy:http://127.0.0.1:8084",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "www.50sea.com"],
            "type": "Reverse Proxy",
            "root": "",
            "proxy_pass": ["http://127.0.0.1:8084"],
            "included": True,
            "status": "READY",
            "source_paths": ["/etc/nginx/sites-enabled/50sea.com"],
            "docker": None,
        },
        {
            "application_id": "docker:sea50-cyfdw1",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "www.50sea.com"],
            "type": "WordPress",
            "change": "migrated",
            "root": "",
            "source_paths": ["/etc/dokploy/compose/sea50-cyfdw1/wp-content"],
            "persistent_data_paths": ["/etc/dokploy/compose/sea50-cyfdw1/wp-content", "volume:sea50_uploads"],
            "docker": {
                "compose_project": "sea50-cyfdw1",
                "container": "sea50-cyfdw1-web-1",
                "mounts": [
                    {"source": "/etc/dokploy/compose/sea50-cyfdw1/wp-content", "destination": "/var/www/html/wp-content", "named_volume": False}
                ],
            },
        },
    ]
    dm = build_domain_map(apps, [], approved_only=True)
    site = next(s for s in dm.sites if s.domain == "50sea.com")
    assert site.backend_status == "CURRENT BACKEND UNAVAILABLE"
    assert "/etc/dokploy/compose/sea50-cyfdw1/wp-content" in site.source_paths
    assert (site.docker or {}).get("compose_project") == "sea50-cyfdw1"
    assert "sea50_uploads" in site.named_volumes
    assert any("CURRENT BACKEND UNAVAILABLE" in w for w in site.warnings)


def test_dead_backend_without_evidence_is_documented_not_silent():
    from app.backup.domain_map import build_domain_map

    apps = [
        {
            "application_id": "reverse-proxy:proxy:http://127.0.0.1:8085",
            "hostname": "xdgen.com",
            "hostnames": ["xdgen.com", "www.xdgen.com"],
            "type": "Reverse Proxy",
            "root": "",
            "proxy_pass": ["http://127.0.0.1:8085"],
            "included": True,
            "status": "READY",
            "source_paths": ["/etc/nginx/sites-enabled/xdgen.com"],
            "docker": None,
        }
    ]
    dm = build_domain_map(apps, [], approved_only=True)
    site = next(s for s in dm.sites if s.domain == "xdgen.com")
    assert site.backend_status == "CURRENT BACKEND UNAVAILABLE"
    assert any("NO PERSISTENT SOURCE IDENTIFIED" in w for w in site.warnings)


def test_unexplained_items_warn_but_do_not_silently_block():
    from app.discover.gate import assess_backup_gate, format_backup_gate

    apps = [{"application_id": "docker:journal50seacom-bkuksm", "included": True, "status": "READY"}]
    classified = [
        # A nameless Nginx block and a legacy hostname — previously these blocked
        # BACKUP NOW with no printed reason.
        {"kind": "nginx", "hostname": "", "nginx": "/etc/nginx/sites-enabled/stub", "classification": "UNRESOLVED"},
    ]
    hostname_records = [
        {"kind": "hostname-investigation", "hostname": "satpass.xdgen.com", "role": "application-hostname", "assigned_website": False, "classification": "UNRESOLVED"},
    ]
    gate = assess_backup_gate(
        apps, [], volumes=[], classified=classified, hostname_records=hostname_records
    )
    assert gate["block_complete_backup"] is False
    assert gate["warnings"]
    text = "\n".join(format_backup_gate(gate))
    assert "WARNINGS" in text
    assert "satpass.xdgen.com" in text or "stub" in text


def test_gate_still_blocks_on_pending_apps_with_reason():
    from app.discover.gate import assess_backup_gate, format_backup_gate

    apps = [{"application_id": "docker:x", "hostname": "x.example.com", "included": False, "status": "NEW SITE DETECTED — REQUIRES APPROVAL"}]
    gate = assess_backup_gate(apps, [])
    assert gate["block_complete_backup"] is True
    text = "\n".join(format_backup_gate(gate))
    assert "pending applications" in text


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
