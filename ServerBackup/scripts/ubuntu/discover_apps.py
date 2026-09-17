#!/usr/bin/env python3
"""Read-only application discovery from Nginx, filesystem evidence, and Docker.

Never modifies Nginx, PHP-FPM, MariaDB, PostgreSQL, Docker, or application files.
Never backups /var/lib/docker or /var/lib/containerd wholesale.
Named volume `_data` directories associated with a website may be inventoried.
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
    docker_database_texts,
    find_database_references,
    inspect_database_contents,
    mariadb_account_info,
    mariadb_schema_details,
    parse_generic_database_from_texts,
    scan_inactive_hostnames,
)
from docker_db import docker_schema_details_for
from path_safety import is_named_volume_data_path, is_safe_unix_syntax, named_volume_data_path, require_docker_name

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
TRAEFIK_HOST_CALL = re.compile(r"Host(?:Regexp)?\(\s*([^)]+)\)", re.IGNORECASE)
QUOTED_TOKEN = re.compile(r"[`'\"]([^`'\"]+)[`'\"]")
HOSTNAME_TOKEN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
DB_VOLUME_DEST_HINTS = (
    "/var/lib/postgresql",
    "/var/lib/mysql",
    "/var/lib/mariadb",
    "/var/lib/postgresql/data",
)
CACHE_VOLUME_DEST_HINTS = ("/var/lib/redis", "/data/cache", "/tmp", "/var/tmp")
DOKPLOY_SCAN_ROOTS = (
    "/etc/dokploy",
    "/etc/dokploy/compose",
    "/etc/dokploy/applications",
    "/etc/dokploy/traefik",
    "/etc/dokploy/traefik/dynamic",
    "/opt/dokploy",
    "/opt/dokploy-migrations",
    "/root/dokploy-migration",
)
TRAEFIK_SCAN_ROOTS = (
    "/etc/dokploy/traefik",
    "/etc/dokploy/traefik/dynamic",
    "/etc/traefik",
    "/etc/traefik/dynamic",
    "/etc/traefik/conf.d",
)
WWW_SCAN_ROOTS = ("/var/www",)
PHP_FPM_SCAN_ROOTS = ("/etc/php", "/etc/php-fpm.d", "/etc/php-fpm.conf")
LIVE_PROXY_PATH_HINTS = (
    "/etc/dokploy/traefik",
    "/etc/traefik",
    "traefik/dynamic",
    "/etc/dokploy/applications",
)
MIGRATION_PATH_HINTS = (
    "/opt/dokploy-migrations",
    "/root/dokploy-migration",
    "/srv/namecheap-migration",
)
BACKEND_URL = re.compile(
    r"""(?:^\s*(?:-\s*)?url:\s*['"]?(https?://[^\s'"]+)['"]?|"url"\s*:\s*"(https?://[^"]+)")""",
    re.IGNORECASE | re.MULTILINE,
)
SITE_URL_ENV = re.compile(
    r"^(?:SITE_URL|APP_URL|PUBLIC_URL|PUBLIC_HOST|PUBLIC_HOSTNAME|BASE_URL|ALLOWED_HOSTS|"
    r"DOMAIN|HOST|HOSTNAME|TRAEFIK_HOST|DOKPLOY_DOMAIN|NEXTAUTH_URL|CANONICAL_HOST|"
    r"CANONICAL_URL|VITE_PUBLIC_HOST|NUXT_PUBLIC_SITE_URL)\s*=\s*(.+)$",
    re.IGNORECASE,
)
ENV_HOST_SKIP_PREFIX = re.compile(
    r"^(?:MYSQL|MARIADB|POSTGRES|PG|DB|DATABASE|REDIS|SMTP|MAIL|MEMCACHED|MONGO|RABBIT|"
    r"KAFKA|ELASTIC|CLICKHOUSE|MINIO|S3)_",
    re.IGNORECASE,
)
GENERIC_BACKEND_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "web", "app", "frontend", "backend", "nginx", "proxy"}
TRAEFIK_API_SH = r"""
fetch() {
  u="$1"
  if command -v wget >/dev/null 2>&1; then
    wget -qO- --timeout=5 "$u" && return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 "$u" && return 0
  fi
  return 1
}
fetch http://127.0.0.1:8080/api/http/routers || fetch http://127.0.0.1:8080/api/rawdata
"""
TRAEFIK_FILES_SH = r"""
for dir in /etc/dokploy/traefik/dynamic /etc/dokploy/traefik /etc/traefik/dynamic /etc/traefik /etc/traefik/conf.d; do
  [ -d "$dir" ] || continue
  find "$dir" -maxdepth 4 -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.toml' -o -name '*.json' \) 2>/dev/null | while IFS= read -r f; do
    echo "# configuration file ${f}:"
    cat "$f" 2>/dev/null || true
    echo
  done
done
"""
ACME_FILES_SH = r"""
for f in /etc/dokploy/traefik/acme.json /etc/traefik/acme.json /acme.json /data/acme.json; do
  if [ -f "$f" ]; then
    echo "# configuration file ${f}:"
    cat "$f" 2>/dev/null || true
    echo
  fi
done
"""
APACHE_SCAN_ROOTS = (
    "/etc/apache2/sites-enabled",
    "/etc/apache2/sites-available",
    "/etc/httpd/conf.d",
    "/etc/httpd/conf",
)
COMPOSE_NAME_HINTS = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
CLASSIFICATION_ACTIVE = "ACTIVE WEBSITE"
CLASSIFICATION_MIGRATED = "MIGRATED WEBSITE"
CLASSIFICATION_LEGACY = "LEGACY INSTALLATION"
CLASSIFICATION_RECOVERY = "RECOVERY DATA"
CLASSIFICATION_SYSTEM = "SYSTEM DATA"
CLASSIFICATION_EXCLUDED = "INTENTIONALLY EXCLUDED"
CLASSIFICATION_UNRESOLVED = "UNRESOLVED — REQUIRES REVIEW"
ROUTING_ENV_KEYS = frozenset({"VIRTUAL_HOST", "DEFAULT_HOST"})
ADVERTISED_ENV_KEYS = frozenset(
    {
        "PUBLIC_HOST",
        "PUBLIC_HOSTNAME",
        "SITE_URL",
        "APP_URL",
        "PUBLIC_URL",
        "CANONICAL_HOST",
        "CANONICAL_URL",
        "NEXTAUTH_URL",
        "BASE_URL",
    }
)
HOSTNAME_ROLE_ROUTING = "application-hostname"
HOSTNAME_ROLE_ADVERTISED = "advertised-public-host"
HOSTNAME_ROLE_ALIAS = "public-alias"
HOSTNAME_ROLE_INFRASTRUCTURE = "infrastructure"
HOSTNAME_ROLE_EXTERNAL = "external-dependency"
HOSTNAME_ROLE_PLACEHOLDER = "placeholder-example"
HOSTNAME_ROLE_CONFIG = "config-reference"
VOLUME_BACKUP_SQL = "BACKUP_AS_SQL_DUMP"
VOLUME_BACKUP_FILES = "BACKUP_AS_FILE_DATA"
VOLUME_BACKUP_INFRA = "BACKUP_AS_INFRASTRUCTURE"
VOLUME_BACKUP_EXCLUDED = "INTENTIONALLY_EXCLUDED_WITH_REASON"
VOLUME_BACKUP_UNRESOLVED = "UNRESOLVED_REQUIRES_REVIEW"


