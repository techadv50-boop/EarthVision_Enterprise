#!/usr/bin/env python3
"""Read-only application discovery from Nginx, filesystem evidence, and Docker.

Never modifies Nginx, PHP-FPM, MariaDB, PostgreSQL, Docker, or application files.
Never backups /var/lib/docker or /var/lib/containerd wholesale.
Never falls back to /var/www/ojs-files when OJS files_dir is missing.
"""

from __future__ import annotations

import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

UNSAFE = set(";&|`$<>\\\n\r")
FILE_MARKER = re.compile(r"^# configuration file (.+):\s*$")
SERVER_OPEN = re.compile(r"\bserver\s*\{")
DIRECTIVE = re.compile(r"^([A-Za-z0-9_]+)\s+(.+?);$")
OJS_FILES_DIR = re.compile(r"^\s*files_dir\s*=\s*(.*)$", re.IGNORECASE)
OJS_VERSION = re.compile(r"^\s*version\s*=\s*(.*)$", re.IGNORECASE)
WP_DB = re.compile(r"""['"]DB_NAME['"]\s*,\s*['"]([^'"]+)['"]""")
DEFAULT_OJS_FALLBACK = "/var/www/ojs-files"
SKIP_HOSTS = {"", "*"}
EXCLUDED_PREFIXES = (
    "/var/lib/docker",
    "/var/lib/containerd",
    "/tmp",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/boot",
    "/srv/namecheap-migration",
    "/home/zhzh/server-migration-backup",
)
SECRET_KEYS = ("password", "passwd", "secret", "api_key", "private_key")


def _strip_value(raw: str) -> str:
    value = (raw or "").strip()
    if ";" in value and not (value.startswith('"') or value.startswith("'")):
        value = value.split(";", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def safe_unix(path: str) -> str:
    cleaned = (path or "").strip()
    if not cleaned.startswith("/") or ".." in cleaned or any(ch in cleaned for ch in UNSAFE):
        return ""
    return cleaned.rstrip("/") or "/"


def is_excluded_path(path: str) -> bool:
    cleaned = (path or "").rstrip("/")
    if not cleaned:
        return True
    return any(cleaned == prefix or cleaned.startswith(prefix + "/") for prefix in EXCLUDED_PREFIXES)


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    in_single = False
    in_double = False
    out = []
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out)


