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

from discover_audit import (
    build_database_inventory,
    find_database_references,
    mariadb_schema_details,
    parse_generic_database_from_texts,
    scan_inactive_hostnames,
)

UNSAFE = set(";&|`$<>\\\n\r")
FILE_MARKER = re.compile(r"^# configuration file (.+):\s*$")
SERVER_OPEN = re.compile(r"\bserver\s*\{")
DIRECTIVE = re.compile(r"^([A-Za-z0-9_]+)\s+(.+?);$")
OJS_FILES_DIR = re.compile(r"^\s*files_dir\s*=\s*(.*)$", re.IGNORECASE)
OJS_VERSION = re.compile(r"^\s*version\s*=\s*(.*)$", re.IGNORECASE)
WP_DB = re.compile(r"""['"]DB_NAME['"]\s*,\s*['"]([^'"]+)['"]""")
DEFAULT_OJS_FALLBACK = "/var/www/ojs-files"
SKIP_HOSTS = {"", "*"}
CATCHALL_HOSTS = {"", "*", "_", "localhost"}
REDIRECT_CODES = {"301", "302", "303", "307", "308"}
SERVER_ONLY = re.compile(r"^server$")
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
    for prefix in EXCLUDED_PREFIXES:
        if cleaned == prefix:
            return True
        if prefix == "/tmp":
            if cleaned.startswith("/tmp/server-backup-work-"):
                return True
            continue
        if cleaned.startswith(prefix + "/"):
            return True
    return False


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
    pending_server = False
    for raw_line in (text or "").splitlines():
        marker = FILE_MARKER.match(raw_line)
        if marker:
            current_file = marker.group(1).strip()
            continue
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        if server_depth is None and not pending_server and SERVER_ONLY.match(line):
            pending_server = True
            continue
        if pending_server:
            pending_server = False
            if line.startswith("{"):
                line = "server " + line
            elif not SERVER_OPEN.search(line):
                depth += line.count("{") - line.count("}")
                depth = max(depth, 0)
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


def _skip_nginx_ws(text: str, index: int) -> int:
    n = len(text)
    while index < n:
        ch = text[index]
        if ch.isspace():
            index += 1
            continue
        if ch == "#":
            while index < n and text[index] not in "\n\r":
                index += 1
            continue
        break
    return index


def _read_nginx_header(text: str, index: int) -> tuple[str, int, str]:
    """Read until `;` or `{` at quote depth 0. Returns (header, index, terminator)."""
    n = len(text)
    start = index
    in_single = False
    in_double = False
    while index < n:
        ch = text[index]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and ch in ";{":
            return text[start:index].strip(), index, ch
        index += 1
    return text[start:index].strip(), index, ""


def _tokenize_nginx(text: str, index: int = 0) -> tuple[list[tuple[str, Any]], int]:
    """Parse nginx syntax into ('directive', key, value) or ('block', header, children)."""
    items: list[tuple[str, Any]] = []
    n = len(text)
    while True:
        index = _skip_nginx_ws(text, index)
        if index >= n:
            return items, index
        if text[index] == "}":
            return items, index + 1
        header, index, term = _read_nginx_header(text, index)
        if not header and not term:
            return items, index
        if term == ";":
            key, value = _split_directive(header)
            if key:
                items.append(("directive", key, value))
            index += 1
            continue
        if term == "{":
            children, index = _tokenize_nginx(text, index + 1)
            items.append(("block", header, children))
            continue
        key, value = _split_directive(header)
        if key:
            items.append(("directive", key, value))
        return items, index


