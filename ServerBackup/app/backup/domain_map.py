"""Map discovered applications to per-domain backup folders.

User-facing folder names are canonical hostnames (50sea.com), never Docker
IDs, volume names, hashes, or application_id strings. Databases are assigned
only from proven discovery associations — never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

CATCHALL_HOSTS = {"", "*", "_", "localhost"}
RESERVED_FOLDERS = {"_unassigned-databases", "_server", "backup-manifest.json"}
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
UNSAFE_FOLDER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CONFIG_BASENAMES = {
    "config.inc.php",
    "wp-config.php",
    "wp-config-sample.php",
    ".env",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}
BLOCKED_FILE_PREFIXES = (
    "/var/lib/docker",
    "/var/lib/containerd",
    "/proc",
    "/sys",
    "/dev",
    "/run",
)


@dataclass
class SiteDatabase:
    name: str
    db_type: str
    shared_with: list[str] = field(default_factory=list)
    include_unassigned: bool = False


@dataclass
class SiteSpec:
    domain: str
    folder: str
    application_id: str
    website_type: str
    application_root: str
    storage_roots: list[str]
    source_paths: list[str]
    config_paths: list[str]
    databases: list[SiteDatabase]
    docker: dict[str, Any] | None
    nginx_source_files: list[str]
    notes: list[str] = field(default_factory=list)
    hostnames: list[str] = field(default_factory=list)
    named_volumes: list[str] = field(default_factory=list)

    def all_file_roots(self) -> list[str]:
        roots: list[str] = []
        for path in [self.application_root, *self.storage_roots, *self.source_paths, *self.config_paths]:
            cleaned = _clean(path)
            if cleaned and cleaned not in roots and not cleaned.startswith("volume:"):
                roots.append(cleaned)
        return roots


@dataclass
class DomainMap:
    sites: list[SiteSpec]
    unassigned_databases: list[SiteDatabase]
    skipped: list[dict[str, str]]

    def site_by_folder(self, folder: str) -> SiteSpec | None:
        for site in self.sites:
            if site.folder == folder:
                return site
        return None

    def site_by_id(self, application_id: str) -> SiteSpec | None:
        ident = str(application_id or "")
        for site in self.sites:
            if site.application_id == ident:
                return site
        return None

    def mariadb_names(self) -> list[str]:
        names: list[str] = []
        for site in self.sites:
            for db in site.databases:
                if _is_mariadb(db.db_type) and db.name not in names:
                    names.append(db.name)
        return names

    def postgres_names(self) -> list[str]:
        names: list[str] = []
        for site in self.sites:
            for db in site.databases:
                if _is_postgres(db.db_type) and db.name not in names:
                    names.append(db.name)
        return names


def _clean(path: str) -> str:
    return str(path or "").replace("\\", "/").rstrip("/")


def _is_mariadb(db_type: str) -> bool:
    return str(db_type or "MariaDB").lower() in {"", "mariadb", "mysql"}


def _is_postgres(db_type: str) -> bool:
    return "postgres" in str(db_type or "").lower()


def _associated(status: str) -> bool:
    return str(status or "").upper().startswith("ASSOCIATED")


def _hostnames(app: dict[str, Any]) -> list[str]:
    names = [str(n) for n in (app.get("hostnames") or []) if n]
    primary = str(app.get("hostname") or "")
    if primary and primary not in names:
        names.insert(0, primary)
    return names


def canonical_domain(app: dict[str, Any]) -> str:
    names = [n for n in _hostnames(app) if n.lower() not in CATCHALL_HOSTS]
    if not names:
        return ""

    def sort_key(name: str) -> tuple[int, str]:
        lower = name.lower()
        return (1 if lower.startswith("www.") else 0, lower)

    return sorted(names, key=sort_key)[0]


def sanitize_domain_folder(domain: str) -> str:
    name = str(domain or "").strip().rstrip(".")
    name = UNSAFE_FOLDER.sub("_", name)
    name = name.replace("..", "_")
    if not name or name in {".", ".."}:
        raise ValueError(f"Refusing empty or relative domain folder {domain!r}")
    if name.lower() in WINDOWS_RESERVED:
        name = f"site-{name}"
    if name.lower() in RESERVED_FOLDERS or name.startswith("_"):
        name = f"site-{name.lstrip('_')}"
    return name


def _eligible_application(app: dict[str, Any]) -> bool:
    if not isinstance(app, dict):
        return False
    if app.get("change") == "removed":
        return False
    if app.get("excluded") or app.get("unused_default_root"):
        return False
    if "EXCLUDED" in str(app.get("status") or ""):
        return False
    if app.get("included") is False:
        return False
    domain = canonical_domain(app)
    if not domain:
        return False
    return True


def _storage_roots(app: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    application = _clean(str(app.get("root") or ""))
    files_dir = _clean(str(app.get("ojs_files_dir") or ""))
    if files_dir and files_dir != application:
        roots.append(files_dir)
    for path in app.get("persistent_data_paths") or []:
        cleaned = _clean(str(path))
        if not cleaned or cleaned.startswith("volume:"):
            continue
        if cleaned == application:
            continue
        if cleaned not in roots:
            roots.append(cleaned)
    return roots


def _config_paths(app: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    root = _clean(str(app.get("root") or ""))
    for raw in app.get("configuration_paths") or []:
        cleaned = _clean(str(raw))
        if cleaned and cleaned not in paths and not cleaned.startswith("volume:"):
            paths.append(cleaned)
    source_file = _clean(str(app.get("source_file") or ""))
    if source_file and source_file not in paths:
        paths.append(source_file)
    docker = app.get("docker") if isinstance(app.get("docker"), dict) else None
    if docker:
        compose = _clean(str(docker.get("compose_file") or docker.get("compose_files") or ""))
        if compose and compose not in paths:
            paths.append(compose)
    if root:
        for name in ("config.inc.php", "wp-config.php"):
            candidate = f"{root}/{name}"
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _named_volumes(app: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for path in app.get("persistent_data_paths") or []:
        raw = str(path or "")
        if raw.startswith("volume:"):
            name = raw.split(":", 1)[-1].strip()
            if name and name not in names:
                names.append(name)
    return names


def _nginx_files(app: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for raw in [app.get("source_file"), *(app.get("source_files") or []), *(app.get("configuration_paths") or [])]:
        cleaned = _clean(str(raw or ""))
        if cleaned and "/nginx" in cleaned and cleaned not in files:
            files.append(cleaned)
    return files


def _db_type_for(name: str, app: dict[str, Any], inventory_row: dict[str, Any] | None) -> str:
    if inventory_row and inventory_row.get("type"):
        return str(inventory_row.get("type"))
    if str(app.get("database_name") or "") == name and app.get("database_type"):
        return str(app.get("database_type"))
    return "MariaDB"


def build_domain_map(
    applications: list[dict[str, Any]] | None,
    database_inventory: list[dict[str, Any]] | None = None,
    *,
    approved_only: bool = True,
) -> DomainMap:
    apps = [row for row in (applications or []) if isinstance(row, dict)]
    inventory = [row for row in (database_inventory or []) if isinstance(row, dict)]
    skipped: list[dict[str, str]] = []
    used_folders: dict[str, int] = {}
    sites: list[SiteSpec] = []

    for app in apps:
        if approved_only and not _eligible_application(app):
            skipped.append(
                {
                    "application_id": str(app.get("application_id") or ""),
                    "hostname": str(app.get("hostname") or ""),
                    "reason": str(app.get("status") or app.get("change") or "not approved"),
                }
            )
            continue
        if not approved_only and (app.get("excluded") or app.get("unused_default_root") or app.get("change") == "removed"):
            continue
        domain = canonical_domain(app)
        if not domain:
            skipped.append(
                {
                    "application_id": str(app.get("application_id") or ""),
                    "hostname": str(app.get("hostname") or ""),
                    "reason": "no canonical domain",
                }
            )
            continue
        folder = sanitize_domain_folder(domain)
        if folder.lower() in used_folders:
            used_folders[folder.lower()] += 1
            folder = f"{folder}__{used_folders[folder.lower()]}"
        else:
            used_folders[folder.lower()] = 1
        ident = str(app.get("application_id") or "")
        source_paths = [_clean(str(p)) for p in (app.get("source_paths") or []) if _clean(str(p)) and not str(p).startswith("volume:")]
        sites.append(
            SiteSpec(
                domain=domain,
                folder=folder,
                application_id=ident,
                website_type=str(app.get("type") or "Other"),
                application_root=_clean(str(app.get("root") or "")),
                storage_roots=_storage_roots(app),
                source_paths=source_paths,
                config_paths=_config_paths(app),
                databases=[],
                docker=dict(app.get("docker")) if isinstance(app.get("docker"), dict) else None,
                nginx_source_files=_nginx_files(app),
                notes=[str(n) for n in (app.get("notes") or []) if n],
                hostnames=_hostnames(app),
                named_volumes=_named_volumes(app),
            )
        )

    by_id = {site.application_id: site for site in sites if site.application_id}
    claimed: dict[str, list[str]] = {}
    assigned_names: set[str] = set()

    for row in inventory:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if row.get("system") or "SYSTEM DATABASE" in str(row.get("status") or ""):
            continue
        if "EXCLUDED" in str(row.get("status") or "") and not _associated(str(row.get("status") or "")):
            continue
        ident = str(row.get("application_id") or "")
        site = by_id.get(ident)
        if site and _associated(str(row.get("status") or "")):
            site.databases.append(
                SiteDatabase(name=name, db_type=_db_type_for(name, {}, row))
            )
            claimed.setdefault(name, []).append(site.folder)
            assigned_names.add(name)

    for site in sites:
        app = next((row for row in apps if str(row.get("application_id") or "") == site.application_id), None)
        name = str((app or {}).get("database_name") or "").strip()
        if not name or name in {db.name for db in site.databases}:
            continue
        site.databases.append(
            SiteDatabase(
                name=name,
                db_type=str((app or {}).get("database_type") or "MariaDB"),
            )
        )
        claimed.setdefault(name, []).append(site.folder)
        assigned_names.add(name)

    for name, folders in claimed.items():
        unique = list(dict.fromkeys(folders))
        if len(unique) < 2:
            continue
        for site in sites:
            for db in site.databases:
                if db.name == name:
                    db.shared_with = [item for item in unique if item != site.folder]

    unassigned: list[SiteDatabase] = []
    for row in inventory:
        name = str(row.get("name") or "").strip()
        if not name or name in assigned_names:
            continue
        if row.get("system") or "SYSTEM DATABASE" in str(row.get("status") or ""):
            continue
        if "EXCLUDED" in str(row.get("status") or ""):
            continue
        unassigned.append(
            SiteDatabase(
                name=name,
                db_type=str(row.get("type") or "MariaDB"),
                include_unassigned=bool(row.get("include_unassigned"))
                or "INCLUDED — UNASSIGNED" in str(row.get("status") or ""),
            )
        )

    return DomainMap(sites=sites, unassigned_databases=unassigned, skipped=skipped)


def dump_names(
    domain_map: DomainMap,
    *,
    selected: list[str] | None = None,
    include_unassigned_selected: bool = True,
) -> tuple[list[str], list[str]]:
    """MariaDB names to dump, plus selected extras. PostgreSQL is listed separately."""
    mariadb = list(domain_map.mariadb_names())
    postgres = list(domain_map.postgres_names())
    selected = [str(n).strip() for n in (selected or []) if str(n).strip()]
    unassigned_names = {db.name for db in domain_map.unassigned_databases}
    for db in domain_map.unassigned_databases:
        if db.include_unassigned and db.name not in mariadb:
            mariadb.append(db.name)
    for name in selected:
        if name in postgres:
            continue
        if name in unassigned_names and not include_unassigned_selected and not any(
            db.name == name and db.include_unassigned for db in domain_map.unassigned_databases
        ):
            continue
        if name not in mariadb:
            mariadb.append(name)
    return mariadb, postgres


def is_blocked_source_path(path: str) -> bool:
    cleaned = _clean(path)
    return any(cleaned == prefix or cleaned.startswith(prefix + "/") for prefix in BLOCKED_FILE_PREFIXES)


def absolute_record_path(record: dict[str, Any]) -> str:
    root = _clean(str(record.get("source_root") or ""))
    rel = str(record.get("relative_path") or "").replace("\\", "/").lstrip("/")
    if rel in {"", "."}:
        return root
    return f"{root}/{rel}"


def _longest_prefix(path: str, roots: list[str]) -> str:
    matches = [root for root in roots if path == root or path.startswith(root + "/")]
    if not matches:
        return ""
    return max(matches, key=len)


def classify_file(
    record: dict[str, Any],
    domain_map: DomainMap,
    *,
    nginx_root: str = "",
) -> dict[str, str]:
    """Place one master-tree file into a site folder or _server.

    Returns keys: site_folder, kind, relative, domain.
    kind is application | storage | config | docker | nginx | extra | unmapped.
    """
    abs_path = absolute_record_path(record)
    if is_blocked_source_path(abs_path):
        return {
            "site_folder": "",
            "kind": "blocked",
            "relative": "",
            "domain": "",
            "absolute": abs_path,
        }
    nginx = _clean(nginx_root)
    source_root = _clean(str(record.get("source_root") or ""))
    rel = str(record.get("relative_path") or "").replace("\\", "/").lstrip("/")
    basename = abs_path.rsplit("/", 1)[-1].lower() if abs_path else ""

    best: tuple[int, SiteSpec, str] | None = None
    for site in domain_map.sites:
        app_root = site.application_root
        if app_root and (abs_path == app_root or abs_path.startswith(app_root + "/")):
            kind = "application"
            prefix = app_root
            if basename in CONFIG_BASENAMES:
                kind = "application"
            score = len(prefix)
            if best is None or score > best[0]:
                best = (score, site, kind)
            continue
        storage = _longest_prefix(abs_path, site.storage_roots)
        if storage:
            score = len(storage)
            if best is None or score > best[0]:
                best = (score, site, "storage")
            continue
        other = _longest_prefix(abs_path, [p for p in site.source_paths if p not in {app_root, *site.storage_roots}])
        if other:
            kind = "storage" if site.application_root else "application"
            score = len(other)
            if best is None or score > best[0]:
                best = (score, site, kind)

    if best is not None:
        _score, site, kind = best
        prefix = site.application_root if kind == "application" else _longest_prefix(
            abs_path, site.storage_roots + site.source_paths + [site.application_root]
        )
        relative = abs_path[len(prefix) :].lstrip("/") if prefix and abs_path.startswith(prefix) else (rel or basename)
        docker = site.docker or {}
        compose = _clean(str(docker.get("compose_file") or docker.get("compose_files") or ""))
        if compose and (abs_path == compose or abs_path.endswith("/" + compose.rsplit("/", 1)[-1])):
            return {
                "site_folder": site.folder,
                "kind": "docker",
                "relative": compose.rsplit("/", 1)[-1],
                "domain": site.domain,
                "absolute": abs_path,
            }
        return {
            "site_folder": site.folder,
            "kind": kind,
            "relative": relative or basename,
            "domain": site.domain,
            "absolute": abs_path,
        }

    if nginx and (source_root == nginx or abs_path == nginx or abs_path.startswith(nginx + "/")):
        nginx_rel = abs_path[len(nginx) :].lstrip("/") if abs_path.startswith(nginx) else (rel or basename)
        for site in domain_map.sites:
            tokens = {site.domain.lower(), site.folder.lower(), *[h.lower() for h in site.hostnames]}
            haystack = f"{nginx_rel} {abs_path}".lower()
            if any(token and token in haystack for token in tokens):
                return {
                    "site_folder": site.folder,
                    "kind": "config",
                    "relative": f"nginx/{nginx_rel or basename}",
                    "domain": site.domain,
                    "absolute": abs_path,
                }
        return {
            "site_folder": "_server",
            "kind": "nginx",
            "relative": nginx_rel or basename,
            "domain": "",
            "absolute": abs_path,
        }

    return {
        "site_folder": "_server",
        "kind": "unmapped",
        "relative": abs_path.lstrip("/") or basename,
        "domain": "",
        "absolute": abs_path,
    }


def extra_config_copies(record: dict[str, Any], placement: dict[str, str]) -> dict[str, str] | None:
    """Optional second copy of well-known config files under files/config/."""
    if placement.get("kind") not in {"application", "storage"}:
        return None
    abs_path = placement.get("absolute") or absolute_record_path(record)
    basename = abs_path.rsplit("/", 1)[-1] if abs_path else ""
    if basename.lower() not in {name.lower() for name in CONFIG_BASENAMES} and basename.lower() not in {
        "config.inc.php",
        "wp-config.php",
    }:
        return None
    folder = placement.get("site_folder") or ""
    if not folder or folder.startswith("_"):
        return None
    return {
        "site_folder": folder,
        "kind": "config",
        "relative": basename,
        "domain": placement.get("domain") or "",
        "absolute": abs_path,
    }
