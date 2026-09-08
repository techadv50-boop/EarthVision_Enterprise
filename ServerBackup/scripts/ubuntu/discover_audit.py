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
EXTRA_SEARCH_ROOTS = (
    "/opt",
    "/etc/systemd/system",
    "/etc/cron.d",
    "/etc/mysql",
    "/etc/nginx",
    "/root",
)
MYSQL_CNF = "/etc/serverbackup/my.cnf"
LEAST_PRIVILEGE_NOTE = (
    "Discovery and dump already use --defaults-extra-file=/etc/serverbackup/my.cnf. "
    "A dedicated least-privilege account (SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS) "
    "is already created by ubuntu-backup-setup.sh --mysql-user. Switching my.cnf user= off root "
    "does not require application code changes. Credentials were not modified."
)
IDENTIFYING_TABLE_HINTS = (
    "wp_posts",
    "wp_users",
    "wp_options",
    "wp_comments",
    "submissions",
    "publications",
    "journal_settings",
    "users",
    "sessions",
    "orders",
    "customers",
)


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


def configured_mysql_user(cnf_path: str = MYSQL_CNF) -> dict[str, Any]:
    """Read only the client user= line. Never returns the password."""
    path = Path(cnf_path)
    info = {"path": cnf_path, "file_present": path.is_file(), "configured_user": ""}
    if not path.is_file():
        return info
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return info
    in_client = True
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_client = stripped.lower() in {"[client]", "[mysql]"}
            continue
        if not in_client or not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.lower().startswith("password"):
            continue
        if stripped.lower().startswith("user"):
            _, _, value = stripped.partition("=")
            info["configured_user"] = value.strip().strip("\"'")
            break
    return info


def mariadb_account_info(run: Callable, mysql_defaults: Callable, *, cnf_path: str = MYSQL_CNF) -> dict[str, Any]:
    """Who discovery/dump actually connect as. No passwords."""
    configured = configured_mysql_user(cnf_path)
    current_user = ""
    session_user = ""
    try:
        result = run(
            [
                "mysql",
                *mysql_defaults(),
                "--batch",
                "--skip-column-names",
                "-e",
                "SELECT CURRENT_USER(), USER()",
            ],
            timeout=15,
        )
        if result.returncode == 0:
            parts = (result.stdout or "").strip().split("\t")
            current_user = parts[0].strip() if parts else ""
            session_user = parts[1].strip() if len(parts) > 1 else ""
    except Exception:
        pass
    grants = _backup_account_grants(run, mysql_defaults)
    configured_user = configured.get("configured_user") or ""
    using_root = any(
        str(item).split("@")[0].lower() == "root"
        for item in (configured_user, current_user, session_user)
        if item
    )
    source = configured["path"] if configured.get("file_present") else "(no /etc/serverbackup/my.cnf; mysql client defaults / unix_socket)"
    return {
        "configured_user": configured_user or "(not set in my.cnf)",
        "current_user": current_user,
        "session_user": session_user,
        "source": source,
        "file_present": bool(configured.get("file_present")),
        "using_root": using_root,
        "grants": grants,
        "least_privilege": LEAST_PRIVILEGE_NOTE,
        "defaults_extra_file": configured["path"] if configured.get("file_present") else "",
    }