def _strip_value(raw: str) -> str:
    value = (raw or "").strip()
    if ";" in value and not (value.startswith('"') or value.startswith("'")):
        value = value.split(";", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def safe_unix(path: str) -> str:
    cleaned = (path or "").strip()
    if not is_safe_unix_syntax(cleaned):
        return ""
    return cleaned.rstrip("/") or "/"


def is_excluded_path(path: str) -> bool:
    cleaned = (path or "").rstrip("/")
    if not cleaned:
        return True
    if is_named_volume_data_path(cleaned):
        return False
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


def looks_like_hostname(value: str) -> bool:
    cleaned = (value or "").strip().rstrip(".").lower()
    if not cleaned or cleaned in CATCHALL_HOSTS:
        return False
    if "*" in cleaned or "{" in cleaned or "/" in cleaned or " " in cleaned or ":" in cleaned:
        return False
    if cleaned.startswith("$"):
        return False
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", cleaned):
        return False
    return bool(HOSTNAME_TOKEN.match(cleaned))


def _split_host_list(text: str) -> list[str]:
    names: list[str] = []
    for item in re.split(r"[\s,;]+", (text or "").strip()):
        cleaned = item.strip().strip("'\"`").rstrip(".")
        if looks_like_hostname(cleaned):
            names.append(cleaned)
    return names


def hostnames_from_traefik_rule(text: str) -> list[str]:
    names: list[str] = []
    for call in TRAEFIK_HOST_CALL.finditer(text or ""):
        inner = call.group(1) or ""
        quoted = QUOTED_TOKEN.findall(inner)
        tokens = quoted or re.split(r"[\s,]+", inner)
        for token in tokens:
            cleaned = str(token).strip().strip("'\"`").rstrip(".")
            if looks_like_hostname(cleaned):
                names.append(cleaned)
    return list(dict.fromkeys(names))


def is_infrastructure_hostname(value: str) -> bool:
    cleaned = (value or "").strip().rstrip(".").lower()
    if not cleaned:
        return False
    if cleaned in CATCHALL_HOSTS or cleaned in {"host.docker.internal"}:
        return True
    if cleaned.endswith(".localhost") or cleaned.endswith(".local") or cleaned.endswith(".internal"):
        return True
    if ".docker.localhost" in cleaned:
        return True
    return False


def env_key_hostname_role(key: str) -> str:
    key_u = str(key or "").strip().upper()
    if not key_u:
        return "ignore"
    if ENV_HOST_SKIP_PREFIX.match(key_u):
        return "ignore"
    if "CORS" in key_u:
        return HOSTNAME_ROLE_CONFIG
    if "API" in key_u and any(token in key_u for token in ("URL", "HOST", "BASE", "ENDPOINT", "URI")):
        return HOSTNAME_ROLE_EXTERNAL
    if key_u in ROUTING_ENV_KEYS:
        return HOSTNAME_ROLE_ROUTING
    if key_u in ADVERTISED_ENV_KEYS:
        return HOSTNAME_ROLE_ADVERTISED
    return "ignore"


def hostnames_from_labels_and_env(labels: dict[str, Any] | None, env_items: list[str] | None = None) -> list[str]:
    """Public routing hostnames only (Traefik Host(), VIRTUAL_HOST, Dokploy domain labels).

    CORS, API URLs, image documentation URLs, and other config strings are not websites.
    """
    names: list[str] = []
    for key, value in (labels or {}).items():
        key_l = str(key).lower()
        text = str(value or "")
        if not text:
            continue
        if "traefik" in key_l and "rule" in key_l:
            names.extend(hostnames_from_traefik_rule(text))
            continue
        if "virtual_host" in key_l:
            names.extend(_split_host_list(text))
            continue
        if "dokploy" in key_l and ("domain" in key_l or key_l.endswith(".host")):
            names.extend(_split_host_list(text))
            continue
        if "caddy" in key_l:
            names.extend(_split_host_list(text))
            names.extend(hostnames_from_traefik_rule(text))
            continue
        if "Host(" in text or "Host `" in text:
            names.extend(hostnames_from_traefik_rule(text))
    for item in env_items or []:
        parsed = parse_env_hostname_assignment(str(item))
        if parsed and parsed["role"] == HOSTNAME_ROLE_ROUTING:
            names.extend(parsed["hostnames"])
    return [name for name in dict.fromkeys(names) if not is_infrastructure_hostname(name)]


def _hostname_roles_from_containers(containers: list[dict[str, Any]]) -> tuple[dict[str, set[str]], set[str]]:
    """Inspect-derived roles and advertised PUBLIC_HOST values, keyed by hostname."""
    roles: dict[str, set[str]] = {}
    advertised: set[str] = set()
    for inspect in containers or []:
        summary = _docker_summary(inspect)
        for name in summary.get("advertised_hostnames") or []:
            if looks_like_hostname(str(name)):
                advertised.add(str(name).lower())
        for rec in summary.get("hostname_mentions") or []:
            host = str(rec.get("hostname") or "").lower()
            role = str(rec.get("role") or "")
            if host and role:
                roles.setdefault(host, set()).add(role)
    return roles, advertised


def _config_only_hostname(hostname: str, roles_by_host: dict[str, set[str]], advertised: set[str]) -> bool:
    """True when the string is a config/API/image URL, not an advertised public host."""
    key = str(hostname or "").lower()
    if not key or key in advertised:
        return False
    found = roles_by_host.get(key) or set()
    config_roles = {HOSTNAME_ROLE_EXTERNAL, HOSTNAME_ROLE_PLACEHOLDER, HOSTNAME_ROLE_CONFIG}
    return bool(found & config_roles) and HOSTNAME_ROLE_ROUTING not in found


def parse_env_hostname_assignment(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip().lstrip("- ").strip()
    if not text or text.startswith("#"):
        return None
    if "=" in text.split(":", 1)[0]:
        key, _, value = text.partition("=")
    elif ":" in text:
        key, _, value = text.partition(":")
    else:
        return None
    key = key.strip()
    value = value.strip().strip("'\"")
    if not key or not value:
        return None
    role = env_key_hostname_role(key)
    if role == "ignore":
        return None
    names: list[str] = []
    for token in re.findall(r"https?://([^/\s'\"\],]+)", value, re.IGNORECASE):
        host = token.split(":")[0].strip().strip(".")
        if looks_like_hostname(host):
            names.append(host.lower())
    names.extend(_split_host_list(value.replace("https://", " ").replace("http://", " ")))
    names = list(dict.fromkeys(names))
    if not names:
        return None
    return {"key": key, "value": value[:240], "role": role, "hostnames": names}


def collect_hostname_mentions(
    *,
    labels: dict[str, Any] | None = None,
    env_items: list[str] | None = None,
    container: str = "",
    source: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in (labels or {}).items():
        key_l = str(key).lower()
        text = str(value or "")
        if not text:
            continue
        names: list[str] = []
        role = HOSTNAME_ROLE_PLACEHOLDER
        routing = False
        if "traefik" in key_l and "rule" in key_l:
            names = hostnames_from_traefik_rule(text)
            role = HOSTNAME_ROLE_ROUTING
            routing = True
        elif "virtual_host" in key_l or ("dokploy" in key_l and "domain" in key_l) or "caddy" in key_l:
            names = _split_host_list(text) + hostnames_from_traefik_rule(text)
            role = HOSTNAME_ROLE_ROUTING
            routing = True
        elif "Host(" in text:
            names = hostnames_from_traefik_rule(text)
            role = HOSTNAME_ROLE_ROUTING
            routing = True
        else:
            extracted = []
            for token in re.findall(r"https?://([^/\s'\"\],]+)", text, re.IGNORECASE):
                host = token.split(":")[0].strip().strip(".")
                if looks_like_hostname(host):
                    extracted.append(host.lower())
            names = list(dict.fromkeys(extracted))
            if "opencontainers" in key_l or "label-schema" in key_l or key_l.endswith(".url"):
                role = HOSTNAME_ROLE_PLACEHOLDER
            else:
                role = HOSTNAME_ROLE_CONFIG
        for name in names:
            item_role = HOSTNAME_ROLE_INFRASTRUCTURE if is_infrastructure_hostname(name) else role
            rows.append(
                {
                    "hostname": name,
                    "role": item_role,
                    "routing": routing and item_role == HOSTNAME_ROLE_ROUTING,
                    "source": source or "docker label",
                    "container": container,
                    "key": str(key),
                    "evidence": text[:240],
                }
            )
    for item in env_items or []:
        parsed = parse_env_hostname_assignment(str(item))
        if not parsed:
            continue
        for name in parsed["hostnames"]:
            item_role = HOSTNAME_ROLE_INFRASTRUCTURE if is_infrastructure_hostname(name) else parsed["role"]
            rows.append(
                {
                    "hostname": name,
                    "role": item_role,
                    "routing": item_role == HOSTNAME_ROLE_ROUTING,
                    "source": source or "docker env",
                    "container": container,
                    "key": parsed["key"],
                    "evidence": f"{parsed['key']}={parsed['value']}",
                }
            )
    return rows


def hostnames_from_env_assignment(raw: str) -> list[str]:
    parsed = parse_env_hostname_assignment(raw)
    if not parsed or parsed["role"] not in {HOSTNAME_ROLE_ROUTING, HOSTNAME_ROLE_ADVERTISED}:
        return []
    return [name for name in parsed["hostnames"] if not is_infrastructure_hostname(name)]


def hostnames_from_compose_text(text: str) -> list[str]:
    names = hostnames_from_traefik_rule(text or "")
    for line in (text or "").splitlines():
        parsed = parse_env_hostname_assignment(line)
        if parsed and parsed["role"] == HOSTNAME_ROLE_ROUTING:
            names.extend(parsed["hostnames"])
    return [name for name in dict.fromkeys(names) if not is_infrastructure_hostname(name)]


def backend_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for match in BACKEND_URL.finditer(text or ""):
        raw = match.group(1) or match.group(2) or ""
        cleaned = raw.strip().rstrip("/")
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            urls.append(cleaned)
    return list(dict.fromkeys(urls))


def is_live_proxy_config_path(path: str) -> bool:
    lower = (path or "").replace("\\", "/").lower()
    if any(hint in lower for hint in MIGRATION_PATH_HINTS):
        return False
    return any(hint in lower for hint in LIVE_PROXY_PATH_HINTS)


def is_migration_config_path(path: str) -> bool:
    lower = (path or "").replace("\\", "/").lower()
    return any(hint in lower for hint in MIGRATION_PATH_HINTS)


def hostnames_from_acme_json(text: str) -> list[str]:
    """Certificate domains from Traefik/Let's Encrypt acme.json. Never uses a hard-coded site list."""
    names: list[str] = []
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        for match in re.finditer(r'"(?:main|sans?)"\s*:\s*"([^"]+)"', raw, re.IGNORECASE):
            if looks_like_hostname(match.group(1)):
                names.append(match.group(1).lower())
        return list(dict.fromkeys(names))

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            main = node.get("main") or node.get("Main")
            if looks_like_hostname(str(main or "")):
                names.append(str(main).lower())
            sans = node.get("sans") or node.get("SANs") or node.get("Sans") or []
            if isinstance(sans, str):
                sans = [sans]
            for item in sans if isinstance(sans, list) else []:
                if looks_like_hostname(str(item)):
                    names.append(str(item).lower())
            domain = node.get("domain") or node.get("Domain")
            if isinstance(domain, dict):
                walk(domain)
            elif looks_like_hostname(str(domain or "")):
                names.append(str(domain).lower())
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(names))


def parse_traefik_file(text: str, source_file: str = "") -> dict[str, Any]:
    """Parse one Traefik/Dokploy YAML or JSON file into Host() routes and backends."""
    body = text or ""
    hosts = hostnames_from_traefik_rule(body)
    if not hosts:
        hosts = hostnames_from_compose_text(body)
    urls = backend_urls_from_text(body)
    tls = bool(
        re.search(r"(?im)^\s*tls\s*:", body)
        or re.search(r'(?i)"tls"\s*:', body)
        or "certresolver" in body.lower()
        or "letsencrypt" in body.lower()
    )
    return {
        "source_file": source_file,
        "hostnames": list(dict.fromkeys(hosts)),
        "backend_urls": urls,
        "tls": tls,
        "live_proxy": is_live_proxy_config_path(source_file) or source_file.startswith("traefik-api:") or source_file.startswith("docker-exec:"),
        "migration": is_migration_config_path(source_file),
    }


def parse_traefik_api_payload(text: str, source: str = "") -> list[dict[str, Any]]:
    """Parse Traefik /api/http/routers or /api/rawdata JSON into Host() routes."""
    raw = (text or "").strip()
    if not raw or raw[0] not in "{[":
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    routers: list[Any] = []
    services: dict[str, list[str]] = {}
    if isinstance(payload, list):
        routers = payload
    elif isinstance(payload, dict):
        maybe_routers = payload.get("routers") or payload.get("http", {}).get("routers") if isinstance(payload.get("http"), dict) else payload.get("routers")
        maybe_services = payload.get("services") or (payload.get("http", {}).get("services") if isinstance(payload.get("http"), dict) else None)
        if isinstance(maybe_routers, list):
            routers = maybe_routers
        elif isinstance(maybe_routers, dict):
            routers = [{"name": key, **(value if isinstance(value, dict) else {})} for key, value in maybe_routers.items()]
        if isinstance(maybe_services, dict):
            for key, value in maybe_services.items():
                urls = _backend_urls_from_service(value)
                if urls:
                    services[str(key).split("@", 1)[0].lower()] = urls
        elif isinstance(maybe_services, list):
            for item in maybe_services:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").split("@", 1)[0].lower()
                urls = _backend_urls_from_service(item)
                if name and urls:
                    services[name] = urls
    routes: list[dict[str, Any]] = []
    for item in routers:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "enabled").lower()
        if status and status not in {"enabled", "ok", ""}:
            continue
        rule = str(item.get("rule") or "")
        hosts = hostnames_from_traefik_rule(rule)
        if not hosts:
            continue
        service = str(item.get("service") or "").split("@", 1)[0]
        urls = list(services.get(service.lower()) or [])
        tls = bool(item.get("tls"))
        routes.append(
            {
                "source_file": source or "traefik-api",
                "hostnames": hosts,
                "backend_urls": urls,
                "service": service,
                "tls": tls,
                "live_proxy": True,
                "migration": False,
            }
        )
    return routes


def _backend_urls_from_service(node: Any) -> list[str]:
    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            url = value.get("url") or value.get("URL")
            if isinstance(url, str) and url.startswith("http"):
                urls.append(url.rstrip("/"))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return list(dict.fromkeys(urls))


def parse_marked_config_dump(text: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    current_name = ""
    current_lines: list[str] = []
    for line in (text or "").splitlines():
        match = FILE_MARKER.match(line)
        if match:
            if current_name:
                files.append((current_name, "\n".join(current_lines)))
            current_name = match.group(1).strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_name:
        files.append((current_name, "\n".join(current_lines)))
    return files


def _looks_like_proxy_container(summary: dict[str, Any]) -> bool:
    blob = " ".join(
        str(summary.get(key) or "")
        for key in ("name", "image", "compose_service", "compose_project")
    ).lower()
    if "traefik" in blob:
        return True
    dests = " ".join(str(mount.get("destination") or "") for mount in (summary.get("mounts") or [])).lower()
    if "traefik" in dests:
        return True
    if "dokploy" in blob and any(token in blob for token in ("proxy", "traefik")):
        return True
    return False


def _looks_like_infrastructure_container(summary: dict[str, Any]) -> bool:
    """Dokploy/Traefik management-plane containers are not public websites."""
    if _looks_like_proxy_container(summary):
        return True
    name = str(summary.get("name") or "").lower()
    image = str(summary.get("image") or "").lower()
    service = str(summary.get("compose_service") or "").lower()
    project = str(summary.get("compose_project") or "").lower()
    if service in {"dokploy", "dokploy-traefik", "dokploy-postgres", "dokploy-redis", "dokploy-db"}:
        return True
    if "dokploy/dokploy" in image or image.startswith("dokploy:"):
        return True
    if project == "dokploy" and not [
        h for h in (summary.get("hostnames") or []) if looks_like_hostname(str(h)) and not is_infrastructure_hostname(str(h))
    ]:
        return True
    if name in {"dokploy", "dokploy-postgres", "dokploy-redis"} or name.startswith("dokploy-"):
        return True
    return False


def _docker_exec_text(run: Callable, container: str, script: str) -> str:
    try:
        name = require_docker_name(container)
    except ValueError:
        return ""
    try:
        result = run(["docker", "exec", name, "sh", "-c", script], timeout=30)
    except Exception:
        return ""
    if getattr(result, "returncode", 1) != 0:
        return ""
    return getattr(result, "stdout", "") or ""


def collect_proxy_routes_from_docker(
    run: Callable | None,
    containers: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Read live Traefik Host() routes from the reverse-proxy container when host YAML is unreadable."""
    if run is None:
        return []
    routes: list[dict[str, Any]] = []
    for inspect in containers or []:
        summary = _docker_summary(inspect)
        if summary.get("running") is False:
            continue
        if not _looks_like_proxy_container(summary):
            continue
        name = str(summary.get("name") or "")
        api_text = _docker_exec_text(run, name, TRAEFIK_API_SH)
        if api_text.strip():
            parsed = parse_traefik_api_payload(api_text, f"traefik-api:{name}")
            if parsed:
                routes.extend(parsed)
                continue
        dump = _docker_exec_text(run, name, TRAEFIK_FILES_SH)
        for path, body in parse_marked_config_dump(dump):
            if "acme.json" in path.lower():
                continue
            parsed = parse_traefik_file(body, f"docker-exec:{name}:{path}")
            if parsed.get("hostnames"):
                parsed["live_proxy"] = True
                parsed["migration"] = False
                routes.append(parsed)
    return _dedupe_proxy_routes(routes)


def collect_acme_from_docker(
    run: Callable | None,
    containers: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    if run is None:
        return {}
    found: dict[str, list[str]] = {}
    for inspect in containers or []:
        summary = _docker_summary(inspect)
        if summary.get("running") is False or not _looks_like_proxy_container(summary):
            continue
        name = str(summary.get("name") or "")
        dump = _docker_exec_text(run, name, ACME_FILES_SH)
        for path, body in parse_marked_config_dump(dump):
            names = hostnames_from_acme_json(body)
            if names:
                found[f"docker-exec:{name}:{path}"] = names
    return found


def _dedupe_proxy_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    unique: list[dict[str, Any]] = []
    for route in routes:
        key = tuple(sorted(str(h).lower() for h in (route.get("hostnames") or []) if h))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique


def _ssl_mechanism(certificate: str, *, https: bool, docker: dict[str, Any] | None = None) -> str:
    cert = (certificate or "").lower()
    if "letsencrypt" in cert:
        return "letsencrypt"
    if cert:
        return "nginx-certificate-file"
    labels = {}
    if docker:
        labels = docker.get("labels") if isinstance(docker.get("labels"), dict) else {}
        blob = " ".join(f"{k}={v}" for k, v in labels.items())
        if "traefik" in blob.lower() and ("tls" in blob.lower() or hostnames_from_labels_and_env(labels)):
            return "traefik"
        if docker.get("hostnames") and https:
            return "traefik"
    if https:
        return "https-listen-without-certificate-path"
    return "none"


def _ssl_restore_procedure(mechanism: str, *, acme_file: str = "", certificates: list[str] | None = None, keys: list[str] | None = None, extra_source_file: str = "") -> str:
    mechanism = (mechanism or "none").lower()
    certs = [c for c in (certificates or []) if c]
    key_files = [c for c in (keys or []) if c]
    if mechanism in {"letsencrypt", "certbot"} or any("letsencrypt" in c.lower() for c in certs):
        live = certs[0] if certs else "/etc/letsencrypt/live/<hostname>/fullchain.pem"
        key = key_files[0] if key_files else "/etc/letsencrypt/live/<hostname>/privkey.pem"
        return (
            f"Nginx/Certbot Let's Encrypt. Persistent store is /etc/letsencrypt "
            f"(certificate {live}, private key {key}). Copy those files into BACKUPS/<site>/ssl/ "
            "and restore the same paths plus the matching Nginx server block before reloading Nginx."
        )
    if mechanism in {"traefik", "traefik-acme"} or acme_file:
        store = acme_file or extra_source_file or "/etc/dokploy/traefik/acme.json"
        route = extra_source_file or "/etc/dokploy/traefik/dynamic/<app>.yml"
        return (
            f"Traefik-managed TLS. Certificates/private keys live in ACME JSON {store}. "
            f"Copy {store} into BACKUPS/<site>/ssl/ and the Host() route file {route} into "
            "BACKUPS/<site>/nginx/. Restore both into Traefik/Dokploy without overwriting unrelated routers; "
            "Traefik reloads ACME material from the restored JSON."
        )
    if certs or key_files:
        return (
            f"Nginx certificate files {', '.join(certs) or '(unknown)'} and keys "
            f"{', '.join(key_files) or '(unknown)'}. Copy those paths into BACKUPS/<site>/ssl/ "
            "and restore them to the same filesystem locations."
        )
    if mechanism == "https-listen-without-certificate-path":
        return (
            "HTTPS is advertised but certificate/key storage was not found. "
            "Do not mark restore ready until ACME JSON or certificate files are located."
        )
    return "No HTTPS certificate storage was identified for this application."


def _ssl_record(
    *,
    https: bool,
    mechanism: str,
    certificates: list[str] | None = None,
    keys: list[str] | None = None,
    acme_file: str = "",
    extra_source_file: str = "",
    docker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    certs = list(dict.fromkeys(certificates or []))
    key_files = list(dict.fromkeys(keys or []))
    storage = list(dict.fromkeys([*certs, *key_files, acme_file] if acme_file else [*certs, *key_files]))
    volume = ""
    for mount in (docker or {}).get("mounts") or []:
        dest = str(mount.get("destination") or "").lower()
        source = str(mount.get("source") or "")
        if "acme" in dest or "letsencrypt" in dest or dest.endswith("/traefik"):
            volume = source
            if source and source not in storage:
                storage.append(source)
    return {
        "https": https,
        "mechanism": mechanism,
        "certificate": certs,
        "certificate_key": key_files,
        "acme_file": acme_file,
        "storage_paths": storage,
        "volume": volume,
        "backup_treatment": _ssl_restore_procedure(
            mechanism,
            acme_file=acme_file,
            certificates=certs,
            keys=key_files,
            extra_source_file=extra_source_file,
        ),
        "restore_procedure": _ssl_restore_procedure(
            mechanism,
            acme_file=acme_file,
            certificates=certs,
            keys=key_files,
            extra_source_file=extra_source_file,
        ),
    }


def _volume_purpose(destination: str, *, named_volume: str = "", container: str = "") -> str:
    dest = (destination or "").lower().rstrip("/")
    name = (named_volume or "").lower()
    cname = (container or "").lower()
    if dest.endswith("/.docker") or dest.endswith("/.docker/config.json") or dest == "/root/.docker" or "/.docker/" in dest + "/":
        return "infrastructure"
    if name == "dokploy" or (name.startswith("dokploy") and ("docker" in dest or dest.endswith("/.docker"))):
        return "infrastructure"
    if "traefik" in cname and ("acme" in dest or dest.endswith("/letsencrypt") or "traefik" in dest):
        return "infrastructure"
    if any(dest == hint.rstrip("/") or dest.startswith(hint.rstrip("/") + "/") for hint in DB_VOLUME_DEST_HINTS):
        return "database-data"
    if "postgres" in dest or "mysql" in dest or "mariadb" in dest:
        return "database-data"
    if "postgres" in name or "mysql" in name or "mariadb" in name or name.endswith("_pgdata") or name.endswith("-pgdata"):
        return "database-data"
    if any(dest == hint.rstrip("/") or dest.startswith(hint.rstrip("/") + "/") for hint in CACHE_VOLUME_DEST_HINTS):
        return "cache"
    if "redis" in dest or "redis" in name or "cache" in name:
        return "cache"
    return "application-data"


def _volume_backup_status(purpose: str) -> str:
    if purpose == "database-data":
        return VOLUME_BACKUP_SQL
    if purpose == "cache":
        return VOLUME_BACKUP_EXCLUDED
    if purpose == "infrastructure":
        return VOLUME_BACKUP_INFRA
    if purpose == "application-data":
        return VOLUME_BACKUP_FILES
    return VOLUME_BACKUP_UNRESOLVED


def _collect_ssl_paths(items: list[tuple[str, Any]]) -> tuple[list[str], list[str]]:
    certs: list[str] = []
    keys: list[str] = []

    def walk(nodes: list[tuple[str, Any]]) -> None:
        for kind, key_or_header, extra in nodes:
            if kind == "directive":
                key = str(key_or_header)
                value = _unquote(str(extra))
                if key == "ssl_certificate":
                    certs.append(value)
                elif key == "ssl_certificate_key":
                    keys.append(value)
                continue
            if kind == "block":
                walk(list(extra or []))

    walk(items)
    return list(dict.fromkeys(certs)), list(dict.fromkeys(keys))


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
    ssl_certs, ssl_keys = _collect_ssl_paths(body)
    if ssl_certs:
        ssl = True
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
        "ssl_certificate": ssl_certs,
        "ssl_certificate_key": ssl_keys,
        "ssl_mechanism": _ssl_mechanism(ssl_certs[0] if ssl_certs else "", https=ssl),
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
                "ssl_certificate": list(block.get("ssl_certificate") or []),
                "ssl_certificate_key": list(block.get("ssl_certificate_key") or []),
                "ssl_mechanism": block.get("ssl_mechanism") or "",
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
    try:
        if not path.is_dir():
            return 0, 0
    except OSError:
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


SS_LISTEN_LINE = re.compile(
    r"^(?:LISTEN|UNCONN)\s+\S+\s+\S+\s+(\S+?):(\d+)\s+\S+(?:\s+(.*))?$"
)
SS_PROC = re.compile(r'pid=(\d+)')
SS_COMM = re.compile(r'\(\("([^"]+)"')
CGROUP_DOCKER = re.compile(r'(?:docker[-/])([0-9a-f]{12,64})(?:\.scope)?')
LOCAL_BACKEND_HOSTS = {"127.0.0.1", "0.0.0.0", "::1", "::", "*", "localhost", "[::1]", "[::]"}


def _run_text(run: Callable, cmd: list[str], timeout: int = 10) -> str:
    """Run a read-only command through the injected runner and return stdout."""
    try:
        result = run(cmd, timeout=timeout)
    except Exception:  # noqa: BLE001
        return ""
    if getattr(result, "returncode", 1) != 0:
        return getattr(result, "stdout", "") or ""
    return getattr(result, "stdout", "") or ""


def _container_id_from_cgroup(text: str) -> str:
    for line in (text or "").splitlines():
        match = CGROUP_DOCKER.search(line.strip())
        if match:
            return match.group(1)
    return ""


def resolve_backend_owners(run: Callable) -> dict[str, dict[str, Any]]:
    """Map each listening TCP port to the process/container that owns it.

    This is how ``proxy_pass http://127.0.0.1:8084`` is traced to the real
    application when the container uses host networking, an unusual publish
    mapping, or is a plain host process (systemd unit / interpreter). It never
    stops or modifies anything: it only reads ``ss`` output and ``/proc``.
    """
    owners: dict[str, dict[str, Any]] = {}
    listing = _run_text(run, ["ss", "-ltnpH"], timeout=10)
    if not listing.strip():
        listing = _run_text(run, ["ss", "-ltnp"], timeout=10)
    for raw in listing.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("state"):
            continue
        match = SS_LISTEN_LINE.match(line)
        if not match:
            continue
        port = match.group(2)
        process = match.group(3) or ""
        pid_match = SS_PROC.search(process)
        if not pid_match:
            # Keep the port known even without a pid so callers can note it.
            owners.setdefault(port, {"port": port})
            continue
        pid = pid_match.group(1)
        comm_match = SS_COMM.search(process)
        comm = comm_match.group(1) if comm_match else ""
        existing = owners.get(port)
        # Prefer a real application process over docker-proxy/systemd shims.
        if existing and existing.get("container_id") and comm in {"docker-proxy", "systemd"}:
            continue
        cgroup = _run_text(run, ["cat", f"/proc/{pid}/cgroup"], timeout=5)
        container_id = _container_id_from_cgroup(cgroup)
        cwd = _run_text(run, ["readlink", "-f", f"/proc/{pid}/cwd"], timeout=5).strip()
        exe = _run_text(run, ["readlink", "-f", f"/proc/{pid}/exe"], timeout=5).strip()
        unit = _run_text(run, ["ps", "-o", "unit=", "-p", pid], timeout=5).strip()
        owners[port] = {
            "port": port,
            "pid": pid,
            "comm": comm,
            "container_id": container_id,
            "cwd": cwd if cwd and not is_excluded_path(cwd) else "",
            "exe": exe,
            "unit": unit if unit and unit not in {"-", "0"} else "",
        }
    return owners


def _local_backend_ports(proxy_passes: list[str]) -> list[str]:
    ports: list[str] = []
    for proxy in proxy_passes or []:
        parsed = parse_proxy(proxy)
        host = (parsed.get("host") or "").lower().strip("[]")
        port = parsed.get("port") or ""
        if host in LOCAL_BACKEND_HOSTS and port and port not in ports:
            ports.append(port)
    return ports


def _match_docker_by_backend_owner(
    proxy_passes: list[str],
    summaries: list[dict[str, Any]],
    backend_owners: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Match a localhost backend port to the container that actually serves it."""
    if not backend_owners:
        return None
    for port in _local_backend_ports(proxy_passes):
        owner = backend_owners.get(port)
        if not owner:
            continue
        container_id = str(owner.get("container_id") or "")
        if not container_id:
            continue
        for item in summaries:
            summary_id = str(item.get("id") or "")
            if summary_id and (container_id.startswith(summary_id) or summary_id.startswith(container_id)):
                if not _looks_like_infrastructure_container(item):
                    return dict(item)
    return None


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
    env_items = [str(item) for item in (config.get("Env") or [])]
    for item in env_items:
        if "=" in item:
            key, value = item.split("=", 1)
            if key.lower() in SECRET_KEYS or "password" in key.lower() or "secret" in key.lower():
                continue
            env_map[key] = value
    safe_labels = {
        str(key): str(value)
        for key, value in labels.items()
        if not any(token in str(key).lower() for token in SECRET_KEYS)
        and "password" not in str(key).lower()
    }
    state = inspect.get("State") if isinstance(inspect.get("State"), dict) else {}
    running = bool(state.get("Running")) if state else True
    routing_hosts = hostnames_from_labels_and_env(labels, env_items)
    advertised_hosts: list[str] = []
    for item in env_items:
        parsed = parse_env_hostname_assignment(str(item))
        if parsed and parsed["role"] == HOSTNAME_ROLE_ADVERTISED:
            advertised_hosts.extend(name for name in parsed["hostnames"] if not is_infrastructure_hostname(name))
    mentions = collect_hostname_mentions(
        labels=labels,
        env_items=env_items,
        container=str((inspect.get("Name") or "").lstrip("/")),
        source="docker inspect",
    )
    network_aliases = _network_aliases(inspect)
    compose_files = labels.get("com.docker.compose.project.config_files") or ""
    return {
        "id": str(inspect.get("Id") or "")[:12],
        "name": str((inspect.get("Name") or "").lstrip("/")),
        "image": str(config.get("Image") or ""),
        "running": running,
        "labels": safe_labels,
        "hostnames": list(dict.fromkeys(routing_hosts)),
        "advertised_hostnames": list(dict.fromkeys(advertised_hosts)),
        "hostname_mentions": mentions,
        "network_aliases": network_aliases,
        "compose_project": labels.get("com.docker.compose.project") or "",
        "compose_service": labels.get("com.docker.compose.service") or "",
        "compose_workdir": labels.get("com.docker.compose.project.working_dir") or "",
        "compose_files": compose_files,
        "published_ports": published,
        "mounts": mounts,
        "postgres_db": env_map.get("POSTGRES_DB") or "",
        "postgres_user": env_map.get("POSTGRES_USER") or "",
        "mysql_database": env_map.get("MYSQL_DATABASE") or env_map.get("MARIADB_DATABASE"),
        "traefik_tls": any("traefik" in str(key).lower() and "tls" in str(key).lower() for key in labels),
    }


def _network_aliases(inspect: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    networks = (inspect.get("NetworkSettings") or {}).get("Networks") or {}
    if isinstance(networks, dict):
        for net in networks.values():
            if not isinstance(net, dict):
                continue
            for item in net.get("Aliases") or []:
                cleaned = str(item or "").strip()
                if cleaned:
                    aliases.append(cleaned)
    return list(dict.fromkeys(aliases))


def _public_docker(docker: dict[str, Any] | None) -> dict[str, Any] | None:
    if not docker:
        return None
    mounts = []
    for mount in docker.get("mounts") or []:
        if not isinstance(mount, dict):
            continue
        mounts.append(
            {
                "type": mount.get("type") or "",
                "source": mount.get("source") or "",
                "destination": mount.get("destination") or "",
                "named_volume": bool(mount.get("named_volume")),
                "purpose": _volume_purpose(str(mount.get("destination") or ""), named_volume=str(mount.get("source") or "")),
            }
        )
    return {
        "compose_project": docker.get("compose_project") or "",
        "compose_file": docker.get("compose_files") or docker.get("compose_file") or "",
        "compose_files": docker.get("compose_files") or docker.get("compose_file") or "",
        "service": docker.get("compose_service") or docker.get("service") or "",
        "container": docker.get("name") or docker.get("container") or "",
        "image": docker.get("image") or "",
        "workdir": docker.get("compose_workdir") or docker.get("workdir") or "",
        "mysql_database": docker.get("mysql_database") or "",
        "postgres_db": docker.get("postgres_db") or "",
        "postgres_user": docker.get("postgres_user") or "",
        "db_container": docker.get("db_container") or "",
        "running": docker.get("running") if docker.get("running") is not None else True,
        "hostnames": list(docker.get("hostnames") or []),
        "advertised_hostnames": list(docker.get("advertised_hostnames") or []),
        "published_ports": list(docker.get("published_ports") or []),
        "mounts": mounts,
        "traefik_tls": bool(docker.get("traefik_tls")),
    }


def inferred_db_container(docker: dict[str, Any] | None) -> str:
    """Dokploy/Compose db containers are named {compose_project}-db-1."""
    docker = docker if isinstance(docker, dict) else {}
    container = str(docker.get("db_container") or "").strip().lstrip("/")
    if container:
        return container
    project = str(docker.get("compose_project") or "").strip()
    if project:
        return f"{project}-db-1"
    return ""


def _looks_like_db_container(item: dict[str, Any]) -> bool:
    if item.get("hostnames"):
        return False
    name = str(item.get("name") or "").lower()
    service = str(item.get("compose_service") or "").lower()
    blob = f"{name} {service}"
    if any(token in blob for token in ("-db-", "_db_", "-db.", "mariadb", "mysql", "postgres")):
        return True
    if service in {"db", "database", "mariadb", "mysql", "postgres"}:
        return True
    if (item.get("mysql_database") or item.get("postgres_db")) and not item.get("published_ports"):
        return True
    return name.endswith("-db") or name.endswith("-db-1")


def _match_docker(
    proxy_passes: list[str],
    containers: list[dict[str, Any]],
    hostnames: list[str] | None = None,
    backend_owners: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    summaries = [_docker_summary(item) for item in containers]
    matched = _match_docker_summary(proxy_passes, summaries)
    if not matched:
        matched = _match_docker_by_backend_owner(proxy_passes, summaries, backend_owners)
    if not matched:
        matched = _match_docker_by_hostname(hostnames or [], summaries)
    return _enrich_docker_from_compose(matched, summaries)


def _match_docker_by_hostname(hostnames: list[str], summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted = {str(name).lower() for name in hostnames if looks_like_hostname(str(name))}
    if not wanted:
        return None
    hits: list[dict[str, Any]] = []
    for item in summaries:
        hosts = {str(name).lower() for name in (item.get("hostnames") or [])}
        if wanted & hosts:
            hits.append(item)
    if not hits:
        return None
    web = [item for item in hits if item.get("running") is not False and not _looks_like_db_container(item)]
    chosen = web[0] if web else hits[0]
    return dict(chosen)


def _match_docker_summary(proxy_passes: list[str], summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for proxy in proxy_passes:
        parsed = parse_proxy(proxy)
        host = (parsed.get("host") or "").lower()
        port = parsed.get("port") or ""
        matched = _match_backend_host(host, summaries, port=port)
        if matched:
            return matched
    return None


def _container_name_tokens(item: dict[str, Any]) -> set[str]:
    tokens = {
        str(item.get("name") or "").lower().lstrip("/"),
        str(item.get("compose_service") or "").lower(),
        str(item.get("compose_project") or "").lower(),
    }
    for alias in item.get("network_aliases") or []:
        tokens.add(str(alias).lower())
    return {token for token in tokens if token}


def _match_backend_host(
    host: str,
    summaries: list[dict[str, Any]],
    *,
    port: str = "",
) -> dict[str, Any] | None:
    host = (host or "").lower().strip()
    if not host:
        return None
    exact: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    for item in summaries:
        names = _container_name_tokens(item)
        if host in names:
            exact.append(item)
            continue
        if host in {"127.0.0.1", "localhost", "::1"}:
            for pub in item.get("published_ports") or []:
                if str(pub.get("host_port")) == port:
                    exact.append(item)
                    break
            continue
        if host in GENERIC_BACKEND_HOSTS:
            continue
        for token in names:
            if token == host or token.startswith(host + "-") or token.startswith(host + "_"):
                fuzzy.append(item)
                break
            if host.startswith(token + "-") or host.startswith(token + "_"):
                fuzzy.append(item)
                break
    pool = exact or fuzzy
    if not pool:
        return None
    web = [item for item in pool if item.get("running") is not False and not _looks_like_db_container(item)]
    chosen = web[0] if web else pool[0]
    return dict(chosen)


def _enrich_docker_from_compose(
    docker: dict[str, Any] | None,
    summaries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Copy MYSQL_DATABASE / POSTGRES_DB from sibling containers in the same compose project.

    Nginx usually matches the web container, which often has no database env vars.
    The db service (e.g. journal50seacom-bkuksm-db-1) does.
    """
    if not docker:
        return docker
    project = str(docker.get("compose_project") or "")
    if not project:
        return docker
    out = dict(docker)
    web_name = str(out.get("name") or "")
    if out.get("mysql_database") and out.get("postgres_db") and out.get("db_container"):
        return out
    for item in summaries:
        if str(item.get("compose_project") or "") != project:
            continue
        if str(item.get("name") or "") == web_name:
            continue
        if not out.get("postgres_db") and item.get("postgres_db"):
            out["postgres_db"] = item.get("postgres_db")
        if item.get("mysql_database"):
            if not out.get("mysql_database"):
                out["mysql_database"] = item.get("mysql_database")
            if not out.get("db_container") and _looks_like_db_container(item):
                out["db_container"] = item.get("name")
        elif not out.get("db_container") and _looks_like_db_container(item):
            out["db_container"] = item.get("name")
    if not out.get("db_container") and (out.get("mysql_database") or out.get("postgres_db")):
        inferred = inferred_db_container(out)
        if inferred:
            out["db_container"] = inferred
    return out


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


def _canonical_hostname(
    names: list[str],
    *,
    routed: list[str] | None = None,
    advertised: list[str] | None = None,
) -> str:
    public = [n for n in names if n and n.lower() not in CATCHALL_HOSTS and not is_infrastructure_hostname(n)]
    routed_public = [n for n in (routed or []) if n in public] if routed else []
    advertised_public = [n for n in (advertised or []) if n in public] if advertised else []
    advertised_routed = [n for n in advertised_public if n in (routed_public or public)]
    use = advertised_routed or advertised_public or routed_public or public or [n for n in names if n] or ["_"]

    def sort_key(name: str) -> tuple[int, int, str]:
        lower = name.lower()
        www = 1 if lower.startswith("www.") else 0
        return (www, len(lower), lower)

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
        return ("docker", project)
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
            sources_field = list(primary.get("discovery_sources") or ([primary.get("discovery_source")] if primary.get("discovery_source") else []))
            for item in row.get("discovery_sources") or ([row.get("discovery_source")] if row.get("discovery_source") else []):
                if item and item not in sources_field:
                    sources_field.append(item)
            primary["discovery_sources"] = sources_field
            if sources_field:
                primary["discovery_source"] = " + ".join(sources_field)
            ssl_row = row.get("ssl") if isinstance(row.get("ssl"), dict) else {}
            ssl_primary = primary.get("ssl") if isinstance(primary.get("ssl"), dict) else {}
            if ssl_row or ssl_primary:
                certs = list(dict.fromkeys([*(ssl_primary.get("certificate") or []), *(ssl_row.get("certificate") or [])]))
                keys = list(dict.fromkeys([*(ssl_primary.get("certificate_key") or []), *(ssl_row.get("certificate_key") or [])]))
                https = bool(ssl_primary.get("https") or ssl_row.get("https") or primary.get("https"))
                mechanism = ssl_primary.get("mechanism") or ssl_row.get("mechanism") or _ssl_mechanism(
                    certs[0] if certs else "", https=https, docker=primary.get("docker") if isinstance(primary.get("docker"), dict) else None
                )
                primary["ssl"] = _ssl_record(
                    https=https,
                    mechanism=mechanism,
                    certificates=certs,
                    keys=keys,
                    acme_file=str(ssl_primary.get("acme_file") or ssl_row.get("acme_file") or ""),
                    extra_source_file=str(primary.get("source_file") or row.get("source_file") or ""),
                    docker=primary.get("docker") if isinstance(primary.get("docker"), dict) else None,
                )
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
                for token in ("invalid root", "duplicate hostname", "excluded root", "files_dir", "catch-all", "Backend container")
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
        docker_primary = primary.get("docker") if isinstance(primary.get("docker"), dict) else {}
        primary["hostname"] = _canonical_hostname(
            hostnames,
            routed=list(docker_primary.get("hostnames") or hostnames),
            advertised=list(docker_primary.get("advertised_hostnames") or []),
        )
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
        notes = [note for note in (app.get("notes") or []) if not str(note).startswith("duplicate hostname")]
        dups = [name for name in (app.get("hostnames") or []) if seen_hosts.get(name.lower(), 0) > 1]
        if dups:
            app["status"] = "REQUIRES REVIEW"
            notes.append("duplicate hostname: " + ", ".join(dups))
        elif app.get("status") == "REQUIRES REVIEW" and not any(
            token in note
            for note in notes
            for token in ("invalid root", "excluded root", "files_dir", "catch-all", "no application root", "Backend container")
        ):
            if not app.get("unused_default_root") and (app.get("root") or app.get("proxy_pass") or app.get("docker")):
                app["status"] = "READY"
        app["notes"] = notes
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
    backend_owners: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    probe = probe or _probe_root
    docker_containers = docker_containers or []
    mariadb = mariadb or []
    backend_owners = backend_owners or {}

    def _exists(path: str) -> bool:
        if path_exists is not None:
            return path_exists(path)
        try:
            return Path(path).is_dir()
        except OSError:
            return False
    candidates: list[dict[str, Any]] = []
    for block in servers:
        names = [n for n in (block.get("server_name") or []) if n]
        if not names:
            continue
        root = safe_unix(str(block.get("root") or ""))
        aliases = [safe_unix(p) for p in (block.get("alias") or []) if safe_unix(p)]
        proxies = list(block.get("proxy_pass") or [])
        docker = _match_docker(proxies, docker_containers, names, backend_owners)
        backend_owner: dict[str, Any] = {}
        backend_notes: list[str] = []
        if not docker and proxies:
            for port in _local_backend_ports(proxies):
                candidate = backend_owners.get(port) or {}
                if candidate.get("pid"):
                    backend_owner = candidate
                    break
        if not docker and not root and backend_owner:
            process_root = safe_unix(str(backend_owner.get("cwd") or ""))
            if process_root and not is_excluded_path(process_root) and _exists(process_root):
                root = process_root
                comm = backend_owner.get("comm") or "process"
                unit = backend_owner.get("unit") or ""
                backend_notes.append(
                    f"Reverse proxy backend on 127.0.0.1:{backend_owner.get('port')} traced to "
                    f"host process {comm} (pid {backend_owner.get('pid')}"
                    + (f", unit {unit}" if unit else "")
                    + f"); application source resolved to {process_root}."
                )
            elif backend_owner.get("pid"):
                backend_notes.append(
                    f"Reverse proxy backend on 127.0.0.1:{backend_owner.get('port')} is served by "
                    f"host process {backend_owner.get('comm') or 'unknown'} (pid {backend_owner.get('pid')}"
                    + (f", unit {backend_owner.get('unit')}" if backend_owner.get('unit') else "")
                    + "); no application working directory could be resolved."
                )
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
                dest = str(mount.get("destination") or "")
                if mount.get("named_volume"):
                    persistent.append(f"volume:{source}")
                    purpose = _volume_purpose(dest, named_volume=source)
                    if purpose == "application-data":
                        try:
                            host_path = named_volume_data_path(source)
                        except ValueError:
                            host_path = ""
                        if host_path and host_path not in persistent:
                            persistent.append(host_path)
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
        for cert_path in list(block.get("ssl_certificate") or []) + list(block.get("ssl_certificate_key") or []):
            cleaned = safe_unix(str(cert_path))
            if cleaned and cleaned not in config_paths:
                config_paths.append(cleaned)
        ssl_info = _ssl_record(
            https=bool(block.get("https") or block.get("ssl") or (docker or {}).get("traefik_tls")),
            mechanism=_ssl_mechanism(
                (list(block.get("ssl_certificate") or []) or [""])[0],
                https=bool(block.get("https") or block.get("ssl")),
                docker=docker,
            ),
            certificates=list(block.get("ssl_certificate") or []),
            keys=list(block.get("ssl_certificate_key") or []),
            extra_source_file=str(block.get("source_file") or ""),
            docker=docker,
        )
        size_bytes = 0
        if probe is _probe_root:
            for path in sources:
                try:
                    size, _count = _dir_stats(Path(path))
                    size_bytes += size
                except OSError:
                    pass
        notes: list[str] = list(backend_notes)
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
                "discovery_sources": ["nginx -T"],
                "classification": CLASSIFICATION_EXCLUDED if unused_default else CLASSIFICATION_ACTIVE,
                "root": root_out,
                "alias": aliases,
                "proxy_pass": proxies,
                "redirect_to": block.get("redirect_to") or "",
                "configuration_paths": [p for p in config_paths if p],
                "database_type": db_type,
                "database_name": db_name,
                "persistent_data_paths": persistent,
                "source_paths": list(dict.fromkeys(sources)),
                "docker": _public_docker(docker) if docker else None,
                "ojs_files_dir": ojs_files_dir,
                "http": bool(block.get("http")),
                "https": bool(ssl_info.get("https") or block.get("https")),
                "ssl": ssl_info,
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


def parse_apache_vhosts(text: str, source_file: str = "") -> list[dict[str, Any]]:
    """Parse Apache VirtualHost blocks. Missing Apache is not an error."""
    servers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (text or "").splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        open_match = re.match(r"^<VirtualHost\b([^>]*)>", line, re.IGNORECASE)
        if open_match:
            listen = open_match.group(1).strip()
            current = {
                "source_file": source_file,
                "server_name": [],
                "listen": [listen] if listen else [],
                "root": "",
                "alias": [],
                "proxy_pass": [],
                "include": [],
                "locations": [],
                "redirect_to": "",
                "http": "443" not in listen.lower() and "ssl" not in listen.lower(),
                "https": "443" in listen.lower() or "ssl" in listen.lower(),
                "ssl": "443" in listen.lower() or "ssl" in listen.lower(),
                "ssl_certificate": [],
                "ssl_certificate_key": [],
                "ssl_mechanism": "",
                "default_server": False,
            }
            continue
        if current is None:
            continue
        if re.match(r"^</VirtualHost>", line, re.IGNORECASE):
            if current.get("server_name") or current.get("root") or current.get("proxy_pass"):
                current["ssl_mechanism"] = _ssl_mechanism(
                    (current.get("ssl_certificate") or [""])[0],
                    https=bool(current.get("https")),
                )
                servers.append(current)
            current = None
            continue
        key, _, value = line.partition(" ")
        key_l = key.lower()
        value = _unquote(value.strip())
        if key_l == "servername" and looks_like_hostname(value.split()[0] if value else ""):
            current["server_name"].append(value.split()[0])
        elif key_l == "serveralias":
            current["server_name"].extend(_split_host_list(value))
        elif key_l == "documentroot":
            current["root"] = safe_unix(value)
        elif key_l == "proxypass":
            parts = value.split()
            if parts:
                current["proxy_pass"].append(parts[-1].rstrip("/"))
        elif key_l == "sslengine" and value.lower() == "on":
            current["https"] = True
            current["ssl"] = True
        elif key_l == "sslcertificatefile":
            current["ssl_certificate"].append(value)
            current["https"] = True
            current["ssl"] = True
        elif key_l == "sslcertificatekeyfile":
            current["ssl_certificate_key"].append(value)
    return servers


def _application_from_docker_summary(
    summary: dict[str, Any],
    *,
    hostnames: list[str],
    probe: Callable,
    path_exists: Callable[[str], bool],
    source: str,
    extra_source_file: str = "",
    extra_proxy: list[str] | None = None,
    extra_tls: bool = False,
    extra_notes: list[str] | None = None,
) -> dict[str, Any]:
    docker = _enrich_docker_from_compose(dict(summary), [summary])
    docker = docker or dict(summary)
    workdir = safe_unix(str(docker.get("compose_workdir") or ""))
    files, texts = probe(workdir) if workdir and not is_excluded_path(workdir) else ({}, {})
    app_type = classify_application(
        root=workdir,
        aliases=[],
        proxy_passes=[],
        docker=docker,
        files=files,
        texts=texts,
    )
    db_name = ""
    db_type = ""
    if docker.get("postgres_db"):
        db_type = "PostgreSQL"
        db_name = str(docker.get("postgres_db") or "")
    elif docker.get("mysql_database"):
        db_type = "MariaDB"
        db_name = str(docker.get("mysql_database") or "")
    if not db_name:
        generic = parse_generic_database_from_texts(texts)
        if generic:
            db_name = generic
            db_type = db_type or "MariaDB"
    persistent: list[str] = []
    sources: list[str] = []
    if workdir and not is_excluded_path(workdir):
        sources.append(workdir)
    for mount in docker.get("mounts") or []:
        source_path = str(mount.get("source") or "")
        dest = str(mount.get("destination") or "")
        if mount.get("named_volume"):
            persistent.append(f"volume:{source_path}")
            purpose = _volume_purpose(dest, named_volume=source_path)
            if purpose == "application-data":
                try:
                    host_path = named_volume_data_path(source_path)
                except ValueError:
                    host_path = ""
                if host_path and host_path not in persistent:
                    persistent.append(host_path)
                    sources.append(host_path)
        elif source_path and not is_excluded_path(source_path):
            if source_path not in persistent:
                persistent.append(source_path)
            if source_path not in sources:
                sources.append(source_path)
    config_paths = []
    compose = str(docker.get("compose_files") or "")
    if compose:
        config_paths.extend(part.strip() for part in compose.split(",") if part.strip())
    named = list(dict.fromkeys(hostnames))
    proxies = [p for p in (extra_proxy or []) if p]
    if extra_source_file and extra_source_file not in config_paths:
        config_paths.append(extra_source_file)
    https = bool(docker.get("traefik_tls") or extra_tls)
    mechanism = _ssl_mechanism("", https=https, docker=docker)
    if extra_tls and mechanism in {"none", "https-listen-without-certificate-path"}:
        mechanism = "traefik-acme"
    ssl_info = _ssl_record(
        https=https,
        mechanism=mechanism,
        extra_source_file=extra_source_file,
        docker=docker,
    )
    notes = [
        f"Discovered from {source}; not present as an Nginx server_name in nginx -T.",
        "Future websites advertised via Traefik/Dokploy Host() files, labels, or VIRTUAL_HOST are included automatically.",
    ]
    for note in extra_notes or []:
        if note and note not in notes:
            notes.append(note)
    if docker.get("running") is False:
        notes.append(f"Docker container {docker.get('name') or ''} is not running.")
    details = {
        name: {
            "source_file": extra_source_file or compose or "docker inspect",
            "root": workdir,
            "alias": [],
            "proxy_pass": proxies,
            "redirect_to": "",
            "listen": [],
        }
        for name in named
    }
    status = "READY"
    if docker.get("running") is False:
        status = "REQUIRES REVIEW"
    return {
        "application_id": _application_id(app_type=app_type, root=workdir, docker=docker, proxy_passes=proxies),
        "hostname": _canonical_hostname(
            named,
            routed=list(docker.get("hostnames") or named),
            advertised=list(docker.get("advertised_hostnames") or []),
        ),
        "hostnames": named,
        "hostname_details": details,
        "type": app_type,
        "discovery_source": source,
        "discovery_sources": [source],
        "classification": CLASSIFICATION_ACTIVE if docker.get("running") is not False else CLASSIFICATION_LEGACY,
        "root": workdir,
        "alias": [],
        "proxy_pass": proxies,
        "redirect_to": "",
        "configuration_paths": config_paths,
        "database_type": db_type,
        "database_name": db_name,
        "persistent_data_paths": persistent,
        "source_paths": list(dict.fromkeys(sources)),
        "docker": _public_docker(docker),
        "ojs_files_dir": "",
        "http": True,
        "https": https,
        "ssl": ssl_info,
        "listen": [],
        "default_server": False,
        "unused_default_root": False,
        "source_file": extra_source_file or compose or "docker inspect",
        "estimated_bytes": 0,
        "status": status,
        "notes": notes,
        "included": False,
        "excluded": False,
    }


def applications_from_unmatched_docker(
    existing: list[dict[str, Any]],
    containers: list[dict[str, Any]],
    *,
    probe: Callable | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create applications from running web containers whose hostnames nginx -T missed.

    Stopped containers with hostnames are returned as leftover records, not backup apps.
    """
    probe = probe or _probe_root

    def _exists(path: str) -> bool:
        if path_exists is not None:
            return path_exists(path)
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    all_summaries = [_docker_summary(item) for item in containers]
    summaries = [_enrich_docker_from_compose(item, all_summaries) or item for item in all_summaries]
    claimed = {str(name).lower() for app in existing for name in (app.get("hostnames") or []) if name}
    claimed_projects = {
        str((app.get("docker") or {}).get("compose_project") or "").lower()
        for app in existing
        if isinstance(app.get("docker"), dict) and (app.get("docker") or {}).get("compose_project")
    }
    extras: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []
    for summary in summaries:
        if _looks_like_db_container(summary) or _looks_like_infrastructure_container(summary):
            continue
        hosts = [
            h
            for h in (summary.get("hostnames") or [])
            if looks_like_hostname(str(h)) and not is_infrastructure_hostname(str(h))
        ]
        unused = [h for h in hosts if h.lower() not in claimed]
        if not unused:
            continue
        project = str(summary.get("compose_project") or "").lower()
        if project and project in claimed_projects and not unused:
            continue
        running = summary.get("running") is not False
        if not running:
            leftovers.append(
                {
                    "hostname": unused[0],
                    "hostnames": unused,
                    "in_active_nginx": False,
                    "verdict": "NOT ACTIVE IN CURRENT SERVER CONFIGURATION",
                    "classification": CLASSIFICATION_LEGACY,
                    "evidence": [
                        {
                            "source": "docker",
                            "file": "docker inspect",
                            "detail": (
                                f"container {summary.get('name') or ''} has Host()/VIRTUAL_HOST labels "
                                "but is not running"
                            ),
                            "root": summary.get("compose_workdir") or "",
                            "enabled": False,
                        }
                    ],
                }
            )
            continue
        extras.append(
            _application_from_docker_summary(
                summary,
                hostnames=unused,
                probe=probe,
                path_exists=_exists,
                source="docker labels",
            )
        )
        for name in unused:
            claimed.add(name.lower())
        if project:
            claimed_projects.add(project)
    return extras, leftovers


def _application_from_unmatched_route(
    route: dict[str, Any],
    hostnames: list[str],
) -> dict[str, Any]:
    named = list(dict.fromkeys(hostnames))
    proxies = list(route.get("backend_urls") or [])
    source_file = str(route.get("source_file") or "")
    https = bool(route.get("tls"))
    notes = [
        "Discovered from Traefik/Dokploy dynamic configuration; not present as an Nginx server_name in nginx -T.",
        "A live reverse-proxy Host() rule is treated as an active website even when docker inspect has no Host() labels.",
        "Backend container was not matched by name, compose service, project, or network alias.",
    ]
    details = {
        name: {
            "source_file": source_file,
            "root": "",
            "alias": [],
            "proxy_pass": proxies,
            "redirect_to": "",
            "listen": [],
        }
        for name in named
    }
    return {
        "application_id": _application_id(
            app_type="Docker",
            root="",
            docker=None,
            proxy_passes=proxies,
        ),
        "hostname": _canonical_hostname(named),
        "hostnames": named,
        "hostname_details": details,
        "type": "Docker",
        "discovery_source": "traefik dynamic",
        "discovery_sources": ["traefik dynamic"],
        "classification": CLASSIFICATION_ACTIVE,
        "root": "",
        "alias": [],
        "proxy_pass": proxies,
        "redirect_to": "",
        "configuration_paths": [source_file] if source_file else [],
        "database_type": "",
        "database_name": "",
        "persistent_data_paths": [],
        "source_paths": [],
        "docker": None,
        "ojs_files_dir": "",
        "http": True,
        "https": https,
        "ssl": _ssl_record(
            https=https,
            mechanism="traefik-acme" if https else "none",
            extra_source_file=source_file,
        ),
        "listen": [],
        "default_server": False,
        "unused_default_root": False,
        "source_file": source_file,
        "estimated_bytes": 0,
        "status": "REQUIRES REVIEW",
        "notes": notes,
        "included": False,
        "excluded": False,
        "database_status": "UNRESOLVED",
    }


def applications_from_traefik_routes(
    existing: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    containers: list[dict[str, Any]],
    *,
    probe: Callable | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Promote live Traefik/Dokploy Host() routes to applications.

    1.4.24 scanned these files but classified unmatched Host() names as LEGACY leftovers,
    so they never appeared under DISCOVERED HOSTNAMES / DISCOVERED APPLICATIONS.
    """
    probe = probe or _probe_root

    def _exists(path: str) -> bool:
        if path_exists is not None:
            return path_exists(path)
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    all_summaries = [_docker_summary(item) for item in containers]
    summaries = [_enrich_docker_from_compose(item, all_summaries) or item for item in all_summaries]
    mention_roles, advertised_hosts = _hostname_roles_from_containers(containers)
    claimed = {str(name).lower() for app in existing for name in (app.get("hostnames") or []) if name}
    extras: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []
    for route in routes:
        hosts = [h for h in (route.get("hostnames") or []) if looks_like_hostname(str(h))]
        infra_hosts = [h for h in hosts if is_infrastructure_hostname(str(h))]
        unused = [h for h in hosts if h.lower() not in claimed and not is_infrastructure_hostname(str(h))]
        if infra_hosts and not unused:
            leftovers.append(
                {
                    "hostname": infra_hosts[0],
                    "hostnames": infra_hosts,
                    "in_active_nginx": False,
                    "verdict": "INFRASTRUCTURE ROUTE — NOT A PUBLIC WEBSITE",
                    "classification": CLASSIFICATION_SYSTEM,
                    "evidence": [
                        {
                            "source": "traefik-infrastructure",
                            "file": route.get("source_file") or "",
                            "detail": (
                                "Host() uses an internal/.localhost/.local/.internal name. "
                                "This is Dokploy/Traefik management routing, not a public website folder."
                            ),
                            "root": "",
                            "enabled": bool(route.get("live_proxy")),
                        }
                    ],
                }
            )
            continue
        if not unused:
            continue
        live = bool(route.get("live_proxy")) and not route.get("migration")
        matched = None
        for url in route.get("backend_urls") or []:
            parsed = urlparse(url)
            matched = _match_backend_host(parsed.hostname or "", summaries, port=str(parsed.port or ""))
            if matched:
                break
        if not matched:
            service = str(route.get("service") or "").split("@", 1)[0]
            if service:
                matched = _match_backend_host(service, summaries)
        if not matched:
            for host in unused:
                label = str(host).split(".", 1)[0]
                if label and label not in GENERIC_BACKEND_HOSTS:
                    matched = _match_backend_host(label, summaries)
                    if matched:
                        break
        if matched and _looks_like_infrastructure_container(matched):
            leftovers.append(
                {
                    "hostname": unused[0],
                    "hostnames": unused,
                    "in_active_nginx": False,
                    "verdict": "INFRASTRUCTURE SERVICE — NOT A PUBLIC WEBSITE",
                    "classification": CLASSIFICATION_SYSTEM,
                    "evidence": [
                        {
                            "source": "traefik-infrastructure",
                            "file": route.get("source_file") or "",
                            "detail": (
                                f"Host() backend is infrastructure container {matched.get('name') or ''} "
                                f"(project {matched.get('compose_project') or ''}). "
                                "Dokploy/Traefik data is backed up under _server, not as a website folder."
                            ),
                            "root": "",
                            "enabled": bool(route.get("live_proxy")),
                        }
                    ],
                }
            )
            continue
        config_only = [h for h in unused if _config_only_hostname(str(h), mention_roles, advertised_hosts)]
        website_hosts = [h for h in unused if h not in config_only]
        if not matched:
            if not website_hosts:
                leftovers.append(
                    {
                        "hostname": unused[0],
                        "hostnames": unused,
                        "in_active_nginx": False,
                        "verdict": "CONFIGURATION/PLACEHOLDER HOSTNAME — NOT A PUBLIC WEBSITE",
                        "classification": CLASSIFICATION_SYSTEM,
                        "evidence": [
                            {
                                "source": "hostname-investigation",
                                "file": route.get("source_file") or "",
                                "detail": (
                                    "Host() hostname is also an image documentation URL, API endpoint, "
                                    "or CORS/config value and is not PUBLIC_HOST/SITE_URL. "
                                    "It is not a deployed website folder."
                                ),
                                "root": "",
                                "enabled": bool(route.get("live_proxy")),
                            }
                        ],
                    }
                )
                continue
            unused = website_hosts
        if matched and matched.get("running") is not False:
            matched = _enrich_docker_from_compose(matched, summaries) or matched
            extras.append(
                _application_from_docker_summary(
                    matched,
                    hostnames=unused,
                    probe=probe,
                    path_exists=_exists,
                    source="traefik dynamic",
                    extra_source_file=str(route.get("source_file") or ""),
                    extra_proxy=list(route.get("backend_urls") or []),
                    extra_tls=bool(route.get("tls") or matched.get("traefik_tls")),
                    extra_notes=[
                        f"Traefik/Dokploy file {route.get('source_file') or ''} Host() was not on docker inspect labels.",
                        "Previous discovery treated unmatched compose/Dokploy Host() as leftovers instead of applications.",
                    ],
                )
            )
            for name in unused:
                claimed.add(name.lower())
            continue
        if live:
            if matched:
                matched = _enrich_docker_from_compose(matched, summaries) or matched
                extras.append(
                    _application_from_docker_summary(
                        matched,
                        hostnames=unused,
                        probe=probe,
                        path_exists=_exists,
                        source="traefik dynamic",
                        extra_source_file=str(route.get("source_file") or ""),
                        extra_proxy=list(route.get("backend_urls") or []),
                        extra_tls=bool(route.get("tls")),
                        extra_notes=[
                            f"Live Traefik route in {route.get('source_file') or ''}; backend container is not running.",
                        ],
                    )
                )
            else:
                extras.append(_application_from_unmatched_route(route, unused))
            for name in unused:
                claimed.add(name.lower())
            continue
        leftovers.append(
            {
                "hostname": unused[0],
                "hostnames": unused,
                "in_active_nginx": False,
                "verdict": "NOT ACTIVE IN CURRENT SERVER CONFIGURATION",
                "classification": CLASSIFICATION_LEGACY if route.get("migration") else CLASSIFICATION_UNRESOLVED,
                "evidence": [
                    {
                        "source": "dokploy-compose",
                        "file": route.get("source_file") or "",
                        "detail": (
                            "hostname in compose/Dokploy file; no live Traefik dynamic route and "
                            "no running web container matched"
                        ),
                        "root": "",
                        "enabled": False,
                    }
                ],
            }
        )
    return extras, leftovers


def scan_proxy_routes(
    extra_files: dict[str, str] | None = None,
    *,
    run: Callable | None = None,
    docker_containers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Walk Dokploy/Traefik/compose files and return Host() routes with backends."""
    roots = tuple(dict.fromkeys([*DOKPLOY_SCAN_ROOTS, *TRAEFIK_SCAN_ROOTS]))
    paths = _iter_existing_files(roots, extra_files)
    for inspect in docker_containers or []:
        summary = _docker_summary(inspect)
        for raw in str(summary.get("compose_files") or "").split(","):
            path = raw.strip()
            if path and path not in paths:
                paths.append(path)
    routes: list[dict[str, Any]] = []
    for path in paths:
        lower = path.lower()
        if lower.endswith("acme.json"):
            continue
        if not any(lower.endswith(ext) or ext in lower for ext in (".yml", ".yaml", ".json", ".toml")):
            continue
        text = _read_scan_file(path, extra_files, limit=120000)
        parsed = parse_traefik_file(text, path)
        if parsed.get("hostnames"):
            if any(
                str((_docker_summary(item).get("compose_files") or "")).find(path) >= 0
                and _docker_summary(item).get("running") is not False
                for item in (docker_containers or [])
            ):
                parsed["live_proxy"] = True
            routes.append(parsed)
    routes.extend(collect_proxy_routes_from_docker(run, docker_containers))
    return _dedupe_proxy_routes(routes)


def scan_acme_hostnames(
    extra_files: dict[str, str] | None = None,
    *,
    run: Callable | None = None,
    docker_containers: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    roots = tuple(dict.fromkeys([*DOKPLOY_SCAN_ROOTS, *TRAEFIK_SCAN_ROOTS]))
    paths = _iter_existing_files(roots, extra_files)
    if extra_files:
        paths.extend(key for key in extra_files if str(key).lower().endswith("acme.json"))
    for path in list(dict.fromkeys(paths)):
        if "acme.json" not in path.lower():
            continue
        text = _read_scan_file(path, extra_files, limit=2_000_000)
        names = hostnames_from_acme_json(text)
        if names:
            found[path] = names
    for key, names in collect_acme_from_docker(run, docker_containers).items():
        found.setdefault(key, names)
    return found


def applications_from_apache_servers(
    apache_servers: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    docker_containers: list[dict[str, Any]] | None = None,
    probe: Callable | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    claimed = {str(name).lower() for app in existing for name in (app.get("hostnames") or []) if name}
    leftover_servers = [
        block
        for block in apache_servers
        if any(looks_like_hostname(str(n)) and str(n).lower() not in claimed for n in (block.get("server_name") or []))
    ]
    if not leftover_servers:
        return []
    apps = applications_from_servers(
        leftover_servers,
        probe=probe,
        docker_containers=docker_containers,
        path_exists=path_exists,
    )
    extra: list[dict[str, Any]] = []
    for app in apps:
        names = [n for n in (app.get("hostnames") or []) if str(n).lower() not in claimed]
        if not names:
            continue
        app = dict(app)
        app["hostnames"] = names
        app["hostname"] = _canonical_hostname(names)
        app["discovery_source"] = "apache"
        app["discovery_sources"] = ["apache"]
        app["classification"] = CLASSIFICATION_ACTIVE
        extra.append(app)
        for name in names:
            claimed.add(name.lower())
    return extra


def inventory_docker_volumes(
    containers: list[dict[str, Any]],
    applications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Every named volume is classified. Overlay2 is never treated as a volume."""
    host_by_container: dict[str, list[str]] = {}
    host_by_project: dict[str, list[str]] = {}
    app_by_host: dict[str, dict[str, Any]] = {}
    for app in applications:
        names = [str(n) for n in (app.get("hostnames") or []) if n]
        docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
        container = str(docker.get("container") or "").lstrip("/")
        project = str(docker.get("compose_project") or "")
        for name in names:
            app_by_host[name.lower()] = app
        if container:
            host_by_container.setdefault(container.lower(), []).extend(names)
        if project:
            host_by_project.setdefault(project.lower(), []).extend(names)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for inspect in containers:
        summary = _docker_summary(inspect)
        for mount in summary.get("mounts") or []:
            if not mount.get("named_volume"):
                continue
            name = str(mount.get("source") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            dest = str(mount.get("destination") or "")
            container = str(summary.get("name") or "")
            purpose = _volume_purpose(dest, named_volume=name, container=container)
            status = _volume_backup_status(purpose)
            project = str(summary.get("compose_project") or "")
            hosts = [
                h
                for h in dict.fromkeys(
                    host_by_container.get(container.lower(), []) + host_by_project.get(project.lower(), [])
                )
                if h and not is_infrastructure_hostname(h)
            ]
            website = hosts[0] if hosts and purpose not in {"infrastructure", "cache"} else ""
            infra_container = _looks_like_infrastructure_container(summary)
            classification = CLASSIFICATION_ACTIVE if website else CLASSIFICATION_UNRESOLVED
            scope = "website" if website else "unresolved"
            application = website
            if purpose == "cache":
                classification = CLASSIFICATION_EXCLUDED
                scope = "excluded"
            elif purpose == "infrastructure" or (infra_container and not website):
                classification = CLASSIFICATION_SYSTEM
                scope = "infrastructure"
                application = project or container
            elif purpose == "database-data" and website:
                classification = CLASSIFICATION_ACTIVE
                scope = "website"
            dest_path = ""
            if purpose == "database-data":
                dest_path = (
                    f"{website}/database/"
                    if website
                    else "_server/infrastructure/databases/"
                )
            elif scope == "infrastructure":
                dest_path = f"_server/infrastructure/volumes/{name}/"
            elif website:
                dest_path = f"{website}/docker/volumes/{name}/"
            try:
                host_path = named_volume_data_path(name)
            except ValueError:
                host_path = ""
            size_bytes = 0
            file_count = 0
            if host_path:
                try:
                    if Path(host_path).is_dir():
                        size_bytes, file_count = _dir_stats(Path(host_path))
                except OSError:
                    size_bytes, file_count = 0, 0
            rows.append(
                {
                    "name": name,
                    "container": container,
                    "mount": dest,
                    "mount_point": dest,
                    "host_path": host_path,
                    "purpose": purpose,
                    "application": application,
                    "scope": scope,
                    "website": website,
                    "hostnames": hosts,
                    "backup_method": status,
                    "backup_status": status,
                    "source": host_path or f"volume:{name}",
                    "destination": dest_path,
                    "backup_destination": dest_path,
                    "size_bytes": size_bytes,
                    "file_count": file_count,
                    "classification": classification,
                    "notes": _volume_notes(purpose, website, name, dest),
                    "status": status,
                }
            )
    return rows


def _volume_notes(purpose: str, website: str, name: str, destination: str = "") -> str:
    if purpose == "database-data":
        if website:
            return (
                f"Named volume {name} is a database data directory. "
                "It is backed up via SQL dump for the associated website, not as a live raw copy."
            )
        return (
            f"Named volume {name} is infrastructure database storage at {destination or 'unknown'}. "
            "It is dumped with pg_dump/mysqldump into _server/infrastructure/databases/, not copied live."
        )
    if purpose == "cache":
        return f"Named volume {name} looks like cache/redis; intentionally excluded from website restore data."
    if purpose == "infrastructure":
        dest = destination or ""
        if dest.rstrip("/").endswith(".docker") or "/.docker" in dest:
            return (
                f"Named volume {name} is Docker CLI/config state mounted at {dest or '/root/.docker'}. "
                "It is Dokploy/Docker management-plane data, not a public website. "
                f"Backed up under _server/infrastructure/volumes/{name}/ for Dokploy recovery."
            )
        return (
            f"Named volume {name} is infrastructure/management-plane storage ({dest or 'unknown mount'}). "
            "Backed up under _server, not as a website folder."
        )
    if purpose == "application-data":
        if website:
            return f"Named volume {name} contains persistent application data for {website} and is copied from _data."
        return f"Named volume {name} looks like application data but has no website association."
    return f"Named volume {name} is unclassified."


def _read_scan_file(path: str, extra_files: dict[str, str] | None = None, limit: int = 40000) -> str:
    if extra_files and path in extra_files:
        return extra_files[path][:limit]
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _path_exists_unprivileged(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _path_is_file_unprivileged(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _iter_existing_files(roots: tuple[str, ...], extra_files: dict[str, str] | None = None) -> list[str]:
    files: list[str] = []
    if extra_files:
        files.extend(extra_files.keys())
    for root in roots:
        files.extend(_walk_files_unprivileged(root))
    return list(dict.fromkeys(files))


def _walk_files_unprivileged(root: str) -> list[str]:
    files: list[str] = []
    try:
        base = Path(root)
        if not _path_exists_unprivileged(base):
            return []
        if _path_is_file_unprivileged(base):
            return [str(base)]
    except OSError:
        return []

    def _onerror(_err: OSError) -> None:
        return None

    try:
        for dirpath, _dirnames, filenames in os.walk(base, onerror=_onerror):
            for name in filenames:
                path = Path(dirpath) / name
                if _path_is_file_unprivileged(path):
                    files.append(str(path))
    except OSError:
        return files
    return files


def unreadable_live_proxy_files() -> list[str]:
    """Host Traefik/Dokploy files that exist but cannot be read by this account."""
    missed: list[str] = []
    roots = tuple(dict.fromkeys([*DOKPLOY_SCAN_ROOTS, *TRAEFIK_SCAN_ROOTS]))
    for path in _iter_existing_files(roots, None):
        if not is_live_proxy_config_path(path):
            continue
        lower = path.lower()
        if not any(lower.endswith(ext) for ext in (".yml", ".yaml", ".json", ".toml")):
            continue
        try:
            if not os.access(path, os.R_OK):
                missed.append(path)
                continue
            Path(path).read_text(encoding="utf-8", errors="replace")[:1]
        except OSError:
            missed.append(path)
    return missed


def scan_compose_hostnames(extra_files: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Hostnames advertised in on-disk compose/Dokploy files, keyed by file path."""
    found: dict[str, list[str]] = {}
    paths = _iter_existing_files(DOKPLOY_SCAN_ROOTS, extra_files)
    for path in paths:
        lower = path.lower()
        if not any(lower.endswith(name) or name in lower for name in (".yml", ".yaml", ".json")):
            continue
        text = _read_scan_file(path, extra_files)
        names = hostnames_from_compose_text(text)
        if names:
            found[path] = names
    return found


def scan_apache_servers(extra_files: dict[str, str] | None = None) -> list[dict[str, Any]]:
    servers: list[dict[str, Any]] = []
    paths = _iter_existing_files(APACHE_SCAN_ROOTS, extra_files)
    for path in paths:
        lower = path.lower()
        if "apache" not in lower and "httpd" not in lower:
            if extra_files is None:
                continue
        text = _read_scan_file(path, extra_files)
        if "<virtualhost" not in text.lower():
            continue
        servers.extend(parse_apache_vhosts(text, path))
    return servers


def classify_discovered_items(
    *,
    applications: list[dict[str, Any]],
    inactive_hostnames: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    database_inventory: list[dict[str, Any]],
    nginx_inventory: list[dict[str, Any]],
    hostname_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every hostname/volume/database/nginx block lands in exactly one category."""
    rows: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for app in applications:
        change = str(app.get("change") or "")
        if change == "migrated" or str(app.get("status") or "").startswith("SITE MIGRATED"):
            category = CLASSIFICATION_MIGRATED
        elif change == "removed" or str(app.get("status") or "").startswith("SITE REMOVED"):
            category = CLASSIFICATION_UNRESOLVED
        elif app.get("unused_default_root") or "EXCLUDED" in str(app.get("status") or ""):
            category = CLASSIFICATION_EXCLUDED
        elif app.get("classification") == CLASSIFICATION_LEGACY:
            category = CLASSIFICATION_LEGACY
        elif "REVIEW" in str(app.get("status") or "") and not app.get("docker") and not app.get("root") and not app.get("proxy_pass"):
            category = CLASSIFICATION_UNRESOLVED
        else:
            category = CLASSIFICATION_ACTIVE
        docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
        ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
        names = [str(n) for n in (app.get("hostnames") or [app.get("hostname")]) if n]
        canonical = str(app.get("hostname") or (names[0] if names else ""))
        for hostname in names:
            if not hostname:
                continue
            key = str(hostname).lower()
            if key in seen_hosts:
                continue
            seen_hosts.add(key)
            host_role = "canonical" if str(hostname) == canonical else f"alias of {canonical}"
            rows.append(
                {
                    "kind": "hostname",
                    "hostname": hostname,
                    "hostname_role": host_role,
                    "application": app.get("application_id") or "",
                    "type": app.get("type") or "",
                    "source_path": app.get("root") or docker.get("workdir") or app.get("source_file") or "",
                    "discovery_source": app.get("discovery_source") or "",
                    "docker": docker.get("container") or docker.get("compose_project") or "",
                    "database": app.get("database_name") or app.get("database_status") or "UNRESOLVED",
                    "nginx": app.get("source_file") or "",
                    "ssl": ssl.get("mechanism") or ("https" if app.get("https") else "none"),
                    "size_bytes": int(app.get("estimated_bytes") or 0),
                    "file_count": int(app.get("file_count") or 0),
                    "restore_ready": (app.get("restore") or {}).get("restore_ready") or "NO",
                    "restore_missing": list((app.get("restore") or {}).get("missing") or []),
                    "status": app.get("status") or "",
                    "classification": category,
                }
            )
    for row in inactive_hostnames or []:
        hostname = str(row.get("hostname") or "")
        if not hostname or hostname.lower() in seen_hosts:
            continue
        if is_infrastructure_hostname(hostname):
            continue
        if str(row.get("classification") or "") == CLASSIFICATION_SYSTEM:
            continue
        seen_hosts.add(hostname.lower())
        evidence = row.get("evidence") or []
        source = ""
        path = ""
        if evidence:
            source = str(evidence[0].get("source") or "")
            path = str(evidence[0].get("file") or evidence[0].get("root") or "")
        rows.append(
            {
                "kind": "hostname",
                "hostname": hostname,
                "application": "",
                "type": "",
                "source_path": path or source,
                "discovery_source": source or "on-disk config",
                "docker": "",
                "database": "",
                "nginx": path if "nginx" in source else "",
                "ssl": "none",
                "size_bytes": 0,
                "status": row.get("verdict") or CLASSIFICATION_LEGACY,
                "classification": row.get("classification") or CLASSIFICATION_LEGACY,
            }
        )
    mention_class = {
        HOSTNAME_ROLE_INFRASTRUCTURE: CLASSIFICATION_SYSTEM,
        HOSTNAME_ROLE_PLACEHOLDER: CLASSIFICATION_SYSTEM,
        HOSTNAME_ROLE_EXTERNAL: CLASSIFICATION_SYSTEM,
        HOSTNAME_ROLE_CONFIG: CLASSIFICATION_SYSTEM,
        HOSTNAME_ROLE_ADVERTISED: CLASSIFICATION_ACTIVE,
        HOSTNAME_ROLE_ALIAS: CLASSIFICATION_ACTIVE,
        HOSTNAME_ROLE_ROUTING: CLASSIFICATION_ACTIVE,
    }
    for rec in hostname_records or []:
        hostname = str(rec.get("hostname") or "")
        if not hostname:
            continue
        key = hostname.lower()
        if key in seen_hosts:
            continue
        role = str(rec.get("role") or HOSTNAME_ROLE_CONFIG)
        if role in {HOSTNAME_ROLE_ROUTING, HOSTNAME_ROLE_ADVERTISED, HOSTNAME_ROLE_ALIAS} and rec.get("assigned_website"):
            continue
        if role in {HOSTNAME_ROLE_ROUTING} and not rec.get("assigned_website") and not is_infrastructure_hostname(hostname):
            category = CLASSIFICATION_UNRESOLVED
        else:
            category = mention_class.get(role, CLASSIFICATION_SYSTEM)
        seen_hosts.add(key)
        rows.append(
            {
                "kind": "hostname-investigation",
                "hostname": hostname,
                "application": "",
                "type": role,
                "source_path": rec.get("evidence") or rec.get("source") or "",
                "discovery_source": rec.get("source") or "",
                "docker": rec.get("container") or "",
                "database": "",
                "nginx": "",
                "ssl": "none",
                "size_bytes": 0,
                "status": role,
                "classification": category,
                "key": rec.get("key") or "",
            }
        )
    for vol in volumes or []:
        rows.append(
            {
                "kind": "volume",
                "hostname": vol.get("website") or "",
                "application": vol.get("name") or "",
                "type": "docker-volume",
                "source_path": vol.get("host_path") or vol.get("mount_point") or "",
                "discovery_source": "docker volume",
                "docker": vol.get("container") or "",
                "database": vol.get("name") if vol.get("purpose") == "database-data" else "",
                "nginx": "",
                "ssl": "none",
                "size_bytes": int(vol.get("size_bytes") or 0),
                "status": vol.get("backup_status") or "",
                "classification": vol.get("classification") or CLASSIFICATION_UNRESOLVED,
            }
        )
    for row in database_inventory or []:
        status = str(row.get("status") or "")
        if row.get("system") or "SYSTEM DATABASE" in status:
            category = CLASSIFICATION_SYSTEM
        elif status.startswith("ASSOCIATED"):
            category = CLASSIFICATION_ACTIVE
        elif status.startswith("RECOVERY"):
            category = CLASSIFICATION_RECOVERY
        elif "EXCLUDED" in status:
            category = CLASSIFICATION_EXCLUDED
        else:
            category = CLASSIFICATION_UNRESOLVED
        rows.append(
            {
                "kind": "database",
                "hostname": "",
                "application": row.get("application_id") or "",
                "type": row.get("type") or "MariaDB",
                "source_path": row.get("docker_container") or "",
                "discovery_source": "database inventory",
                "docker": row.get("docker_container") or "",
                "database": row.get("name") or "",
                "nginx": "",
                "ssl": "none",
                "size_bytes": int(row.get("size_bytes") or 0),
                "status": status,
                "classification": category,
            }
        )
    claimed_nginx_hosts = seen_hosts
    for block in nginx_inventory or []:
        names = [str(n) for n in (block.get("server_name") or []) if n]
        if names and any(name.lower() in claimed_nginx_hosts for name in names):
            continue
        if not names:
            rows.append(
                {
                    "kind": "nginx",
                    "hostname": "",
                    "application": "",
                    "type": "nginx-server",
                    "source_path": block.get("source_file") or "",
                    "discovery_source": "nginx -T",
                    "docker": "",
                    "database": "",
                    "nginx": block.get("source_file") or "",
                    "ssl": "https" if block.get("https") else "none",
                    "size_bytes": 0,
                    "status": "unexplained nginx server block",
                    "classification": CLASSIFICATION_UNRESOLVED,
                }
            )
    return rows


def _attach_acme_ssl(applications: list[dict[str, Any]], acme_hosts: dict[str, list[str]]) -> None:
    by_host: dict[str, str] = {}
    for path, names in acme_hosts.items():
        for name in names:
            by_host.setdefault(str(name).lower(), path)
    for app in applications:
        ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
        matched = [
            by_host[str(name).lower()]
            for name in (app.get("hostnames") or [])
            if str(name).lower() in by_host
        ]
        if not matched:
            continue
        ssl = dict(ssl)
        ssl.update(
            _ssl_record(
                https=True,
                mechanism="traefik-acme"
                if not ssl.get("mechanism") or ssl.get("mechanism") in {"none", "https-listen-without-certificate-path"}
                else str(ssl.get("mechanism")),
                certificates=list(ssl.get("certificate") or []),
                keys=list(ssl.get("certificate_key") or []),
                acme_file=matched[0],
                extra_source_file=str(app.get("source_file") or ""),
                docker=app.get("docker") if isinstance(app.get("docker"), dict) else None,
            )
        )
        app["ssl"] = ssl
        app["https"] = True
        config = list(app.get("configuration_paths") or [])
        if matched[0] not in config:
            config.append(matched[0])
            app["configuration_paths"] = config


def _database_status_for_app(app: dict[str, Any]) -> str:
    if app.get("database_name"):
        return "ASSOCIATED"
    docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
    has_db_volume = any(
        str(mount.get("purpose") or "") == "database-data"
        or "postgres" in str(mount.get("destination") or "").lower()
        or "mysql" in str(mount.get("destination") or "").lower()
        or "mariadb" in str(mount.get("destination") or "").lower()
        for mount in (docker.get("mounts") or [])
        if isinstance(mount, dict)
    )
    if docker.get("db_container") or docker.get("mysql_database") or docker.get("postgres_db") or has_db_volume:
        return "UNRESOLVED"
    if str(app.get("type") or "") in {"WordPress", "OJS"}:
        return "UNRESOLVED"
    source = str(app.get("discovery_source") or "")
    if str(app.get("type") or "") == "Docker" and not docker and "traefik" in source:
        return "UNRESOLVED"
    return "NONE"


def _restore_ready_for_app(app: dict[str, Any], db_row: dict[str, Any] | None) -> dict[str, Any]:
    missing: list[str] = []
    docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
    ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
    has_files = bool(app.get("root") or app.get("source_paths") or app.get("persistent_data_paths"))
    has_proxy = bool(app.get("proxy_pass") or app.get("source_file") or docker)
    if not has_files and not docker:
        missing.append("application files / persistent path")
    if not has_proxy:
        missing.append("nginx or Traefik configuration")
    db_status = str(app.get("database_status") or _database_status_for_app(app))
    if db_status == "UNRESOLVED":
        missing.append("database association")
    elif db_status == "ASSOCIATED":
        missing.append("database dump (Dry Run does not dump; BACKUP NOW required)")
        if db_row and db_row.get("size_bytes") is None and db_row.get("docker_container"):
            missing.append("database size unverified inside Docker container")
        if docker and not (db_row or {}).get("docker_container") and not docker.get("db_container"):
            missing.append("database container")
        engine = str((db_row or {}).get("type") or app.get("database_type") or "")
        if "postgres" in engine.lower():
            if not (db_row or {}).get("dump_capable"):
                missing.append("validated PostgreSQL pg_dump (psql/pg_dump probe did not succeed)")
            if not (db_row or {}).get("dump_method"):
                missing.append("PostgreSQL dump method")
        elif db_row and db_row.get("docker_container") and db_row.get("dump_capable") is False:
            missing.append("validated database dump probe")
    if app.get("https") and not (
        ssl.get("certificate")
        or ssl.get("acme_file")
        or ssl.get("storage_paths")
        or ssl.get("mechanism") in {"traefik", "traefik-acme", "letsencrypt"}
    ):
        missing.append("ssl certificate / ACME material")
    elif app.get("https") and ssl.get("mechanism") == "https-listen-without-certificate-path":
        missing.append("ssl certificate storage path")
    if docker:
        named = [
            mount.get("source")
            for mount in (docker.get("mounts") or [])
            if isinstance(mount, dict) and mount.get("named_volume")
        ]
        copied = [p for p in (app.get("source_paths") or []) if "/volumes/" in str(p) and str(p).endswith("/_data")]
        db_named = [
            mount.get("source")
            for mount in (docker.get("mounts") or [])
            if isinstance(mount, dict)
            and mount.get("named_volume")
            and str(mount.get("purpose") or "") == "database-data"
        ]
        app_named = [name for name in named if name and name not in db_named]
        if app_named and not copied:
            missing.append("Docker named volume _data copy path")
    return {
        "restore_ready": "NO",
        "missing": missing or ["live backup not taken (Dry Run does not copy files or dump databases)"],
    }


def _probe_docker_schema_sizes(
    inventory: list[dict[str, Any]],
    *,
    run: Callable | None,
    details_override: dict[str, dict[str, Any]] | None,
    errors: list[str],
) -> None:
    if run is None or details_override is not None:
        return
    for row in inventory:
        if row.get("system"):
            continue
        container = str(row.get("docker_container") or "").strip()
        name = str(row.get("name") or "").strip()
        if not container or not name:
            continue
        postgres = "postgres" in str(row.get("type") or "").lower()
        size_known = row.get("size_bytes") not in {None, 0} and row.get("table_count") not in {None}
        if size_known and row.get("dump_capable") is True:
            continue
        try:
            probed = docker_schema_details_for(run, container, name, engine=str(row.get("type") or ""))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Docker schema probe skipped for {name}: {exc}")
            row["size_probe"] = str(exc)
            row["dump_capable"] = False
            continue
        if probed.get("size_bytes") is not None:
            row["size_bytes"] = probed.get("size_bytes")
        if probed.get("table_count") is not None:
            row["table_count"] = probed.get("table_count")
        if probed.get("row_count") is not None:
            row["row_count"] = probed.get("row_count")
        row["size_probe"] = probed.get("probe") or ""
        row["dump_capable"] = bool(probed.get("dump_capable"))
        row["dump_probe"] = probed.get("dump_probe") or ""
        row["dump_method"] = probed.get("dump_method") or ""
        if probed.get("engine"):
            row["type"] = probed.get("engine")
        if probed.get("postgres_user"):
            row["postgres_user"] = probed.get("postgres_user")
        if probed.get("postgres_version"):
            row["engine_version"] = probed.get("postgres_version")
        if probed.get("tools"):
            row["dump_tools"] = probed.get("tools")
        if probed.get("size_bytes") is None:
            engine = str(row.get("type") or "database")
            errors.append(
                f"Docker database {name} in {container}: size still unknown ({probed.get('probe') or 'probe failed'}). "
                f"Host serverbackup MySQL grants do not apply inside this container; dump uses docker exec "
                f"{'psql/pg_dump' if 'postgres' in engine.lower() else 'mysql/mysqldump'}."
            )


def scan_coverage(
    *,
    nginx_ok: bool,
    docker_containers: list[dict[str, Any]],
    proxy_routes: list[dict[str, Any]],
    errors: list[str],
    extra_files: dict[str, str] | None,
) -> dict[str, Any]:
    unreadable: list[str] = []
    existing_roots: list[str] = []
    unreadable_files: list[str] = []
    if extra_files is None:
        for root in (*DOKPLOY_SCAN_ROOTS, *TRAEFIK_SCAN_ROOTS, *APACHE_SCAN_ROOTS):
            path = Path(root)
            try:
                if path.exists():
                    existing_roots.append(root)
                    if not os.access(path, os.R_OK):
                        unreadable.append(root)
            except OSError:
                unreadable.append(root)
        unreadable_files = unreadable_live_proxy_files()
    incomplete = []
    if not nginx_ok:
        incomplete.append("nginx -T failed or returned no server blocks")
    if extra_files is None and not docker_containers and not any("docker" in str(err).lower() for err in errors):
        incomplete.append("docker inspect returned no containers")
    live_unreadable = [
        root
        for root in unreadable
        if any(hint in root.replace("\\", "/").lower() for hint in LIVE_PROXY_PATH_HINTS)
    ]
    live_routes = [route for route in proxy_routes if route.get("live_proxy") and not route.get("migration")]
    harvested_from_docker = any(
        str(route.get("source_file") or "").startswith(("traefik-api:", "docker-exec:"))
        for route in live_routes
    )
    if live_unreadable and not harvested_from_docker:
        incomplete.append("unreadable live Traefik/Dokploy scan roots: " + ", ".join(live_unreadable))
    if extra_files is None and unreadable_files and not live_routes:
        incomplete.append(
            "Traefik/Dokploy dynamic files exist but are unreadable by this account: "
            + ", ".join(unreadable_files[:12])
        )
    proxy_containers = []
    for item in docker_containers:
        summary = _docker_summary(item)
        if _looks_like_proxy_container(summary) and summary.get("running") is not False:
            proxy_containers.append(summary)
    if extra_files is None and proxy_containers and not live_routes:
        names = ", ".join(str(item.get("name") or "") for item in proxy_containers if item.get("name"))
        incomplete.append(
            "Dokploy/Traefik is running ("
            + names
            + ") but no live Host() routes were readable from host files, Traefik API, or docker exec"
        )
    return {
        "nginx_ok": nginx_ok,
        "docker_containers": len(docker_containers),
        "traefik_routes": len(proxy_routes),
        "existing_scan_roots": existing_roots,
        "unreadable_scan_roots": unreadable,
        "unreadable_live_proxy_files": unreadable_files,
        "incomplete_reasons": incomplete,
        "complete": not incomplete,
    }


def _dedupe_hostname_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("hostname") or "").lower(),
            str(row.get("role") or ""),
            str(row.get("key") or row.get("source") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _collect_hostname_records(
    docker_containers: list[dict[str, Any]],
    proxy_routes: list[dict[str, Any]],
    applications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for inspect in docker_containers:
        summary = _docker_summary(inspect)
        rows.extend(summary.get("hostname_mentions") or [])
        if _looks_like_infrastructure_container(summary):
            for name in summary.get("hostnames") or []:
                rows.append(
                    {
                        "hostname": name,
                        "role": HOSTNAME_ROLE_INFRASTRUCTURE,
                        "routing": False,
                        "source": "docker infrastructure",
                        "container": summary.get("name") or "",
                        "key": "compose",
                        "evidence": f"infrastructure container {summary.get('name')}",
                    }
                )
    for route in proxy_routes:
        for name in route.get("hostnames") or []:
            role = HOSTNAME_ROLE_INFRASTRUCTURE if is_infrastructure_hostname(str(name)) else HOSTNAME_ROLE_ROUTING
            rows.append(
                {
                    "hostname": name,
                    "role": role,
                    "routing": role == HOSTNAME_ROLE_ROUTING,
                    "source": "traefik Host()",
                    "container": "",
                    "key": "Host()",
                    "evidence": str(route.get("source_file") or "")[:240],
                }
            )
    claimed = {str(name).lower() for app in applications for name in (app.get("hostnames") or []) if name}
    mention_roles, advertised_hosts = _hostname_roles_from_containers(docker_containers)
    for row in rows:
        host = str(row.get("hostname") or "").lower()
        if host in claimed and row.get("role") in {HOSTNAME_ROLE_ROUTING, HOSTNAME_ROLE_ADVERTISED, HOSTNAME_ROLE_ALIAS}:
            row["assigned_website"] = True
        else:
            row["assigned_website"] = False
        if (
            not row["assigned_website"]
            and row.get("role") == HOSTNAME_ROLE_ROUTING
            and _config_only_hostname(host, mention_roles, advertised_hosts)
        ):
            config_roles = mention_roles.get(host) or set()
            if HOSTNAME_ROLE_PLACEHOLDER in config_roles:
                row["role"] = HOSTNAME_ROLE_PLACEHOLDER
            elif HOSTNAME_ROLE_EXTERNAL in config_roles:
                row["role"] = HOSTNAME_ROLE_EXTERNAL
            else:
                row["role"] = HOSTNAME_ROLE_CONFIG
            row["routing"] = False
            row["evidence"] = (
                str(row.get("evidence") or "")
                + " | Host() is a config/placeholder/external string, not a website folder"
            )
    return _dedupe_hostname_records(rows)


def _attach_advertised_aliases(applications: list[dict[str, Any]], docker_containers: list[dict[str, Any]]) -> None:
    """PUBLIC_HOST/SITE_URL become aliases of the same compose project, not new websites."""
    by_project: dict[str, dict[str, Any]] = {}
    for app in applications:
        docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
        project = str(docker.get("compose_project") or "").lower()
        if project:
            by_project.setdefault(project, app)
    for inspect in docker_containers:
        summary = _docker_summary(inspect)
        project = str(summary.get("compose_project") or "").lower()
        if not project:
            continue
        app = by_project.get(project)
        if not app:
            continue
        advertised = [n for n in (summary.get("advertised_hostnames") or []) if looks_like_hostname(str(n))]
        if not advertised:
            continue
        names = list(app.get("hostnames") or [])
        details = dict(app.get("hostname_details") or {})
        docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
        docker_adv = list(docker.get("advertised_hostnames") or [])
        for name in advertised:
            if name not in names:
                names.append(name)
                details[name] = {
                    "source_file": summary.get("compose_files") or "docker env",
                    "root": app.get("root") or "",
                    "alias": [],
                    "proxy_pass": list(app.get("proxy_pass") or []),
                    "redirect_to": "",
                    "listen": [],
                    "role": HOSTNAME_ROLE_ADVERTISED,
                }
            if name not in docker_adv:
                docker_adv.append(name)
        docker["advertised_hostnames"] = docker_adv
        app["docker"] = docker
        app["hostnames"] = names
        app["hostname_details"] = details
        app["hostname"] = _canonical_hostname(
            names,
            routed=list(docker.get("hostnames") or names),
            advertised=docker_adv,
        )
        notes = list(app.get("notes") or [])
        note = (
            "Advertised PUBLIC_HOST/SITE_URL values on this compose project are aliases of the "
            "same application, not independent websites."
        )
        if note not in notes:
            notes.append(note)
        app["notes"] = notes


def attach_infrastructure_databases(
    docker_containers: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    applications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dokploy/Traefik PostgreSQL/MariaDB is infrastructure recovery data, not a website database."""
    seen = {str(row.get("name") or "") for row in inventory}
    claimed_projects = {
        str((app.get("docker") or {}).get("compose_project") or "").lower()
        for app in applications
        if isinstance(app.get("docker"), dict)
    }
    extra: list[dict[str, Any]] = []
    for inspect in docker_containers:
        summary = _docker_summary(inspect)
        if not _looks_like_db_container(summary) and not (
            _looks_like_infrastructure_container(summary) and (summary.get("postgres_db") or summary.get("mysql_database"))
        ):
            continue
        project = str(summary.get("compose_project") or "").lower()
        if project in claimed_projects and not _looks_like_infrastructure_container(summary):
            continue
        if not _looks_like_infrastructure_container(summary) and project not in {"dokploy"}:
            continue
        name = str(summary.get("postgres_db") or summary.get("mysql_database") or "").strip()
        if not name or name in seen:
            continue
        db_type = "PostgreSQL" if summary.get("postgres_db") else "MariaDB"
        container = str(summary.get("name") or "")
        extra.append(
            {
                "name": name,
                "type": db_type,
                "system": False,
                "size_bytes": None,
                "table_count": None,
                "application_id": f"infrastructure:{project or container}",
                "status": "ASSOCIATED WITH INFRASTRUCTURE",
                "reason": (
                    f"{db_type} schema {name} belongs to infrastructure compose project "
                    f"{project or container}, not a public website. "
                    "Dumped under _server/infrastructure/databases for disaster recovery."
                ),
                "docker_container": container,
                "infrastructure": True,
                "dump_method": (
                    f"docker exec {container} pg_dump -U $POSTGRES_USER --format=plain --no-owner --no-acl {name}"
                    if db_type == "PostgreSQL"
                    else f"docker exec {container} mysqldump --databases {name}"
                ),
                "dump_destination": f"_server/infrastructure/databases/{name}.sql",
                "references": [{"path": f"docker:{container}", "kind": "infrastructure-db"}],
            }
        )
        seen.add(name)
    return list(inventory) + extra


def assemble_discovery(
    *,
    servers: list[dict[str, Any]],
    docker_containers: list[dict[str, Any]] | None = None,
    mariadb: list[str] | None = None,
    apache_servers: list[dict[str, Any]] | None = None,
    extra_scan_files: dict[str, str] | None = None,
    extra_config_texts: dict[str, str] | None = None,
    previous_hostnames: list[str] | None = None,
    details_override: dict[str, dict[str, Any]] | None = None,
    probe: Callable | None = None,
    path_exists: Callable[[str], bool] | None = None,
    run: Callable | None = None,
    mysql_defaults: Callable | None = None,
    nginx_ok: bool = True,
    hostname: str = "",
    errors: list[str] | None = None,
    backend_owners: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile nginx -T, Docker labels, Apache, compose, and leftover configs."""
    errors = list(errors or [])
    docker_containers = list(docker_containers or [])
    mariadb = list(mariadb or [])
    apache_servers = list(apache_servers or [])
    if backend_owners is None and run is not None:
        try:
            backend_owners = resolve_backend_owners(run)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"listening-socket backend resolution skipped: {exc}")
            backend_owners = {}
    backend_owners = backend_owners or {}
    apps = applications_from_servers(
        servers,
        probe=probe,
        docker_containers=docker_containers,
        mariadb=mariadb,
        path_exists=path_exists,
        backend_owners=backend_owners,
    )
    docker_apps, docker_leftovers = applications_from_unmatched_docker(
        apps,
        docker_containers,
        probe=probe,
        path_exists=path_exists,
    )
    if docker_apps:
        apps = _merge_candidates(list(apps) + docker_apps)
    apache_apps = applications_from_apache_servers(
        apache_servers,
        apps,
        docker_containers=docker_containers,
        probe=probe,
        path_exists=path_exists,
    )
    if apache_apps:
        apps = _merge_candidates(list(apps) + apache_apps)
    proxy_routes: list[dict[str, Any]] = []
    try:
        proxy_routes = scan_proxy_routes(
            extra_scan_files,
            run=run,
            docker_containers=docker_containers,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Traefik/Dokploy file scan warning: {exc}")
    traefik_apps, compose_leftovers = applications_from_traefik_routes(
        apps,
        proxy_routes,
        docker_containers,
        probe=probe,
        path_exists=path_exists,
    )
    if traefik_apps:
        apps = _merge_candidates(list(apps) + traefik_apps)
    _attach_advertised_aliases(apps, docker_containers)
    apps = _merge_candidates(apps)
    acme_hosts: dict[str, list[str]] = {}
    try:
        acme_hosts = scan_acme_hostnames(
            extra_scan_files,
            run=run,
            docker_containers=docker_containers,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"acme.json scan warning: {exc}")
    _attach_acme_ssl(apps, acme_hosts)
    claimed = {str(name).lower() for app in apps for name in (app.get("hostnames") or []) if name}
    for path, names in acme_hosts.items():
        unused = [name for name in names if name.lower() not in claimed and not is_infrastructure_hostname(name)]
        if not unused:
            continue
        compose_leftovers.append(
            {
                "hostname": unused[0],
                "hostnames": unused,
                "in_active_nginx": False,
                "verdict": "NOT ACTIVE IN CURRENT SERVER CONFIGURATION",
                "classification": CLASSIFICATION_UNRESOLVED,
                "evidence": [
                    {
                        "source": "traefik-acme",
                        "file": path,
                        "detail": "certificate domain in acme.json; no live Traefik Host() or nginx server_name matched",
                        "root": "",
                        "enabled": False,
                    }
                ],
            }
        )
    details: dict[str, dict[str, Any]] = dict(details_override or {})
    if mariadb and details_override is None and run is not None and mysql_defaults is not None:
        try:
            details = mariadb_schema_details(run, mysql_defaults, mariadb)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"MariaDB schema details skipped: {exc}")
    search_roots = [str(app.get("root") or "") for app in apps if app.get("root")]
    extra_texts = dict(extra_config_texts or {})
    extra_texts.update(docker_database_texts(docker_containers))
    try:
        references = find_database_references(mariadb, search_roots, extra_texts=extra_texts)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"database reference search skipped: {exc}")
        references = {}
    if mariadb and details_override is None and run is not None and mysql_defaults is not None:
        unassociated_names = [
            name
            for name in mariadb
            if name not in {"information_schema", "performance_schema", "mysql", "sys"}
            and not any(str(app.get("database_name") or "") == name for app in apps)
            and not (
                references.get(name)
                and any(
                    str(app.get("root") or "")
                    and str(item.get("path") or "").startswith(str(app.get("root") or ""))
                    for app in apps
                    for item in (references.get(name) or [])
                )
            )
        ]
        for name in unassociated_names:
            try:
                inspected = inspect_database_contents(run, mysql_defaults, name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"MariaDB inspect skipped for a database: {exc}")
                continue
            details.setdefault(name, {})
            details[name].update(inspected)
            if inspected.get("tables") and details[name].get("table_count") in {None, 0}:
                details[name]["table_count"] = len(inspected.get("tables") or [])
    account: dict[str, Any] = {}
    if run is not None and mysql_defaults is not None:
        try:
            account = mariadb_account_info(run, mysql_defaults)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"MariaDB account probe skipped: {exc}")
    database_inventory = build_database_inventory(mariadb, apps, details=details, references=references)
    database_inventory = attach_docker_only_databases(apps, database_inventory, mariadb)
    database_inventory = attach_infrastructure_databases(docker_containers, database_inventory, apps)
    _probe_docker_schema_sizes(
        database_inventory,
        run=run,
        details_override=details_override,
        errors=errors,
    )
    by_id = {str(app.get("application_id") or ""): app for app in apps}
    db_by_app: dict[str, dict[str, Any]] = {}
    db_by_name: dict[str, dict[str, Any]] = {}
    for row in database_inventory:
        ident = str(row.get("application_id") or "")
        app = by_id.get(ident)
        if app and row.get("name") and not app.get("database_name") and str(row.get("status") or "").startswith("ASSOCIATED") and "INFRASTRUCTURE" not in str(row.get("status") or ""):
            app["database_name"] = row["name"]
            app["database_type"] = row.get("type") or "MariaDB"
        if ident:
            db_by_app[ident] = row
        if row.get("name"):
            db_by_name[str(row.get("name"))] = row
        if not row.get("dump_destination"):
            if row.get("infrastructure") or "INFRASTRUCTURE" in str(row.get("status") or ""):
                row["dump_destination"] = f"_server/infrastructure/databases/{row.get('name')}.sql"
            elif app:
                row["dump_destination"] = f"{app.get('hostname') or 'website'}/database/{row.get('name')}.sql"
            elif str(row.get("status") or "").startswith("RECOVERY"):
                row["dump_destination"] = f"_recovery/databases/{row.get('name')}.sql"
    for app in apps:
        app["database_status"] = _database_status_for_app(app)
        db_row = db_by_app.get(str(app.get("application_id") or "")) or db_by_name.get(str(app.get("database_name") or ""))
        app["restore"] = _restore_ready_for_app(app, db_row)
    docker_hosts: list[str] = []
    for inspect in docker_containers:
        summary = _docker_summary(inspect)
        docker_hosts.extend(str(name) for name in (summary.get("hostnames") or []) if name)
    active_hosts = parsed_hostnames(servers)
    for app in apps:
        for name in app.get("hostnames") or []:
            if name and name not in active_hosts:
                active_hosts.append(str(name))
    try:
        inactive_hostnames = scan_inactive_hostnames(
            active_hosts,
            previous_hostnames=previous_hostnames,
            parse_nginx_t=parse_nginx_t,
            extra_files=extra_scan_files,
            docker_hint_hostnames=docker_hosts,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"inactive hostname scan skipped: {exc}")
        inactive_hostnames = []
    leftover_index = {str(row.get("hostname") or "").lower(): row for row in inactive_hostnames}
    for extra in [*docker_leftovers, *compose_leftovers]:
        key = str(extra.get("hostname") or "").lower()
        if not key:
            continue
        if key in leftover_index:
            evidence = leftover_index[key].setdefault("evidence", [])
            for item in extra.get("evidence") or []:
                if item not in evidence:
                    evidence.append(item)
            leftover_index[key]["classification"] = extra.get("classification") or CLASSIFICATION_LEGACY
        else:
            inactive_hostnames.append(extra)
            leftover_index[key] = extra
    postgres = sorted(
        {
            str(app.get("database_name"))
            for app in apps
            if app.get("database_type") == "PostgreSQL" and app.get("database_name")
        }
    )
    volumes = inventory_docker_volumes(docker_containers, apps)
    nginx_rows = nginx_inventory(servers)
    hostname_records = _collect_hostname_records(docker_containers, proxy_routes, apps)
    classified = classify_discovered_items(
        applications=apps,
        inactive_hostnames=inactive_hostnames,
        volumes=volumes,
        database_inventory=database_inventory,
        nginx_inventory=nginx_rows,
        hostname_records=hostname_records,
    )
    sources = sorted(
        {
            str(src)
            for app in apps
            for src in (app.get("discovery_sources") or [app.get("discovery_source") or "nginx -T"])
            if src
        }
    )
    unique_websites = [
        app
        for app in apps
        if app.get("classification") != CLASSIFICATION_EXCLUDED
        and not app.get("unused_default_root")
        and app.get("change") not in {"removed", "migrated"}
    ]
    return {
        "ok": bool(nginx_ok or apps),
        "hostname": hostname or socket.gethostname(),
        "discovery_source": " + ".join(sources) if sources else "nginx -T",
        "nginx_ok": nginx_ok,
        "applications": apps,
        "servers": servers,
        "nginx_inventory": nginx_rows,
        "parsed_hostnames": parsed_hostnames(servers),
        "inactive_hostnames": inactive_hostnames,
        "database_inventory": database_inventory,
        "database_account": account,
        "databases": {"mariadb": mariadb, "postgresql": postgres},
        "docker_projects": sorted(
            {
                str((app.get("docker") or {}).get("compose_project"))
                for app in apps
                if (app.get("docker") or {}).get("compose_project")
            }
        ),
        "docker_volumes": volumes,
        "classified": classified,
        "hostname_records": hostname_records,
        "infrastructure": [
            row
            for row in hostname_records
            if row.get("role") == HOSTNAME_ROLE_INFRASTRUCTURE
        ],
        "proxy_routes": proxy_routes,
        "backend_owners": backend_owners,
        "acme_hostnames": acme_hosts,
        "scan_coverage": scan_coverage(
            nginx_ok=nginx_ok,
            docker_containers=docker_containers,
            proxy_routes=proxy_routes,
            errors=errors,
            extra_files=extra_scan_files,
        ),
        "discovery_totals": discovery_totals(
            applications=apps,
            classified=classified,
            volumes=volumes,
            database_inventory=database_inventory,
            nginx_inventory=nginx_rows,
            unique_websites=unique_websites,
        ),
        "errors": errors,
    }


def discovery_totals(
    *,
    applications: list[dict[str, Any]],
    classified: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    database_inventory: list[dict[str, Any]],
    nginx_inventory: list[dict[str, Any]],
    unique_websites: list[dict[str, Any]],
) -> dict[str, int]:
    host_rows = [row for row in classified if row.get("kind") == "hostname"]
    live_apps = [app for app in applications if app.get("change") not in {"removed", "migrated"}]
    docker_apps = [app for app in live_apps if app.get("docker")]
    https_sites = [app for app in unique_websites if app.get("https") or (isinstance(app.get("ssl"), dict) and app.get("ssl", {}).get("https"))]
    dbs = [row for row in database_inventory if not row.get("system")]
    unresolved_volumes = [row for row in volumes if str(row.get("classification") or "").startswith("UNRESOLVED")]
    return {
        "hostnames_discovered": len(host_rows),
        "unique_websites": len(unique_websites),
        "applications": len(live_apps),
        "databases": len(dbs),
        "docker_applications": len(docker_apps),
        "docker_volumes": len(volumes),
        "nginx_server_blocks": len(nginx_inventory),
        "https_sites": len(https_sites),
        "unresolved_volumes": len(unresolved_volumes),
        "hostname_investigations": len([row for row in classified if row.get("kind") == "hostname-investigation"]),
    }


def attach_docker_only_databases(
    applications: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    host_names: list[str],
) -> list[dict[str, Any]]:
    """Associate compose MYSQL_DATABASE / POSTGRES_DB names that exist only inside a db container."""
    host = {str(name) for name in host_names if name}
    seen = {str(row.get("name") or "") for row in inventory}
    extra: list[dict[str, Any]] = []
    for app in applications:
        docker = app.get("docker") if isinstance(app.get("docker"), dict) else {}
        name = str(app.get("database_name") or docker.get("mysql_database") or docker.get("postgres_db") or "").strip()
        container = inferred_db_container(docker)
        db_type = str(app.get("database_type") or "")
        if docker.get("postgres_db") and name == str(docker.get("postgres_db") or ""):
            db_type = "PostgreSQL"
        elif not db_type:
            db_type = "MariaDB"
        if not name or name in host or name in seen:
            continue
        if not container:
            continue
        extra.append(
            {
                "name": name,
                "type": db_type,
                "system": False,
                "size_bytes": None,
                "table_count": None,
                "application_id": app.get("application_id") or "",
                "status": "ASSOCIATED WITH APPLICATION",
                "reason": (
                    f"schema lives in Docker container {container}; not present on host {db_type}. "
                    f"Dump uses docker exec with container credentials "
                    f"({'psql/pg_dump' if db_type == 'PostgreSQL' else 'mysql/mysqldump'}), "
                    "not the host serverbackup MariaDB account."
                ),
                "docker_container": container,
                "dump_method": (
                    f"docker exec {container} pg_dump -U $POSTGRES_USER --format=plain --no-owner --no-acl {name}"
                    if db_type == "PostgreSQL"
                    else f"docker exec {container} mysqldump --databases {name}"
                ),
                "dump_destination": f"{app.get('hostname') or 'website'}/database/{name}.sql",
                "references": [{"path": f"docker:{container}", "kind": "docker-db"}],
            }
        )
        seen.add(name)
    return list(inventory) + extra


def discover_applications(payload: dict | None = None, *, run=None, mysql_defaults=None) -> dict[str, Any]:
    """Collect a read-only inventory from every web-serving source on the host."""
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
    apache_servers: list[dict[str, Any]] = []
    try:
        apache_servers = scan_apache_servers(extra_scan_files)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Apache scan skipped: {exc}")
    return assemble_discovery(
        servers=servers,
        docker_containers=docker_containers,
        mariadb=mariadb,
        apache_servers=apache_servers,
        extra_scan_files=extra_scan_files,
        extra_config_texts=extra_config_texts,
        previous_hostnames=previous_hostnames,
        details_override=details_override,
        run=run,
        mysql_defaults=mysql_defaults,
        nginx_ok=nginx_ok,
        errors=errors,
    )


def handle(action: str, payload: dict, *, run=None, mysql_defaults=None) -> dict[str, Any]:
    if action != "discover-applications":
        return {"ok": False, "error": f"unhandled discovery action {action}"}
    return discover_applications(payload, run=run, mysql_defaults=mysql_defaults)
