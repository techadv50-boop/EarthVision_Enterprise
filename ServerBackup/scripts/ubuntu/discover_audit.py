"""Read-only database association and inactive-hostname evidence.

Never modifies MariaDB, Nginx, application files, or sudoers.
Never hardcodes production hostnames or database names.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

SYSTEM_DATABASES = {"information_schema", "performance_schema", "mysql", "sys"}
SECRET_LINE = re.compile(r"(password|passwd|secret|api_key|private_key|identified by)", re.IGNORECASE)
GENERIC_DB = re.compile(
    r"""(?:['"]DB_NAME['"]\s*,\s*['"]([A-Za-z0-9_]+)['"]"""
    r"""|^\s*(?:DB_NAME|MYSQL_DATABASE|DATABASE_NAME|POSTGRES_DB|dbname)\s*=\s*['"]?([A-Za-z0-9_]+)"""
    r"""|['"]database['"]\s*=>\s*['"]([A-Za-z0-9_]+)['"])""",
    re.IGNORECASE | re.MULTILINE,
)
CONFIG_FILENAMES = {
    "wp-config.php",
    "config.inc.php",
    ".env",
    ".env.local",
    ".env.production",
    "config.php",
    "database.php",
    "settings.php",
    "configuration.php",
    "local.xml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
}
NGINX_SCAN_ROOTS = (
    "/etc/nginx/sites-available",
    "/etc/nginx/sites-enabled",
    "/etc/nginx/conf.d",
    "/etc/nginx/snippets",
)
OTHER_SCAN_ROOTS = (
    "/etc/apache2/sites-available",
    "/etc/apache2/sites-enabled",
    "/etc/httpd/conf.d",
    "/etc/httpd/conf",
    "/etc/cloudflared",
    "/usr/local/etc/cloudflared",
    "/etc/caddy",
    "/etc/traefik",
)
SKIP_DIR_NAMES = {
    "node_modules",
    "vendor",
    ".git",
    "cache",
    "uploads",
    "wp-content",
    "__pycache__",
}


def parse_generic_database_name(text: str) -> str | None:
    match = GENERIC_DB.search(text or "")
    if not match:
        return None
    for group in match.groups():
        if group and group.lower() not in {"password", "passwd", "secret", "user", "username"}:
            return group
    return None


def parse_generic_database_from_texts(texts: dict[str, str]) -> str | None:
    for name in ("wp-config.php", "config.inc.php", ".env", "config.php", "database.php", "settings.php"):
        found = parse_generic_database_name(texts.get(name) or "")
        if found:
            return found
    for text in texts.values():
        found = parse_generic_database_name(text)
        if found:
            return found
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def mariadb_schema_details(run: Callable, mysql_defaults: Callable, names: list[str]) -> dict[str, dict[str, Any]]:
    """Size, table count, and timestamps from information_schema. Read-only."""
    wanted = [n for n in names if n and n not in SYSTEM_DATABASES]
    if not wanted:
        return {}
    quoted = ",".join("'" + n.replace("'", "") + "'" for n in wanted)
    sql = (
        "SELECT table_schema, "
        "COALESCE(SUM(data_length + index_length), 0), "
        "COUNT(*), "
        "MIN(create_time), "
        "MAX(update_time) "
        "FROM information_schema.tables "
        f"WHERE table_schema IN ({quoted}) "
        "GROUP BY table_schema"
    )
    try:
        result = run(
            ["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "--raw", "-e", sql],
            timeout=30,
        )
    except Exception:
        return {}
    if result.returncode != 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in (result.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        out[name] = {
            "size_bytes": _safe_int(parts[1]),
            "table_count": _safe_int(parts[2]),
            "created": (parts[3].strip() if len(parts) > 3 else "") or "",
            "updated": (parts[4].strip() if len(parts) > 4 else "") or "",
        }
    for name in wanted:
        out.setdefault(name, {"size_bytes": 0, "table_count": 0, "created": "", "updated": ""})
    grants = _backup_account_grants(run, mysql_defaults)
    for name, row in out.items():
        row["grants"] = [g for g in grants if name.lower() in g.lower() or "*.*" in g or "ALL PRIVILEGES" in g.upper()]
        if not row["grants"] and grants:
            row["grants"] = ["(no schema-specific GRANT visible for backup account)"]
    return out


def _backup_account_grants(run: Callable, mysql_defaults: Callable) -> list[str]:
    try:
        result = run(["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "-e", "SHOW GRANTS"], timeout=20)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    lines = []
    for raw in (result.stdout or "").splitlines():
        text = SECRET_LINE.sub("***", raw.strip())
        text = re.sub(r"IDENTIFIED BY\s+'[^']*'", "IDENTIFIED BY '***'", text, flags=re.IGNORECASE)
        if text:
            lines.append(text)
    return lines


def collect_config_texts(root: str, *, limit: int = 40) -> dict[str, str]:
    texts: dict[str, str] = {}
    base = Path(root)
    if not root or not base.is_dir():
        return texts
    count = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        depth = Path(dirpath).relative_to(base).parts
        if len(depth) > 3:
            dirnames[:] = []
            continue
        for filename in filenames:
            if filename not in CONFIG_FILENAMES:
                continue
            path = Path(dirpath) / filename
            rel = str(path)
            try:
                texts[rel] = path.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                texts[rel] = ""
            count += 1
            if count >= limit:
                return texts
    return texts


def find_database_references(
    names: Iterable[str],
    search_roots: Iterable[str],
    *,
    extra_texts: dict[str, str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Locate database names in application/config files. File paths only; no secrets."""
    wanted = [n for n in names if n and n not in SYSTEM_DATABASES]
    hits: dict[str, list[dict[str, str]]] = {name: [] for name in wanted}
    texts = dict(extra_texts or {})
    for root in search_roots:
        if not root:
            continue
        texts.update(collect_config_texts(root))
    for path, body in texts.items():
        if SECRET_LINE.search(Path(path).name):
            continue
        for name in wanted:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", body or ""):
                hits[name].append({"path": path, "kind": Path(path).name})
    return hits


def build_database_inventory(
    names: list[str],
    applications: list[dict[str, Any]],
    *,
    details: dict[str, dict[str, Any]] | None = None,
    references: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    details = details or {}
    references = references or {}
    associated_by_app: dict[str, str] = {}
    for app in applications:
        dname = str(app.get("database_name") or "").strip()
        if not dname:
            continue
        ident = str(app.get("application_id") or app.get("hostname") or "")
        associated_by_app.setdefault(dname, ident)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        system = name in SYSTEM_DATABASES
        meta = dict(details.get(name) or {})
        refs = list(references.get(name) or [])
        app_id = associated_by_app.get(name) or ""
        if not app_id:
            for ref in refs:
                path = str(ref.get("path") or "")
                for app in applications:
                    root = str(app.get("root") or "").rstrip("/")
                    if root and (path == root or path.startswith(root + "/")):
                        app_id = str(app.get("application_id") or "")
                        break
                if app_id:
                    break
        table_count = meta.get("table_count")
        if system:
            status = "SYSTEM DATABASE — EXCLUDED"
            reason = "MariaDB system schema"
        elif app_id:
            status = "ASSOCIATED WITH APPLICATION"
            reason = f"referenced by {app_id}"
        elif table_count == 0:
            status = "UNUSED/EMPTY DATABASE — EXCLUDED"
            reason = "zero tables; shown for review, not silently omitted"
        else:
            status = "UNASSOCIATED DATABASE — REQUIRES REVIEW"
            reason = "no application association discovered"
        rows.append(
            {
                "name": name,
                "type": "MariaDB",
                "system": system,
                "size_bytes": _safe_int(meta.get("size_bytes")),
                "table_count": table_count if table_count is not None else None,
                "created": meta.get("created") or "",
                "updated": meta.get("updated") or "",
                "grants": list(meta.get("grants") or []),
                "references": refs,
                "application_id": app_id,
                "status": status,
                "reason": reason,
            }
        )
    return rows


def _read_text_file(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _iter_scan_files(roots: Iterable[str], suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        if base.is_file():
            files.append(base)
            continue
        try:
            for path in base.rglob("*"):
                if path.is_file() and (path.suffix.lower() in suffixes or path.name.endswith(".conf")):
                    files.append(path)
        except OSError:
            continue
    return files


def scan_inactive_hostnames(
    active_hostnames: Iterable[str],
    *,
    previous_hostnames: Iterable[str] | None = None,
    parse_nginx_t: Callable[[str], list[dict[str, Any]]] | None = None,
    extra_files: dict[str, str] | None = None,
    docker_hint_hostnames: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Hostnames present in on-disk configs but not in active nginx -T.

    Does not add them as backup applications. Evidence only.
    """
    active = {str(name).lower() for name in active_hostnames if name}
    evidence: dict[str, dict[str, Any]] = {}

    def add(hostname: str, source: str, path: str, detail: str, **extra: Any) -> None:
        key = hostname.lower()
        if not hostname or key in active or key in {"", "*", "_", "localhost"}:
            return
        row = evidence.setdefault(
            key,
            {
                "hostname": hostname,
                "in_active_nginx": False,
                "evidence": [],
                "verdict": "NOT ACTIVE IN CURRENT SERVER CONFIGURATION",
            },
        )
        item = {"source": source, "file": path, "detail": detail, **extra}
        if item not in row["evidence"]:
            row["evidence"].append(item)

    files = dict(extra_files or {})
    if extra_files is None:
        for path in _iter_scan_files(NGINX_SCAN_ROOTS, (".conf", ".inc", "")):
            files[str(path)] = _read_text_file(path)
        for path in _iter_scan_files(OTHER_SCAN_ROOTS, (".conf", ".yml", ".yaml", ".json", ".toml")):
            files[str(path)] = _read_text_file(path)
        home_cf = Path.home() / ".cloudflared"
        if home_cf.is_dir():
            for path in home_cf.glob("*"):
                if path.is_file():
                    files[str(path)] = _read_text_file(path)

    parser = parse_nginx_t
    for path, body in files.items():
        lower_path = path.lower()
        source = "nginx-file"
        if "sites-available" in lower_path:
            source = "nginx-sites-available"
        elif "sites-enabled" in lower_path:
            source = "nginx-sites-enabled"
        elif "apache" in lower_path or "httpd" in lower_path:
            source = "apache"
        elif "cloudflare" in lower_path:
            source = "cloudflared"
        elif "caddy" in lower_path:
            source = "caddy"
        elif "traefik" in lower_path:
            source = "traefik"
        names: list[str] = []
        root = ""
        if parser and ("nginx" in source or path.endswith(".conf")):
            wrapped = f"# configuration file {path}:\nhttp {{\n{body}\n}}\n"
            try:
                for block in parser(wrapped) or []:
                    names.extend(block.get("server_name") or [])
                    if block.get("root") and not root:
                        root = str(block.get("root") or "")
            except Exception:
                names = []
        if not names:
            for match in re.finditer(r"(?im)^\s*(?:server_name|ServerName|hostname)\s+(.+?);?\s*$", body or ""):
                for item in match.group(1).replace(",", " ").split():
                    cleaned = item.strip().strip("'\"")
                    if cleaned and not cleaned.startswith("$"):
                        names.append(cleaned)
        enabled = "sites-enabled" in lower_path
        for hostname in names:
            add(
                hostname,
                source,
                path,
                "present in configuration file; not in active nginx -T",
                root=root,
                enabled=enabled,
            )

    for hostname in docker_hint_hostnames or []:
        add(str(hostname), "docker", "docker inspect", "hostname-like docker label/env; not in active nginx -T")

    previous = [str(n) for n in (previous_hostnames or []) if n]
    for hostname in previous:
        key = hostname.lower()
        if key in active:
            continue
        if key not in evidence:
            add(
                hostname,
                "previous-discovery",
                "",
                "seen in a previous discovery snapshot; not in active nginx -T or scanned configs",
            )

    return [evidence[key] for key in sorted(evidence)]