def parse_nginx_t(text: str) -> list[dict[str, Any]]:
    """Parse `nginx -T` into server blocks with hostnames, roots, aliases, and proxy_pass."""
    current_file = ""
    depth = 0
    server_depth: int | None = None
    buf: list[str] = []
    servers: list[dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        marker = FILE_MARKER.match(raw_line)
        if marker:
            current_file = marker.group(1).strip()
            continue
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        opens = line.count("{")
        closes = line.count("}")
        if server_depth is None and SERVER_OPEN.search(line):
            server_depth = depth
            buf = [line]
            depth += opens - closes
            if depth <= server_depth:
                parsed = _parse_server_block("\n".join(buf), current_file)
                if parsed:
                    servers.append(parsed)
                server_depth = None
                buf = []
            continue
        if server_depth is not None:
            buf.append(line)
            depth += opens - closes
            if depth <= server_depth:
                parsed = _parse_server_block("\n".join(buf), current_file)
                if parsed:
                    servers.append(parsed)
                server_depth = None
                buf = []
            continue
        depth += opens - closes
        depth = max(depth, 0)
    return servers


def _parse_server_block(block: str, source_file: str) -> dict[str, Any] | None:
    listen: list[str] = []
    names: list[str] = []
    root = ""
    aliases: list[str] = []
    proxy_passes: list[str] = []
    includes: list[str] = []
    ssl = False
    locations: list[dict[str, str]] = []
    loc_path = ""
    loc_depth = 0
    current_loc: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        opens = line.count("{")
        closes = line.count("}")
        loc_match = re.match(r"^location\s+(.+?)\s*\{", line)
        if loc_match and loc_depth == 0:
            loc_path = loc_match.group(1).strip()
            current_loc = {"path": loc_path}
            loc_depth = max(1, loc_depth + opens - closes)
            if loc_depth == 0 and current_loc:
                locations.append(current_loc)
                current_loc = {}
            continue
        if loc_depth > 0:
            _apply_directive(line, listen, names, current_loc, aliases, proxy_passes, includes)
            if "ssl" in line.split():
                ssl = True
            loc_depth += opens - closes
            if loc_depth <= 0:
                if current_loc:
                    locations.append(current_loc)
                current_loc = {}
                loc_depth = 0
            continue
        if line.startswith("server {") or line == "server{":
            continue
        _apply_directive(line, listen, names, {"root": "", "alias": "", "proxy_pass": ""}, aliases, proxy_passes, includes)
        match = DIRECTIVE.match(line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if key == "root" and not root:
                root = _unquote(value)
            elif key == "server_name":
                names.extend(_split_names(value))
            elif key == "listen":
                listen.append(value)
                if "ssl" in value.split():
                    ssl = True
            elif key == "alias":
                aliases.append(_unquote(value))
            elif key == "proxy_pass":
                proxy_passes.append(_unquote(value).rstrip("/"))
            elif key == "include":
                includes.append(_unquote(value))
        if "ssl" in line.split() and key_from_line(line) == "listen":
            ssl = True
    if not names and not listen:
        return None
    if not names:
        names = ["_"]
    loc_roots = [item.get("root") or "" for item in locations if item.get("root")]
    loc_alias = [item.get("alias") or "" for item in locations if item.get("alias")]
    loc_proxy = [item.get("proxy_pass") or "" for item in locations if item.get("proxy_pass")]
    if loc_roots and not root:
        root = loc_roots[0]
    aliases = list(dict.fromkeys([*aliases, *loc_alias]))
    proxy_passes = list(dict.fromkeys([*proxy_passes, *loc_proxy]))
    http = any(not _is_ssl_listen(item) for item in listen) or not listen
    https = ssl or any(_is_ssl_listen(item) for item in listen)
    return {
        "source_file": source_file,
        "server_name": list(dict.fromkeys(names)),
        "listen": listen,
        "root": root,
        "alias": aliases,
        "proxy_pass": proxy_passes,
        "include": includes,
        "locations": locations,
        "http": http,
        "https": https,
        "ssl": https,
    }


def key_from_line(line: str) -> str:
    match = DIRECTIVE.match(line.strip())
    return match.group(1) if match else ""


def _is_ssl_listen(value: str) -> bool:
    parts = value.split()
    return "ssl" in parts or "443" in parts[0]


def _unquote(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _split_names(value: str) -> list[str]:
    return [item for item in value.split() if item and item not in SKIP_HOSTS]


def _apply_directive(
    line: str,
    listen: list[str],
    names: list[str],
    loc: dict[str, str],
    aliases: list[str],
    proxy_passes: list[str],
    includes: list[str],
) -> None:
    match = DIRECTIVE.match(line)
    if not match:
        return
    key, value = match.group(1), match.group(2).strip()
    cleaned = _unquote(value)
    if key == "root":
        loc["root"] = cleaned
    elif key == "alias":
        loc["alias"] = cleaned
        aliases.append(cleaned)
    elif key == "proxy_pass":
        loc["proxy_pass"] = cleaned.rstrip("/")
        proxy_passes.append(cleaned.rstrip("/"))
    elif key == "include":
        includes.append(cleaned)
    elif key == "server_name":
        names.extend(_split_names(value))
    elif key == "listen":
        listen.append(value)


def parse_proxy(url: str) -> dict[str, str]:
    raw = (url or "").strip()
    if not raw:
        return {}
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or ""
    port = str(parsed.port or (443 if parsed.scheme == "https" else 80))
    return {"scheme": parsed.scheme or "http", "host": host, "port": port, "url": url}


def classify_application(
    *,
    root: str,
    aliases: list[str],
    proxy_passes: list[str],
    docker: dict[str, Any] | None,
    files: dict[str, bool],
    texts: dict[str, str],
) -> str:
    """Classify from config/filesystem evidence. Hostnames are never hardcoded."""
    config_php = texts.get("config.inc.php") or ""
    if files.get("config.inc.php") or "files_dir" in config_php.lower():
        return "OJS"
    if files.get("wp-config.php") or files.get("wp-includes"):
        return "WordPress"
    if docker:
        return "Docker"
    if files.get("package.json") or files.get("node_modules"):
        return "Node"
    req = (texts.get("requirements.txt") or "") + "\n" + (texts.get("pyproject.toml") or "")
    if files.get("requirements.txt") or files.get("pyproject.toml") or "fastapi" in req.lower() or "uvicorn" in req.lower():
        return "Python/FastAPI"
    if proxy_passes:
        return "Reverse Proxy"
    if files.get("index.php") or files.get("composer.json"):
        return "PHP"
    if files.get("index.html") or files.get("index.htm"):
        return "Static"
    if root:
        return "Other"
    return "Other"


def parse_files_dir(config_text: str) -> str | None:
    for line in (config_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = OJS_FILES_DIR.match(stripped)
        if match:
            return _strip_value(match.group(1)) or None
    return None


def parse_ojs_version(config_text: str) -> str:
    for line in (config_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = OJS_VERSION.match(stripped)
        if match:
            value = _strip_value(match.group(1))
            if value:
                return value
    return "unknown"


def parse_ojs_database_name(config_text: str) -> str | None:
    in_database = False
    for line in (config_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_database = stripped.lower() == "[database]"
            continue
        if not in_database or stripped.startswith((";", "#")):
            continue
        if re.match(r"^\s*name\s*=", stripped, re.IGNORECASE):
            value = _strip_value(stripped.split("=", 1)[1])
            if value and value.lower() not in SECRET_KEYS:
                return value
    return None


def parse_wp_database_name(config_text: str) -> str | None:
    match = WP_DB.search(config_text or "")
    return match.group(1) if match else None


def resolve_files_dir(raw: str, application_path: str) -> str | None:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("/"):
        resolved = safe_unix(cleaned)
    else:
        resolved = safe_unix(str(Path(application_path.rstrip("/")) / cleaned))
    return resolved or None


def _dir_stats(path: Path, limit: int = 20000) -> tuple[int, int]:
    files = 0
    size = 0
    if not path.is_dir():
        return 0, 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if name not in {".git", "node_modules", "cache"}]
        for name in names:
            file_path = Path(root) / name
            try:
                info = file_path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                files += 1
                size += int(info.st_size)
                if files >= limit:
                    return size, files
    return size, files


def _probe_root(root: str) -> tuple[dict[str, bool], dict[str, str]]:
    files: dict[str, bool] = {}
    texts: dict[str, str] = {}
    base = Path(root)
    if not root or not base.is_dir():
        return files, texts
    names = (
        "config.inc.php",
        "wp-config.php",
        "index.php",
        "index.html",
        "index.htm",
        "package.json",
        "composer.json",
        "requirements.txt",
        "pyproject.toml",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yaml",
    )
    for name in names:
        path = base / name
        files[name] = path.is_file()
        if files[name] and name.endswith((".php", ".txt", ".toml", ".json", ".yml", ".yaml")):
            try:
                texts[name] = path.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                texts[name] = ""
    files["wp-includes"] = (base / "wp-includes").is_dir()
    files["node_modules"] = (base / "node_modules").is_dir()
    return files, texts


def _list_mariadb(run: Callable, mysql_defaults: Callable) -> list[str]:
    try:
        result = run(["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "-e", "SHOW DATABASES"], timeout=30)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _docker_containers(run: Callable) -> list[dict[str, Any]]:
    result = run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=20)
    if result.returncode != 0:
        return []
    rows = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    detailed = []
    for row in rows:
        ident = str(row.get("ID") or row.get("Id") or "")
        if not ident:
            continue
        inspect = run(["docker", "inspect", ident], timeout=20)
        if inspect.returncode != 0:
            continue
        try:
            payload = json.loads(inspect.stdout or "[]")
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and payload:
            detailed.append(payload[0])
    return detailed


def _docker_summary(inspect: dict[str, Any]) -> dict[str, Any]:
    config = inspect.get("Config") or {}
    labels = config.get("Labels") or {}
    host_config = inspect.get("HostConfig") or {}
    ports = host_config.get("PortBindings") or {}
    published = []
    for container_port, binds in ports.items():
        for bind in binds or []:
            published.append(
                {
                    "container_port": str(container_port),
                    "host_ip": bind.get("HostIp") or "0.0.0.0",
                    "host_port": bind.get("HostPort") or "",
                }
            )
    mounts = []
    for mount in inspect.get("Mounts") or []:
        if not isinstance(mount, dict):
            continue
        dest = str(mount.get("Destination") or "")
        source = str(mount.get("Source") or mount.get("Name") or "")
        mtype = str(mount.get("Type") or "")
        if mtype == "bind" and is_excluded_path(source):
            continue
        mounts.append(
            {
                "type": mtype,
                "source": source if mtype == "bind" else str(mount.get("Name") or source),
                "destination": dest,
                "named_volume": mtype == "volume",
            }
        )
    env_map = {}
    for item in config.get("Env") or []:
        if "=" in str(item):
            key, value = str(item).split("=", 1)
            if key.lower() in SECRET_KEYS or "password" in key.lower() or "secret" in key.lower():
                continue
            env_map[key] = value
    return {
        "id": str(inspect.get("Id") or "")[:12],
        "name": str((inspect.get("Name") or "").lstrip("/")),
        "image": str(config.get("Image") or ""),
        "compose_project": labels.get("com.docker.compose.project") or "",
        "compose_service": labels.get("com.docker.compose.service") or "",
        "compose_workdir": labels.get("com.docker.compose.project.working_dir") or "",
        "compose_files": labels.get("com.docker.compose.project.config_files") or "",
        "published_ports": published,
        "mounts": mounts,
        "postgres_db": env_map.get("POSTGRES_DB") or env_map.get("POSTGRES_USER") and env_map.get("POSTGRES_DB"),
        "mysql_database": env_map.get("MYSQL_DATABASE") or env_map.get("MARIADB_DATABASE"),
    }


def _match_docker(proxy_passes: list[str], containers: list[dict[str, Any]]) -> dict[str, Any] | None:
    summaries = [_docker_summary(item) for item in containers]
    for proxy in proxy_passes:
        parsed = parse_proxy(proxy)
        host = (parsed.get("host") or "").lower()
        port = parsed.get("port") or ""
        for item in summaries:
            names = {
                item["name"].lower(),
                item["compose_service"].lower(),
                item["compose_project"].lower(),
            }
            if host and host in names:
                return item
            if host in {"127.0.0.1", "localhost", "::1"}:
                for pub in item.get("published_ports") or []:
                    if str(pub.get("host_port")) == port:
                        return item
    return None


def _application_id(hostname: str, root: str) -> str:
    host = hostname.strip().lower()
    extra = root.rstrip("/") if root else ""
    return f"{host}:{extra}" if extra else host


def applications_from_servers(
    servers: list[dict[str, Any]],
    *,
    probe: Callable[[str], tuple[dict[str, bool], dict[str, str]]] | None = None,
    docker_containers: list[dict[str, Any]] | None = None,
    mariadb: list[str] | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    probe = probe or _probe_root
    docker_containers = docker_containers or []
    mariadb = mariadb or []

    def _exists(path: str) -> bool:
        if path_exists is not None:
            return path_exists(path)
        try:
            return Path(path).is_dir()
        except OSError:
            return False
    seen_hosts: dict[str, int] = {}
    for block in servers:
        for name in block.get("server_name") or []:
            seen_hosts[name.lower()] = seen_hosts.get(name.lower(), 0) + 1
    apps: list[dict[str, Any]] = []
    for block in servers:
        names = [n for n in (block.get("server_name") or []) if n]
        if not names:
            continue
        root = safe_unix(str(block.get("root") or ""))
        aliases = [safe_unix(p) for p in (block.get("alias") or []) if safe_unix(p)]
        proxies = list(block.get("proxy_pass") or [])
        docker = _match_docker(proxies, docker_containers)
        files, texts = probe(root) if root and not is_excluded_path(root) else ({}, {})
        app_type = classify_application(
            root=root,
            aliases=aliases,
            proxy_passes=proxies,
            docker=docker,
            files=files,
            texts=texts,
        )
        ojs_files_dir = ""
        ojs_error = ""
        db_name = ""
        db_type = ""
        config_text = texts.get("config.inc.php") or ""
        if app_type == "OJS":
            raw = parse_files_dir(config_text)
            if not raw:
                ojs_error = "config.inc.php has no files_dir"
            else:
                resolved = resolve_files_dir(raw, root)
                if not resolved:
                    ojs_error = f"invalid files_dir {raw!r}"
                elif resolved == DEFAULT_OJS_FALLBACK and raw not in {DEFAULT_OJS_FALLBACK, DEFAULT_OJS_FALLBACK + "/"}:
                    ojs_error = f"refusing silent fallback to {DEFAULT_OJS_FALLBACK}; configured files_dir is {raw!r}"
                else:
                    ojs_files_dir = resolved
                    if not _exists(resolved):
                        ojs_error = f"files_dir {resolved} does not exist"
            db_name = parse_ojs_database_name(config_text) or ""
            db_type = "MariaDB" if db_name else ""
        elif app_type == "WordPress":
            db_name = parse_wp_database_name(texts.get("wp-config.php") or "") or ""
            db_type = "MariaDB" if db_name else ""
        if docker:
            if docker.get("postgres_db"):
                db_type = "PostgreSQL"
                db_name = str(docker.get("postgres_db") or db_name)
            elif docker.get("mysql_database"):
                db_type = db_type or "MariaDB"
                db_name = str(docker.get("mysql_database") or db_name)
        if db_name and db_type == "MariaDB" and mariadb and db_name not in mariadb:
            # Keep the association; mark review if the backup account cannot see it.
            pass
        persistent = []
        for path in [ojs_files_dir, *aliases]:
            if path and path not in persistent and not is_excluded_path(path):
                persistent.append(path)
        if docker:
            for mount in docker.get("mounts") or []:
                source = str(mount.get("source") or "")
                if mount.get("named_volume"):
                    persistent.append(f"volume:{source}")
                elif source and not is_excluded_path(source) and source not in persistent:
                    persistent.append(source)
        sources = []
        if root and not is_excluded_path(root):
            sources.append(root)
        sources.extend([p for p in persistent if p and not str(p).startswith("volume:")])
        config_paths = [str(block.get("source_file") or "")]
        if root:
            if files.get("config.inc.php"):
                config_paths.append(f"{root}/config.inc.php")
            if files.get("wp-config.php"):
                config_paths.append(f"{root}/wp-config.php")
        if docker and docker.get("compose_files"):
            config_paths.extend(str(docker.get("compose_files")).split(","))
        size_bytes = 0
        if probe is _probe_root:
            for path in sources:
                try:
                    size, _count = _dir_stats(Path(path))
                    size_bytes += size
                except OSError:
                    pass
        for hostname in names:
            notes: list[str] = []
            status = "READY"
            if seen_hosts.get(hostname.lower(), 0) > 1:
                status = "REQUIRES REVIEW"
                notes.append("duplicate hostname")
            if hostname in {"_", "localhost"}:
                status = "REQUIRES REVIEW"
                notes.append("catch-all/default server_name")
            if root and is_excluded_path(root):
                status = "REQUIRES REVIEW"
                notes.append(f"excluded root {root}")
                root_out = ""
            else:
                root_out = root
            if root and not _exists(root):
                status = "REQUIRES REVIEW"
                notes.append(f"invalid root {root}")
            if app_type == "OJS" and ojs_error:
                status = "REQUIRES REVIEW"
                notes.append(ojs_error)
            if not root_out and not proxies and not docker:
                status = "REQUIRES REVIEW"
                notes.append("no application root or proxy target")
            apps.append(
                {
                    "application_id": _application_id(hostname, root_out),
                    "hostname": hostname,
                    "type": app_type,
                    "discovery_source": "nginx -T",
                    "root": root_out,
                    "alias": aliases,
                    "proxy_pass": proxies,
                    "configuration_paths": [p for p in config_paths if p],
                    "database_type": db_type,
                    "database_name": db_name,
                    "persistent_data_paths": persistent,
                    "source_paths": list(dict.fromkeys(sources)),
                    "docker": {
                        "compose_project": docker.get("compose_project"),
                        "compose_file": docker.get("compose_files"),
                        "service": docker.get("compose_service"),
                        "container": docker.get("name"),
                        "workdir": docker.get("compose_workdir"),
                    }
                    if docker
                    else None,
                    "ojs_files_dir": ojs_files_dir,
                    "http": bool(block.get("http")),
                    "https": bool(block.get("https")),
                    "listen": list(block.get("listen") or []),
                    "source_file": block.get("source_file") or "",
                    "estimated_bytes": size_bytes,
                    "status": status,
                    "notes": notes,
                    "included": False,
                    "excluded": is_excluded_path(root) if root else False,
                }
            )
    return apps


def discover_applications(payload: dict | None = None, *, run=None, mysql_defaults=None) -> dict[str, Any]:
    """Collect a read-only inventory. payload is unused except for future flags."""
    del payload
    errors: list[str] = []
    nginx_text = ""
    nginx_ok = False
    if run is None:
        import subprocess

        def run(cmd, timeout=60):  # type: ignore[misc]
            return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)

    if mysql_defaults is None:
        def mysql_defaults():  # type: ignore[misc]
            cnf = Path("/etc/serverbackup/my.cnf")
            return [f"--defaults-extra-file={cnf}"] if cnf.is_file() else []

    nginx_bin = "/usr/sbin/nginx" if Path("/usr/sbin/nginx").is_file() else "nginx"
    try:
        result = run([nginx_bin, "-T"], timeout=30)
        nginx_text = (result.stdout or "") + ("\n" + result.stderr if result.stderr and "configuration file" in (result.stderr or "") else "")
        nginx_ok = result.returncode == 0 and bool(nginx_text.strip())
        if not nginx_ok:
            errors.append(result.stderr.strip() or "nginx -T failed")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"nginx -T failed: {exc}")
    servers = parse_nginx_t(nginx_text) if nginx_text else []
    if nginx_ok and not servers:
        errors.append("nginx -T returned no server blocks")
    docker_containers: list[dict[str, Any]] = []
    try:
        docker_containers = _docker_containers(run)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"docker inspect skipped: {exc}")
    mariadb: list[str] = []
    try:
        mariadb = _list_mariadb(run, mysql_defaults)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"MariaDB discovery skipped: {exc}")
    apps = applications_from_servers(
        servers,
        docker_containers=docker_containers,
        mariadb=mariadb,
    )
    postgres = sorted(
        {
            str(app.get("database_name"))
            for app in apps
            if app.get("database_type") == "PostgreSQL" and app.get("database_name")
        }
    )
    return {
        "ok": nginx_ok,
        "hostname": socket.gethostname(),
        "discovery_source": "nginx -T",
        "nginx_ok": nginx_ok,
        "applications": apps,
        "servers": servers,
        "databases": {
            "mariadb": mariadb,
            "postgresql": postgres,
        },
        "docker_projects": sorted(
            {
                str((app.get("docker") or {}).get("compose_project"))
                for app in apps
                if (app.get("docker") or {}).get("compose_project")
            }
        ),
        "errors": errors,
    }


def handle(action: str, payload: dict, *, run=None, mysql_defaults=None) -> dict[str, Any]:
    if action != "discover-applications":
        return {"ok": False, "error": f"unhandled discovery action {action}"}
    return discover_applications(payload, run=run, mysql_defaults=mysql_defaults)