def inspect_database_contents(
    run: Callable,
    mysql_defaults: Callable,
    name: str,
    *,
    table_limit: int = 40,
) -> dict[str, Any]:
    """Read-only table/row inventory. Does not SELECT application row contents."""
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    if not safe or safe != name:
        return {"tables": [], "row_count": 0, "column_names": [], "identifying_hints": []}
    sql = (
        "SELECT table_name, engine, table_rows, "
        "COALESCE(data_length + index_length, 0), table_comment "
        "FROM information_schema.tables "
        f"WHERE table_schema = '{safe}' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    )
    tables: list[dict[str, Any]] = []
    try:
        result = run(
            ["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "--raw", "-e", sql],
            timeout=20,
        )
    except Exception:
        return {"tables": [], "row_count": None, "column_names": [], "identifying_hints": []}
    if result.returncode != 0:
        return {"tables": [], "row_count": None, "column_names": [], "identifying_hints": []}
    for line in (result.stdout or "").splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        tables.append(
            {
                "name": parts[0].strip(),
                "engine": parts[1].strip() if len(parts) > 1 else "",
                "estimated_rows": _safe_int(parts[2] if len(parts) > 2 else 0),
                "size_bytes": _safe_int(parts[3] if len(parts) > 3 else 0),
                "comment": (parts[4].strip() if len(parts) > 4 else "")[:120],
                "rows": None,
            }
        )
        if len(tables) >= table_limit:
            break
    exact_total = 0
    exact_ok = True
    for table in tables:
        tname = "".join(ch for ch in str(table["name"]) if ch.isalnum() or ch == "_")
        if tname != table["name"]:
            exact_ok = False
            continue
        try:
            counted = run(
                [
                    "mysql",
                    *mysql_defaults(),
                    "--batch",
                    "--skip-column-names",
                    "-e",
                    f"SELECT COUNT(*) FROM `{safe}`.`{tname}`",
                ],
                timeout=15,
            )
        except Exception:
            exact_ok = False
            continue
        if counted.returncode != 0:
            exact_ok = False
            continue
        table["rows"] = _safe_int((counted.stdout or "").strip())
        exact_total += int(table["rows"] or 0)
    columns: list[str] = []
    try:
        col_sql = (
            "SELECT table_name, column_name FROM information_schema.columns "
            f"WHERE table_schema = '{safe}' ORDER BY table_name, ordinal_position"
        )
        col_result = run(
            ["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "-e", col_sql],
            timeout=15,
        )
        if col_result.returncode == 0:
            for line in (col_result.stdout or "").splitlines()[:80]:
                parts = line.split("\t")
                if len(parts) >= 2:
                    columns.append(f"{parts[0].strip()}.{parts[1].strip()}")
    except Exception:
        pass
    names = [str(item.get("name") or "") for item in tables]
    hints = [hint for hint in IDENTIFYING_TABLE_HINTS if any(hint.lower() in n.lower() for n in names)]
    return {
        "tables": tables,
        "row_count": exact_total if exact_ok else None,
        "column_names": columns,
        "identifying_hints": hints,
        "table_names": names,
    }


def _backup_account_grants(run: Callable, mysql_defaults: Callable) -> list[str]:
    try:
        result = run(["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "-e", "SHOW GRANTS"], timeout=20)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    lines = []
    for raw in (result.stdout or "").splitlines():
        text = raw.strip()
        text = re.sub(r"IDENTIFIED BY\s+(PASSWORD\s+)?('[^']*'|\"[^\"]*\"|\S+)", "IDENTIFIED BY '***'", text, flags=re.IGNORECASE)
        text = re.sub(r"(password|passwd)\s*=\s*\S+", "password=***", text, flags=re.IGNORECASE)
        if SECRET_LINE.search(text) and "GRANT" not in text.upper():
            text = SECRET_LINE.sub("***", text)
        if text:
            lines.append(text)
    return lines


def collect_config_texts(root: str, *, limit: int = 80) -> dict[str, str]:
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
            is_config = filename in CONFIG_FILENAMES
            is_php = filename.endswith(".php") and len(depth) <= 2
            is_unit = filename.endswith(".service") or filename.endswith(".env")
            if not (is_config or is_php or is_unit):
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


def docker_database_texts(containers: list[dict[str, Any]] | None) -> dict[str, str]:
    texts: dict[str, str] = {}
    for inspect in containers or []:
        config = inspect.get("Config") or {}
        name = str(inspect.get("Name") or inspect.get("Id") or "container").lstrip("/")
        env_lines = []
        for item in config.get("Env") or []:
            text = str(item)
            if any(
                text.startswith(prefix)
                for prefix in (
                    "MYSQL_DATABASE=",
                    "MARIADB_DATABASE=",
                    "MYSQL_DATABASE",
                    "POSTGRES_DB=",
                )
            ):
                env_lines.append(text)
        if env_lines:
            texts[f"docker:{name}"] = "\n".join(env_lines)
    return texts


def find_database_references(
    names: Iterable[str],
    search_roots: Iterable[str],
    *,
    extra_texts: dict[str, str] | None = None,
    extra_roots: Iterable[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Locate database names in application/config files. File paths only; no secrets."""
    wanted = [n for n in names if n and n not in SYSTEM_DATABASES]
    hits: dict[str, list[dict[str, str]]] = {name: [] for name in wanted}
    texts = dict(extra_texts or {})
    roots = [str(root) for root in search_roots if root]
    for root in extra_roots if extra_roots is not None else EXTRA_SEARCH_ROOTS:
        if root and root not in roots:
            roots.append(str(root))
    for root in roots:
        if not root:
            continue
        texts.update(collect_config_texts(root))
    for path, body in texts.items():
        if SECRET_LINE.search(Path(path).name):
            continue
        for name in wanted:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", body or ""):
                hits[name].append({"path": path, "kind": Path(path).name or path})
    return hits


def _row_count(meta: dict[str, Any]) -> int | None:
    if meta.get("row_count") is not None:
        try:
            return int(meta.get("row_count"))
        except (TypeError, ValueError):
            return None
    tables = meta.get("tables") or []
    if not tables:
        return None
    total = 0
    known = False
    for table in tables:
        if table.get("rows") is None:
            continue
        known = True
        total += _safe_int(table.get("rows"))
    return total if known else None


def finalize_database_verdict(row: dict[str, Any]) -> dict[str, Any]:
    """Classify unassociated databases. Never silently omit them."""
    status = str(row.get("status") or "")
    if row.get("system") or status.startswith("ASSOCIATED") or "UNUSED/EMPTY" in status:
        return row
    refs = list(row.get("references") or [])
    app_id = str(row.get("application_id") or "")
    rows = _row_count(row)
    table_count = row.get("table_count")
    if app_id:
        row["status"] = "ASSOCIATED WITH APPLICATION"
        row["reason"] = f"referenced by {app_id}"
        return row
    if table_count == 0:
        row["status"] = "UNUSED/EMPTY DATABASE — EXCLUDED"
        row["reason"] = "zero tables; shown for review, not silently omitted"
        return row
    if not refs and rows == 0:
        names = ", ".join(str(t.get("name") or "") for t in (row.get("tables") or [])[:12]) or "(none)"
        row["status"] = "EXCLUDED — UNUSED/LEGACY"
        row["reason"] = (
            "no application, Docker, or config reference; table row counts are zero; "
            f"leftover schema only ({names})"
        )
        return row
    table_list = ", ".join(str(t.get("name") or "") for t in (row.get("tables") or [])[:12])
    hints = ", ".join(str(h) for h in (row.get("identifying_hints") or [])[:8])
    extra = ""
    if table_list:
        extra += f" tables: {table_list}."
    if hints:
        extra += f" identifying table hints: {hints}."
    if rows is None:
        extra += " row counts were not available; not marked unused."
    elif rows:
        extra += f" contains {rows} rows of data."
    if refs:
        paths = ", ".join(str(item.get("path") or "") for item in refs if item.get("path"))
        extra += f" orphan config references (not under an active application): {paths}."
        row["status"] = "UNASSOCIATED DATABASE — REQUIRES REVIEW"
        row["reason"] = "referenced outside active applications;" + extra
        return row
    row["status"] = "UNASSOCIATED DATABASE — REQUIRES REVIEW"
    row["reason"] = "no application association discovered;" + extra
    return row


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
    app_roots: list[tuple[str, str]] = []
    for app in applications:
        ident = str(app.get("application_id") or app.get("hostname") or "")
        root = str(app.get("root") or "").rstrip("/")
        if root and ident:
            app_roots.append((root, ident))
        dname = str(app.get("database_name") or "").strip()
        if dname:
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
        app_refs: list[dict[str, str]] = []
        orphan_refs: list[dict[str, str]] = []
        if not app_id:
            for ref in refs:
                path = str(ref.get("path") or "")
                matched = ""
                if path.startswith("docker:"):
                    for app in applications:
                        if str(app.get("database_name") or "") == name:
                            matched = str(app.get("application_id") or "")
                            break
                else:
                    for root, ident in app_roots:
                        if root and (path == root or path.startswith(root + "/")):
                            matched = ident
                            break
                if matched:
                    app_id = app_id or matched
                    app_refs.append(ref)
                else:
                    orphan_refs.append(ref)
            refs = (app_refs + orphan_refs) if app_id else orphan_refs
        table_count = meta.get("table_count")
        row = {
            "name": name,
            "type": "MariaDB",
            "system": system,
            "size_bytes": _safe_int(meta.get("size_bytes")),
            "table_count": table_count if table_count is not None else None,
            "row_count": meta.get("row_count"),
            "created": meta.get("created") or "",
            "updated": meta.get("updated") or "",
            "grants": list(meta.get("grants") or []),
            "references": refs,
            "tables": list(meta.get("tables") or []),
            "column_names": list(meta.get("column_names") or []),
            "identifying_hints": list(meta.get("identifying_hints") or []),
            "application_id": app_id,
            "status": "",
            "reason": "",
        }
        if system:
            row["status"] = "SYSTEM DATABASE — EXCLUDED"
            row["reason"] = "MariaDB system schema"
        elif app_id:
            row["status"] = "ASSOCIATED WITH APPLICATION"
            row["reason"] = f"referenced by {app_id}"
        elif table_count == 0:
            row["status"] = "UNUSED/EMPTY DATABASE — EXCLUDED"
            row["reason"] = "zero tables; shown for review, not silently omitted"
        else:
            row["status"] = "UNASSOCIATED DATABASE — REQUIRES REVIEW"
            row["reason"] = "no application association discovered"
        rows.append(finalize_database_verdict(row))
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