def _split_directive(header: str) -> tuple[str, str]:
    parts = (header or "").split(None, 1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _walk_nginx(
    items: list[tuple[str, Any]],
    *,
    scope: str,
    listen: list[str],
    names: list[str],
    aliases: list[str],
    proxy_passes: list[str],
    includes: list[str],
    locations: list[dict[str, str]],
    redirects: list[str],
    server_root: list[str],
    loc: dict[str, str] | None = None,
) -> None:
    loc = loc if loc is not None else {}
    for kind, key_or_header, extra in items:
        if kind == "directive":
            key = str(key_or_header)
            value = str(extra)
            cleaned = _unquote(value)
            if key == "listen":
                listen.append(value)
            elif key == "server_name":
                names.extend(_split_names(value))
            elif key == "root":
                if scope == "server" and not server_root[0]:
                    server_root[0] = cleaned
                loc["root"] = cleaned
            elif key == "alias":
                loc["alias"] = cleaned
                aliases.append(cleaned)
            elif key == "proxy_pass":
                loc["proxy_pass"] = cleaned.rstrip("/")
                proxy_passes.append(cleaned.rstrip("/"))
            elif key == "include":
                includes.append(cleaned)
            elif key == "return":
                parts = value.split()
                if parts and parts[0] in REDIRECT_CODES:
                    target = _redirect_hostname(value)
                    if target:
                        redirects.append(target)
            elif key == "rewrite" and re.search(r"\b(redirect|permanent)\b", value, re.IGNORECASE):
                target = _redirect_hostname(value)
                if target:
                    redirects.append(target)
            continue
        header = str(key_or_header)
        children = list(extra or [])
        loc_match = re.match(r"^location\s+(.+)$", header.strip(), re.IGNORECASE)
        if loc_match:
            child_loc = {"path": loc_match.group(1).strip()}
            _walk_nginx(
                children,
                scope="location",
                listen=listen,
                names=names,
                aliases=aliases,
                proxy_passes=proxy_passes,
                includes=includes,
                locations=locations,
                redirects=redirects,
                server_root=server_root,
                loc=child_loc,
            )
            locations.append(dict(child_loc))
            continue
        _walk_nginx(
            children,
            scope=scope,
            listen=listen,
            names=names,
            aliases=aliases,
            proxy_passes=proxy_passes,
            includes=includes,
            locations=locations,
            redirects=redirects,
            server_root=server_root,
            loc=loc,
        )


def _parse_server_block(block: str, source_file: str) -> dict[str, Any] | None:
    listen: list[str] = []
    names: list[str] = []
    aliases: list[str] = []
    proxy_passes: list[str] = []
    includes: list[str] = []
    locations: list[dict[str, str]] = []
    redirects: list[str] = []
    server_root = [""]
    items, _end = _tokenize_nginx(block)
    body = items
    if items and items[0][0] == "block" and str(items[0][1]).strip().lower().startswith("server"):
        body = list(items[0][2] or [])
    _walk_nginx(
        body,
        scope="server",
        listen=listen,
        names=names,
        aliases=aliases,
        proxy_passes=proxy_passes,
        includes=includes,
        locations=locations,
        redirects=redirects,
        server_root=server_root,
    )
    root = server_root[0]
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
    ssl = any(_is_ssl_listen(item) for item in listen)
    http = any(not _is_ssl_listen(item) for item in listen) or not listen
    return {
        "source_file": source_file,
        "server_name": list(dict.fromkeys(names)),
        "listen": listen,
        "root": root,
        "alias": aliases,
        "proxy_pass": proxy_passes,
        "include": includes,
        "locations": locations,
        "redirect_to": redirects[0] if redirects else "",
        "http": http,
        "https": ssl,
        "ssl": ssl,
        "default_server": any("default_server" in item.split() for item in listen),
    }


def key_from_line(line: str) -> str:
    match = DIRECTIVE.match(line.strip())
    return match.group(1) if match else ""


def _is_ssl_listen(value: str) -> bool:
    parts = value.split()
    if not parts:
        return False
    return "ssl" in parts or parts[0].split(":")[0] == "443" or parts[0].endswith(":443") or parts[0].endswith("]:443")


def _unquote(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _split_names(value: str) -> list[str]:
    names: list[str] = []
    for item in value.replace(",", " ").split():
        cleaned = _unquote(item)
        if cleaned and cleaned not in SKIP_HOSTS:
            names.append(cleaned)
    return names


def _redirect_hostname(value: str) -> str:
    match = re.search(r"https?://([^/:\s$?#]+)", value or "", re.IGNORECASE)
    if not match:
        return ""
    host = _unquote(match.group(1)).strip().rstrip(".")
    if not host or host.startswith("$") or host.lower() in CATCHALL_HOSTS:
        return ""
    return host


def nginx_inventory(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in servers:
        rows.append(
            {
                "source_file": block.get("source_file") or "",
                "server_name": list(block.get("server_name") or []),
                "root": block.get("root") or "",
                "alias": list(block.get("alias") or []),
                "proxy_pass": list(block.get("proxy_pass") or []),
                "redirect_to": block.get("redirect_to") or "",
                "listen": list(block.get("listen") or []),
                "default_server": bool(block.get("default_server")),
                "http": bool(block.get("http")),
                "https": bool(block.get("https")),
            }
        )
    return rows


def parsed_hostnames(servers: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for block in servers:
        for name in block.get("server_name") or []:
            key = str(name).lower()
            if not name or key in seen:
                continue
            seen.add(key)
            names.append(str(name))
    return names


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
        ".env",
        ".env.local",
        ".env.production",
        "config.php",
        "database.php",
        "settings.php",
    )
    for name in names:
        path = base / name
        files[name] = path.is_file()
        if files[name] and (
            name.startswith(".env")
            or name.endswith((".php", ".txt", ".toml", ".json", ".yml", ".yaml"))
        ):
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


def _application_id(
    *,
    app_type: str,
    root: str = "",
    docker: dict[str, Any] | None = None,
    proxy_passes: list[str] | None = None,
) -> str:
    slug = (app_type or "other").strip().lower().replace(" ", "-").replace("/", "-")
    extra = (root or "").rstrip("/")
    if extra:
        return f"{slug}:{extra}"
    project = str((docker or {}).get("compose_project") or "")
    if project:
        return f"docker:{project}" if slug == "docker" else f"{slug}:docker:{project}"
    proxies = [p.rstrip("/") for p in (proxy_passes or []) if p]
    if proxies:
        return f"{slug}:proxy:{proxies[0]}"
    return f"{slug}:unknown"


def _canonical_hostname(names: list[str]) -> str:
    filtered = [n for n in names if n and n.lower() not in CATCHALL_HOSTS]
    use = filtered or [n for n in names if n] or ["_"]

    def sort_key(name: str) -> tuple[int, str]:
        lower = name.lower()
        return (1 if lower.startswith("www.") else 0, lower)

    return sorted(use, key=sort_key)[0]


def is_default_html_root(root: str) -> bool:
    parts = Path((root or "").rstrip("/") or "/").parts
    return len(parts) >= 2 and parts[-2:] == ("www", "html")


def is_unused_default_root(
    *,
    root: str,
    hostnames: list[str],
    listen: list[str],
    app_type: str,
    files: dict[str, bool],
) -> bool:
    """True for the distro default vhost (usually /var/www/html + default_server)."""
    if not is_default_html_root(root):
        return False
    named = [h for h in hostnames if h and h.lower() not in CATCHALL_HOSTS]
    if named:
        return False
    if files.get("wp-config.php") or files.get("config.inc.php") or files.get("composer.json") or files.get("package.json"):
        return False
    default_listen = any("default_server" in str(item).split() for item in listen)
    trivial = (app_type or "Other") in {"Other", "Static"}
    return trivial and (default_listen or not named)


def _merge_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Identity used to merge hostnames of the same application.

    Same filesystem path is not enough: type and database must also match.
    """
    if candidate.get("unused_default_root"):
        return ("unused-html", str(candidate.get("root") or ""))
    root = str(candidate.get("root") or "").rstrip("/")
    atype = str(candidate.get("type") or "").lower()
    db = (str(candidate.get("database_type") or "").lower(), str(candidate.get("database_name") or ""))
    if root:
        return ("app", atype, root, db)
    docker = candidate.get("docker") or {}
    project = str(docker.get("compose_project") or "")
    if project:
        return ("docker", atype, project, db)
    proxies = tuple(sorted(p.rstrip("/") for p in (candidate.get("proxy_pass") or []) if p))
    if proxies:
        return ("proxy", atype, proxies, db)
    return ("singleton", str(candidate.get("hostname") or ""), atype)


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    order: list[tuple[Any, ...]] = []
    for item in candidates:
        key = _merge_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    merged: list[dict[str, Any]] = []
    for key in order:
        rows = groups[key]
        ranked = sorted(
            rows,
            key=lambda r: (
                0 if r.get("unused_default_root") else 1,
                1 if r.get("database_name") else 0,
                1 if (r.get("root") or r.get("proxy_pass") or r.get("docker")) else 0,
                1 if str(r.get("status") or "") == "READY" else 0,
            ),
            reverse=True,
        )
        primary = dict(ranked[0])
        hostnames: list[str] = []
        notes: list[str] = list(primary.get("notes") or [])
        source_files: list[str] = []
        listens: list[str] = []
        proxies: list[str] = []
        aliases: list[str] = []
        config_paths: list[str] = []
        sources: list[str] = []
        persist: list[str] = []
        for row in rows:
            for name in row.get("hostnames") or [row.get("hostname")]:
                if name and name not in hostnames:
                    hostnames.append(str(name))
            for note in row.get("notes") or []:
                if note not in notes:
                    notes.append(note)
            for field, bucket in (
                ("source_file", source_files),
                ("listen", listens),
                ("proxy_pass", proxies),
                ("alias", aliases),
                ("configuration_paths", config_paths),
                ("source_paths", sources),
                ("persistent_data_paths", persist),
            ):
                values = row.get(field)
                if isinstance(values, list):
                    for value in values:
                        if value and value not in bucket:
                            bucket.append(value)
                elif values and values not in bucket:
                    bucket.append(values)
            primary["http"] = bool(primary.get("http") or row.get("http"))
            primary["https"] = bool(primary.get("https") or row.get("https"))
            primary["default_server"] = bool(primary.get("default_server") or row.get("default_server"))
            primary["estimated_bytes"] = max(int(primary.get("estimated_bytes") or 0), int(row.get("estimated_bytes") or 0))
            if row.get("ojs_files_dir") and not primary.get("ojs_files_dir"):
                primary["ojs_files_dir"] = row.get("ojs_files_dir")
            if row.get("database_name") and not primary.get("database_name"):
                primary["database_name"] = row.get("database_name")
                primary["database_type"] = row.get("database_type")
        if len(rows) > 1:
            notes.append(
                "Hostname aliases of the same application (verified Nginx root, type, and database)."
            )
            for row in rows:
                src = str(row.get("source_file") or "")
                if src:
                    notes.append(f"Nginx server block: {src}")
        notes = [note for note in notes if note != "no application root or proxy target"]
        if (
            not primary.get("unused_default_root")
            and (primary.get("root") or primary.get("proxy_pass") or primary.get("docker"))
            and primary.get("status") == "REQUIRES REVIEW"
            and not any(
                token in note
                for note in notes
                for token in ("invalid root", "duplicate hostname", "excluded root", "files_dir", "catch-all")
            )
        ):
            primary["status"] = "READY"
        details: dict[str, Any] = {}
        for row in rows:
            for name, meta in (row.get("hostname_details") or {}).items():
                if name and name not in details:
                    details[name] = meta
            if row.get("redirect_to") and not primary.get("redirect_to"):
                primary["redirect_to"] = row.get("redirect_to")
        primary["hostnames"] = hostnames
        primary["hostname"] = _canonical_hostname(hostnames)
        primary["hostname_details"] = details
        primary["listen"] = listens or list(primary.get("listen") or [])
        primary["proxy_pass"] = proxies or list(primary.get("proxy_pass") or [])
        primary["alias"] = aliases or list(primary.get("alias") or [])
        primary["configuration_paths"] = config_paths
        primary["source_paths"] = sources or list(primary.get("source_paths") or [])
        primary["persistent_data_paths"] = persist or list(primary.get("persistent_data_paths") or [])
        primary["source_files"] = source_files
        primary["notes"] = notes
        primary["application_id"] = _application_id(
            app_type=str(primary.get("type") or "Other"),
            root=str(primary.get("root") or ""),
            docker=primary.get("docker") if isinstance(primary.get("docker"), dict) else None,
            proxy_passes=list(primary.get("proxy_pass") or []),
        )
        merged.append(primary)
    seen_hosts: dict[str, int] = {}
    for app in merged:
        for name in app.get("hostnames") or []:
            seen_hosts[name.lower()] = seen_hosts.get(name.lower(), 0) + 1
    for app in merged:
        dups = [name for name in (app.get("hostnames") or []) if seen_hosts.get(name.lower(), 0) > 1]
        if dups:
            app["status"] = "REQUIRES REVIEW"
            note = "duplicate hostname: " + ", ".join(dups)
            if note not in (app.get("notes") or []):
                app.setdefault("notes", []).append(note)
    return merged


def _has_application_payload(candidate: dict[str, Any]) -> bool:
    if candidate.get("unused_default_root"):
        return False
    return bool(candidate.get("root") or candidate.get("proxy_pass") or candidate.get("docker"))


def _attach_ssl_and_redirect_peers(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach redirect-only / HTTP peer vhosts as aliases of the real application.

    Association is from Nginx (shared server_name or return/rewrite target),
    never from a shared filesystem path alone.
    """
    reals = [row for row in candidates if _has_application_payload(row)]
    by_host: dict[str, list[dict[str, Any]]] = {}
    for row in reals:
        for name in row.get("hostnames") or []:
            by_host.setdefault(str(name).lower(), []).append(row)
    for row in candidates:
        if _has_application_payload(row) or row.get("unused_default_root"):
            continue
        target: dict[str, Any] | None = None
        redirect_to = str(row.get("redirect_to") or "").lower()
        if redirect_to:
            matches = by_host.get(redirect_to) or []
            if len(matches) == 1:
                target = matches[0]
        if target is None:
            overlap: list[dict[str, Any]] = []
            seen_ids: set[int] = set()
            for name in row.get("hostnames") or []:
                for match in by_host.get(str(name).lower()) or []:
                    if id(match) in seen_ids:
                        continue
                    seen_ids.add(id(match))
                    overlap.append(match)
            if len(overlap) == 1:
                target = overlap[0]
        if target is None:
            continue
        if row.get("database_name") and target.get("database_name") and row.get("database_name") != target.get("database_name"):
            continue
        if row.get("type") not in {"Other", "Static", "", target.get("type")} and row.get("root"):
            continue
        row["root"] = target.get("root") or row.get("root")
        row["type"] = target.get("type")
        row["database_name"] = target.get("database_name") or row.get("database_name")
        row["database_type"] = target.get("database_type") or row.get("database_type")
        row["application_id"] = target.get("application_id")
        if not row.get("docker"):
            row["docker"] = target.get("docker")
        if not row.get("ojs_files_dir"):
            row["ojs_files_dir"] = target.get("ojs_files_dir")
        for path in target.get("source_paths") or []:
            if path and path not in (row.get("source_paths") or []):
                row.setdefault("source_paths", []).append(path)
        row.setdefault("notes", []).append(
            "Nginx hostname alias of "
            f"{target.get('hostname')} (redirect or HTTP/HTTPS peer; not path-only)."
        )
        row["notes"] = [n for n in (row.get("notes") or []) if n != "no application root or proxy target"]
        if row.get("status") == "REQUIRES REVIEW" and not any(
            token in note
            for note in row.get("notes") or []
            for token in ("invalid root", "duplicate hostname", "excluded root", "files_dir", "catch-all")
        ):
            row["status"] = "READY"
    return candidates


def _restore_dropped_hostnames(servers: list[dict[str, Any]], merged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalization must not silently drop an active Nginx server_name."""
    found = {str(name).lower() for app in merged for name in (app.get("hostnames") or [])}
    for name in parsed_hostnames(servers):
        if name.lower() in found:
            continue
        block = next(
            (item for item in servers if name in (item.get("server_name") or [])),
            {},
        )
        note = "Hostname present in active Nginx configuration but missing after normalization."
        merged.append(
            {
                "application_id": f"other:{name}",
                "hostname": name,
                "hostnames": [name],
                "hostname_details": {
                    name: {
                        "source_file": block.get("source_file") or "",
                        "root": block.get("root") or "",
                        "alias": list(block.get("alias") or []),
                        "proxy_pass": list(block.get("proxy_pass") or []),
                        "redirect_to": block.get("redirect_to") or "",
                        "listen": list(block.get("listen") or []),
                    }
                },
                "type": "Other",
                "discovery_source": "nginx -T",
                "root": block.get("root") or "",
                "alias": list(block.get("alias") or []),
                "proxy_pass": list(block.get("proxy_pass") or []),
                "redirect_to": block.get("redirect_to") or "",
                "configuration_paths": [block.get("source_file") or ""],
                "database_type": "",
                "database_name": "",
                "persistent_data_paths": [],
                "source_paths": [],
                "docker": None,
                "ojs_files_dir": "",
                "http": bool(block.get("http")),
                "https": bool(block.get("https")),
                "listen": list(block.get("listen") or []),
                "default_server": bool(block.get("default_server")),
                "unused_default_root": False,
                "source_file": block.get("source_file") or "",
                "source_files": [block.get("source_file") or ""],
                "estimated_bytes": 0,
                "status": "REQUIRES REVIEW",
                "notes": [note],
                "included": False,
                "excluded": False,
            }
        )
        found.add(name.lower())
    return merged


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
    candidates: list[dict[str, Any]] = []
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
        if not db_name:
            generic = parse_generic_database_from_texts(texts)
            if generic:
                db_name = generic
                db_type = db_type or "MariaDB"
        if docker:
            if docker.get("postgres_db"):
                db_type = "PostgreSQL"
                db_name = str(docker.get("postgres_db") or db_name)
            elif docker.get("mysql_database"):
                db_type = db_type or "MariaDB"
                db_name = str(docker.get("mysql_database") or db_name)
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
        notes: list[str] = []
        status = "READY"
        default_server = bool(block.get("default_server")) or any(
            "default_server" in str(item).split() for item in (block.get("listen") or [])
        )
        unused_default = is_unused_default_root(
            root=root,
            hostnames=names,
            listen=list(block.get("listen") or []),
            app_type=app_type,
            files=files,
        )
        if unused_default:
            status = "EXCLUDED — UNUSED DEFAULT ROOT"
            notes.append("Nginx unused default root (typically /var/www/html).")
            if default_server:
                notes.append("listen default_server")
            notes.append("server_name: " + ", ".join(names))
            notes.append(f"Nginx server block: {block.get('source_file') or 'unknown'}")
            notes.append(f"estimated size: {size_bytes} bytes")
            notes.append("Not a named public site; excluded from backup unless you override.")
        if any(seen_hosts.get(name.lower(), 0) > 1 for name in names):
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append("duplicate hostname")
        if all(name.lower() in CATCHALL_HOSTS for name in names) and not unused_default:
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append("catch-all/default server_name")
        if root and is_excluded_path(root):
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append(f"excluded root {root}")
            root_out = ""
        else:
            root_out = root
        if root and not _exists(root) and not unused_default:
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append(f"invalid root {root}")
        if app_type == "OJS" and ojs_error:
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append(ojs_error)
        if not root_out and not proxies and not docker and not unused_default:
            if status == "READY":
                status = "REQUIRES REVIEW"
            notes.append("no application root or proxy target")
        named = list(dict.fromkeys(names))
        details = {
            name: {
                "source_file": block.get("source_file") or "",
                "root": root_out,
                "alias": aliases,
                "proxy_pass": proxies,
                "redirect_to": block.get("redirect_to") or "",
                "listen": list(block.get("listen") or []),
            }
            for name in named
        }
        candidates.append(
            {
                "application_id": _application_id(
                    app_type=app_type,
                    root=root_out,
                    docker=docker if docker else None,
                    proxy_passes=proxies,
                ),
                "hostname": _canonical_hostname(named),
                "hostnames": named,
                "hostname_details": details,
                "type": app_type,
                "discovery_source": "nginx -T",
                "root": root_out,
                "alias": aliases,
                "proxy_pass": proxies,
                "redirect_to": block.get("redirect_to") or "",
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
                "default_server": default_server,
                "unused_default_root": unused_default,
                "source_file": block.get("source_file") or "",
                "estimated_bytes": size_bytes,
                "status": status,
                "notes": notes,
                "included": False,
                "excluded": bool(unused_default or (is_excluded_path(root) if root else False)),
            }
        )
    attached = _attach_ssl_and_redirect_peers(candidates)
    return _restore_dropped_hostnames(servers, _merge_candidates(attached))


def discover_applications(payload: dict | None = None, *, run=None, mysql_defaults=None) -> dict[str, Any]:
    """Collect a read-only inventory. payload may include previous_hostnames."""
    payload = payload if isinstance(payload, dict) else {}
    previous_hostnames = [str(n) for n in (payload.get("previous_hostnames") or []) if n]
    extra_scan_files = payload.get("hostname_scan_files") if isinstance(payload.get("hostname_scan_files"), dict) else None
    extra_config_texts = payload.get("config_texts") if isinstance(payload.get("config_texts"), dict) else None
    details_override = payload.get("database_details") if isinstance(payload.get("database_details"), dict) else None
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
    details: dict[str, dict[str, Any]] = dict(details_override or {})
    if mariadb and details_override is None:
        try:
            details = mariadb_schema_details(run, mysql_defaults, mariadb)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"MariaDB schema details skipped: {exc}")
    search_roots = [str(app.get("root") or "") for app in apps if app.get("root")]
    search_roots.extend(["/opt"])
    try:
        references = find_database_references(
            mariadb,
            search_roots,
            extra_texts=extra_config_texts,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"database reference search skipped: {exc}")
        references = {}
    database_inventory = build_database_inventory(
        mariadb,
        apps,
        details=details,
        references=references,
    )
    by_id = {str(app.get("application_id") or ""): app for app in apps}
    for row in database_inventory:
        ident = str(row.get("application_id") or "")
        app = by_id.get(ident)
        if app and row.get("name") and not app.get("database_name") and str(row.get("status") or "").startswith("ASSOCIATED"):
            app["database_name"] = row["name"]
            app["database_type"] = "MariaDB"
    docker_hosts: list[str] = []
    for inspect in docker_containers:
        config = inspect.get("Config") or {}
        labels = config.get("Labels") or {}
        for key, value in {**labels, **{}}.items():
            text = str(value or "")
            if "VIRTUAL_HOST" in str(key).upper() or "hostname" in str(key).lower():
                docker_hosts.extend(part.strip() for part in text.replace(",", " ").split() if "." in part)
        for item in config.get("Env") or []:
            if str(item).startswith("VIRTUAL_HOST="):
                docker_hosts.extend(part.strip() for part in str(item).split("=", 1)[1].replace(",", " ").split() if "." in part)
    try:
        inactive_hostnames = scan_inactive_hostnames(
            parsed_hostnames(servers),
            previous_hostnames=previous_hostnames,
            parse_nginx_t=parse_nginx_t,
            extra_files=extra_scan_files,
            docker_hint_hostnames=docker_hosts,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"inactive hostname scan skipped: {exc}")
        inactive_hostnames = []
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
        "nginx_inventory": nginx_inventory(servers),
        "parsed_hostnames": parsed_hostnames(servers),
        "inactive_hostnames": inactive_hostnames,
        "database_inventory": database_inventory,
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
