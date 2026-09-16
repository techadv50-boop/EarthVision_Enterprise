"""Human-readable per-domain export under destination/BACKUPS.

Does not modify master/, live websites, Docker, or databases. Existing
timestamped archives are left untouched. A failed export never deletes
a previous BACKUPS tree.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import gzip
import json
import shutil

from app import __app_name__, __version__
from app.backup.checksum import sha256_file
from app.backup.domain_map import (
    SiteDatabase,
    SiteSpec,
    absolute_record_path,
    build_domain_map,
    classify_file,
    extra_config_copies,
    inferred_db_container,
)
from app.backup.restore_validate import validate_readable_tree
from app.master.objects import object_path
from app.master.store import MasterStore
from app.master.tree import index_active

READABLE_DIR = "BACKUPS"
STAGING_SUFFIX = ".staging"
PREVIOUS_SUFFIX = ".previous"
UNASSIGNED_DIR = "_unassigned-databases"
RECOVERY_DIR = "_recovery"
SERVER_DIR = "_server"
MANIFEST_NAME = "BACKUP-MANIFEST.json"
SITE_MANIFEST_NAME = "manifest.json"
INFO_NAME = "backup-info.txt"
INFO_JSON_NAME = "backup-info.json"


class ReadableExportError(RuntimeError):
    pass


def readable_root(destination: str | Path) -> Path:
    return Path(destination) / READABLE_DIR


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _safe_sql_name(name: str) -> str:
    cleaned = "".join(ch for ch in str(name) if ch.isalnum() or ch in {"-", "_", "."})
    if not cleaned or cleaned in {".", ".."}:
        raise ReadableExportError(f"Refusing unsafe database filename {name!r}")
    return cleaned


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _copy_object(store: MasterStore, digest: str, dest: Path) -> int:
    source = object_path(store.objects_root, digest)
    if not source.is_file():
        raise ReadableExportError(f"Missing master object {digest} for {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.replace(dest)
    return dest.stat().st_size


def _write_sql_from_object(store: MasterStore, digest: str, dest: Path) -> int:
    source = object_path(store.objects_root, digest)
    if not source.is_file():
        raise ReadableExportError(f"Missing database object {digest} for {dest}")
    raw = source.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        tmp.write_bytes(gzip.decompress(raw))
    else:
        tmp.write_bytes(raw)
    tmp.replace(dest)
    return dest.stat().st_size


def _site_dirs(root: Path, site: SiteSpec) -> dict[str, Path]:
    base = root / site.folder
    website = base / "website"
    return {
        "base": base,
        "website": website,
        "application": website / "application",
        "storage": website / "storage",
        "config": website / "config",
        "database": base / "database",
        "nginx": base / "nginx",
        "ssl": base / "ssl",
        "docker": base / "docker",
    }


def _ensure_site_layout(root: Path, site: SiteSpec) -> dict[str, Path]:
    dirs = _site_dirs(root, site)
    for path in (dirs["application"], dirs["storage"], dirs["config"], dirs["database"], dirs["nginx"], dirs["ssl"]):
        path.mkdir(parents=True, exist_ok=True)
    dirs["docker"].mkdir(parents=True, exist_ok=True)
    return dirs


def format_backup_info(
    site: SiteSpec,
    *,
    timestamp: str,
    generation: int | None,
    app_version: str,
    database_files: list[str],
    source_files: list[str],
    extra_notes: list[str] | None = None,
) -> str:
    docker = site.docker or {}
    db_names = [db.name for db in site.databases] or ["(none associated)"]
    db_types = list(dict.fromkeys(db.db_type or "MariaDB" for db in site.databases)) or ["(none)"]
    shared = []
    for db in site.databases:
        if db.shared_with:
            shared.append(f"{db.name} also belongs to: {', '.join(db.shared_with)}")
    lines = [
        f"Domain: {site.domain}",
        f"Hostnames: {', '.join(site.hostnames) or site.domain}",
        f"Backup date/time: {timestamp}",
        f"Website type: {site.website_type}",
        f"Database name: {', '.join(db_names)}",
        f"Database server/type: {', '.join(db_types)}",
        f"Docker container name: {docker.get('container') or '(none)'}",
        f"Docker compose project: {docker.get('compose_project') or '(none)'}",
        f"Docker compose file: {docker.get('compose_file') or docker.get('compose_files') or '(none)'}",
        f"Application id (internal): {site.application_id or '(none)'}",
        "",
        "Source paths:",
        f"  application: {site.application_root or '(none)'}",
        f"  storage: {', '.join(site.storage_roots) if site.storage_roots else '(none)'}",
        f"  other files: {', '.join(p for p in site.source_paths if p != site.application_root) or '(none)'}",
        f"  nginx: {', '.join(site.nginx_source_files) if site.nginx_source_files else '(none)'}",
        "",
        "Backup software:",
        f"  {__app_name__} {app_version}",
        f"  Master generation: {generation if generation is not None else '(none)'}",
        "",
        "Files in this backup:",
        *[f"  {item}" for item in source_files[:80] or ["  (none)"]],
        "",
        "Database files:",
        *[f"  {item}" for item in database_files or ["  (none associated or not dumped)"]],
        "",
        "Restore notes:",
        "  1. This folder is a self-contained copy of one website.",
        "  2. Copy website/application/ onto the site document root / bind mount.",
        "  3. Copy website/storage/ onto the original storage/files_dir path listed above.",
        "  4. Copy nginx/ onto the matching Nginx site files; SSL material is under nginx/ssl/ when inventoried.",
        "  5. Create the MariaDB/PostgreSQL schema named above, then import database/*.sql.",
        "  6. Docker sites: recreate the compose project from docker/ and restore named volumes from metadata.",
        "  7. Do not mix these files with another domain folder.",
        "  8. Restore is not proven by copy+dump alone; see restore_validation in manifest.json.",
    ]
    if shared:
        lines.extend(["", "Shared databases:", *[f"  {item}" for item in shared]])
    notes = list(site.notes) + list(extra_notes or [])
    if notes:
        lines.extend(["", "Discovery notes:", *[f"  {item}" for item in notes]])
    lines.append("")
    return "\n".join(lines)


def _site_info_json(
    site: SiteSpec,
    *,
    timestamp: str,
    generation: int | None,
    app_version: str,
    database_files: list[str],
    file_count: int = 0,
    checksums: dict[str, str] | None = None,
    restore_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    docker = site.docker or {}
    dump_name = Path(database_files[0]).name if database_files else ""
    aliases = [h for h in site.hostnames if h != site.domain]
    db_names = [db.name for db in site.databases]
    db_containers = [db.docker_container or inferred_db_container(site.docker) for db in site.databases]
    return {
        "canonical_hostname": site.domain,
        "aliases": aliases,
        "application_id": site.application_id,
        "application_type": site.website_type,
        "database_name": db_names[0] if len(db_names) == 1 else db_names,
        "database_container": db_containers[0] if len(db_containers) == 1 else db_containers,
        "nginx_configuration_files": list(site.nginx_source_files),
        "docker": {
            "container": docker.get("container") or "",
            "compose_project": docker.get("compose_project") or "",
            "compose_file": docker.get("compose_file") or docker.get("compose_files") or "",
            "service": docker.get("service") or "",
            "image": docker.get("image") or "",
            "workdir": docker.get("workdir") or "",
            "named_volumes": list(site.named_volumes),
            "bind_mounts": list(site.storage_roots),
        },
        "source_locations": {
            "application": site.application_root,
            "persistent_data": site.storage_roots,
            "files": site.source_paths,
            "config": site.config_paths,
            "nginx": site.nginx_source_files,
            "named_volumes": list(site.named_volumes),
        },
        "backup_timestamp": timestamp,
        "backup_version": app_version,
        "file_count": file_count,
        "database_dump_filename": dump_name,
        "checksums": checksums or {},
        "restore_validation": restore_validation or {},
        "domain": site.domain,
        "hostnames": site.hostnames,
        "website_type": site.website_type,
        "database_names": db_names,
        "database_type": [db.db_type for db in site.databases],
        "docker_container": docker.get("container") or "",
        "docker_compose_project": docker.get("compose_project") or "",
        "docker_compose_file": docker.get("compose_file") or docker.get("compose_files") or "",
        "source_paths": {
            "application": site.application_root,
            "storage": site.storage_roots,
            "files": site.source_paths,
            "config": site.config_paths,
            "nginx": site.nginx_source_files,
        },
        "database_files": database_files,
        "backup_software": f"{__app_name__} {app_version}",
        "proxy_pass": list(docker.get("published_ports") or []),
        "http_https": {
            "https": any("/ssl/" in p or "letsencrypt" in p or p.endswith(".pem") for p in site.config_paths),
        },
        "ssl": {
            "certificate_paths": [p for p in site.config_paths if "letsencrypt" in p or p.endswith(".pem") or p.endswith(".crt") or p.endswith(".key")],
        },
        "environment_files": [p for p in site.config_paths if p.rsplit("/", 1)[-1].startswith(".env") or p.endswith((".yml", ".yaml", ".inc.php", "wp-config.php"))],
        "exclusions": [],
        "warnings": list(site.notes),
        "restore_readiness": (restore_validation or {}).get("status") or "",
        "master_generation": generation,
        "shared_databases": {db.name: db.shared_with for db in site.databases if db.shared_with},
    }


def _write_docker_info(path: Path, site: SiteSpec) -> None:
    docker = site.docker or {}
    volumes = list(site.named_volumes)
    payload = {
        "domain": site.domain,
        "container": docker.get("container") or "",
        "compose_project": docker.get("compose_project") or "",
        "compose_file": docker.get("compose_file") or docker.get("compose_files") or "",
        "service": docker.get("service") or "",
        "image": docker.get("image") or "",
        "workdir": docker.get("workdir") or "",
        "named_volumes": list(dict.fromkeys(volumes)),
        "note": (
            "Application named volumes under /var/lib/docker/volumes/<name>/_data are copied when classified COPY_DATA. "
            "Database volumes are restored from SQL dumps, not live raw copies. Overlay2 is never copied."
        ),
    }
    _write_text(path / "container-info.json", json.dumps(payload, indent=2) + "\n")
    lines = [
        f"Domain: {site.domain}",
        f"Container: {payload['container'] or '(none)'}",
        f"Compose project: {payload['compose_project'] or '(none)'}",
        f"Compose file: {payload['compose_file'] or '(none)'}",
        f"Service: {payload['service'] or '(none)'}",
        f"Workdir: {payload['workdir'] or '(none)'}",
        "Named volumes: " + (", ".join(payload["named_volumes"]) if payload["named_volumes"] else "(none recorded)"),
        payload["note"],
        "",
    ]
    _write_text(path / "container-info.txt", "\n".join(lines))


def _dest_for_kind(dirs: dict[str, Path], kind: str, relative: str, server_root: Path) -> Path:
    rel = Path(relative)
    if kind == "application":
        return dirs["application"] / rel
    if kind == "storage":
        return dirs["storage"] / rel
    if kind == "config":
        return dirs["config"] / rel
    if kind == "docker":
        return dirs["docker"] / rel
    if kind == "ssl":
        ssl_root = dirs.get("ssl")
        if ssl_root is not None:
            return ssl_root / rel
        return server_root / "ssl" / rel
    if kind == "nginx":
        nginx_root = dirs.get("nginx")
        if nginx_root is not None:
            return nginx_root / rel
        return server_root / "nginx" / rel
    if kind == "unmapped":
        return server_root / "unmapped" / rel
    return server_root / "extra" / rel


def export_readable_backup(
    *,
    destination: str | Path,
    store: MasterStore,
    tree: dict[str, Any],
    applications: list[dict[str, Any]],
    database_inventory: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    nginx_root: str = "/etc/nginx",
    timestamp: str | None = None,
    generation: int | None = None,
    output_root: str | Path | None = None,
    replace_existing: bool = True,
) -> dict[str, Any]:
    """Materialize destination/BACKUPS (or output_root) from the current master tree.

    output_root: if set, write there instead of destination/BACKUPS. Used for
    isolated test exports. Never deletes master/ or legacy timestamp folders.
    """
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gen = generation if generation is not None else tree.get("generation")
    domain_map = build_domain_map(applications, database_inventory, approved_only=True)
    final_root = Path(output_root) if output_root is not None else readable_root(dest)
    parent = final_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = final_root.with_name(final_root.name + STAGING_SUFFIX)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    objects = dict((meta or {}).get("database_objects") or tree.get("database_objects") or {})
    files = list(index_active(tree).values())
    site_file_lists: dict[str, list[str]] = {site.folder: [] for site in domain_map.sites}
    site_file_lists[SERVER_DIR] = []
    copied = 0
    blocked = 0

    for site in domain_map.sites:
        _ensure_site_layout(staging, site)

    server_root = staging / SERVER_DIR
    (server_root / "nginx").mkdir(parents=True, exist_ok=True)

    for record in files:
        placement = classify_file(record, domain_map, nginx_root=nginx_root)
        if placement.get("kind") == "blocked":
            blocked += 1
            continue
        digest = str(record.get("sha256") or "")
        if not digest:
            raise ReadableExportError(f"Active tree file has no sha256: {absolute_record_path(record)}")
        folder = placement.get("site_folder") or SERVER_DIR
        kind = placement.get("kind") or "unmapped"
        relative = placement.get("relative") or Path(absolute_record_path(record)).name
        if folder == SERVER_DIR:
            dirs = {
                "application": server_root / "files",
                "storage": server_root / "files",
                "config": server_root / "files",
                "docker": server_root / "docker",
            }
            dest_path = _dest_for_kind(dirs, kind, relative, server_root)
        else:
            site = domain_map.site_by_folder(folder)
            if site is None:
                dest_path = server_root / "unmapped" / relative
                folder = SERVER_DIR
            else:
                dirs = _site_dirs(staging, site)
                dest_path = _dest_for_kind(dirs, kind, relative, server_root)
        copied += _copy_object(store, digest, dest_path)
        rel_shown = str(dest_path.relative_to(staging)).replace("\\", "/")
        site_file_lists.setdefault(folder, []).append(rel_shown)
        extra = extra_config_copies(record, placement)
        if extra:
            extra_site = domain_map.site_by_folder(extra["site_folder"])
            if extra_site is not None:
                extra_path = _site_dirs(staging, extra_site)["config"] / extra["relative"]
                if not extra_path.is_file():
                    _copy_object(store, digest, extra_path)
                    site_file_lists[extra_site.folder].append(str(extra_path.relative_to(staging)).replace("\\", "/"))

    website_rows: list[dict[str, Any]] = []
    for site in domain_map.sites:
        dirs = _ensure_site_layout(staging, site)
        db_files: list[str] = []
        extra_notes: list[str] = []
        for db in site.databases:
            sql_name = f"{_safe_sql_name(db.name)}.sql"
            dest_sql = dirs["database"] / sql_name
            digest = str(objects.get(db.name) or "")
            if digest:
                _write_sql_from_object(store, digest, dest_sql)
                db_files.append(f"{site.folder}/database/{sql_name}")
            else:
                extra_notes.append(
                    f"Database {db.name} ({db.db_type}) was associated but no dump object was present in this generation."
                )
                if _is_postgres_note(db.db_type):
                    extra_notes.append(
                        f"PostgreSQL database {db.name} is recorded for restore planning; SQL dump is omitted unless dumped."
                    )
        if site.docker:
            _write_docker_info(dirs["docker"], site)
            extra_notes.append("Docker named volumes were not copied from Docker internal storage.")
        checksums: dict[str, str] = {}
        for db_file in db_files:
            leaf = Path(db_file).name
            dump_path = dirs["database"] / leaf
            if dump_path.is_file():
                checksums[f"database/{leaf}"] = sha256_file(dump_path)
        file_count = _count_files(dirs["base"])
        extra_notes.append(f"Per-site restore contract is {SITE_MANIFEST_NAME}.")
        info_text = format_backup_info(
            site,
            timestamp=stamp,
            generation=int(gen) if gen is not None else None,
            app_version=__version__,
            database_files=db_files,
            source_files=site_file_lists.get(site.folder) or [],
            extra_notes=extra_notes,
        )
        _write_text(dirs["base"] / INFO_NAME, info_text)
        site_manifest = _site_info_json(
            site,
            timestamp=stamp,
            generation=int(gen) if gen is not None else None,
            app_version=__version__,
            database_files=db_files,
            file_count=file_count,
            checksums=checksums,
        )
        _write_text(dirs["base"] / INFO_JSON_NAME, json.dumps(site_manifest, indent=2) + "\n")
        _write_text(dirs["base"] / SITE_MANIFEST_NAME, json.dumps(site_manifest, indent=2) + "\n")
        website_rows.append(
            {
                "domain": site.domain,
                "type": site.website_type,
                "folder": site.folder,
                "files": f"{site.folder}/website",
                "website": f"{site.folder}/website",
                "nginx": f"{site.folder}/nginx",
                "docker": f"{site.folder}/docker" if site.docker else "",
                "manifest": f"{site.folder}/{SITE_MANIFEST_NAME}",
                "database": db_files[0] if len(db_files) == 1 else db_files,
                "databases": [db.name for db in site.databases],
                "database_files": db_files,
                "backup_info": f"{site.folder}/{INFO_NAME}",
                "file_count": file_count,
                "status": "SUCCESS",
            }
        )

    unassigned_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    placed_db = {db.name for site in domain_map.sites for db in site.databases}
    recovery_all = list(domain_map.recovery_databases)
    seen_recovery = {db.name for db in recovery_all}
    unassigned_all = list(domain_map.unassigned_databases)
    seen_unassigned = {db.name for db in unassigned_all} | seen_recovery
    for name in objects:
        if name and name not in placed_db and name not in seen_unassigned:
            unassigned_all.append(SiteDatabase(name=str(name), db_type="MariaDB"))
            seen_unassigned.add(str(name))
    if recovery_all:
        recovery_dir = staging / RECOVERY_DIR / "databases"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        dumped_here: list[str] = []
        missing_here: list[str] = []
        for db in recovery_all:
            sql_name = f"{_safe_sql_name(db.name)}.sql"
            digest = str(objects.get(db.name) or "")
            if not digest:
                note = recovery_dir / f"{_safe_sql_name(db.name)}.EXCLUDED.txt"
                _write_text(
                    note,
                    "\n".join(
                        [
                            f"Database: {db.name}",
                            "Classification: Dokploy migration leftover / unassigned recovery schema.",
                            "This schema was NOT silently deleted.",
                            "It is not part of any live website folder.",
                            "Recovery option: Discover → DUMP AS UNASSIGNED, then run BACKUP NOW.",
                            "A dump object was not present in this master generation.",
                            "",
                        ]
                    ),
                )
                missing_here.append(db.name)
                recovery_rows.append(
                    {
                        "name": db.name,
                        "type": db.db_type,
                        "file": f"{RECOVERY_DIR}/databases/{note.name}",
                        "reason": "Dokploy migration leftover; dump object missing in this generation",
                    }
                )
                continue
            dest_sql = recovery_dir / sql_name
            _write_sql_from_object(store, digest, dest_sql)
            dumped_here.append(f"{RECOVERY_DIR}/databases/{sql_name}")
            recovery_rows.append(
                {
                    "name": db.name,
                    "type": db.db_type,
                    "file": f"{RECOVERY_DIR}/databases/{sql_name}",
                    "checksum": sha256_file(dest_sql),
                    "reason": "Dokploy migration leftover; not assigned to a live website",
                }
            )
        _write_text(
            staging / RECOVERY_DIR / "README.txt",
            "\n".join(
                [
                    "Recovery area — not a website.",
                    "Schemas here are leftovers (for example sea_tecdb after the 50sea.com",
                    "WordPress → Docker cutover). They are kept so they are never silently discarded.",
                    "They are intentionally NOT placed under 50sea.com/ or any other live site folder.",
                    "",
                    "Dumped: " + (", ".join(dumped_here) if dumped_here else "(none in this generation)"),
                    "Documented without dump: " + (", ".join(missing_here) if missing_here else "(none)"),
                    "",
                    "To restore one of these schemas, import the .sql into a scratch MariaDB instance.",
                    "To skip future dumps, use Discover → EXCLUDE FROM BACKUP; a .EXCLUDED.txt note remains.",
                    "",
                ]
            ),
        )
    if unassigned_all:
        unassigned_dir = staging / UNASSIGNED_DIR
        unassigned_dir.mkdir(parents=True, exist_ok=True)
        dumped_here = []
        missing_here = []
        for db in unassigned_all:
            sql_name = f"{_safe_sql_name(db.name)}.sql"
            digest = str(objects.get(db.name) or "")
            if not digest:
                missing_here.append(db.name)
                continue
            dest_sql = unassigned_dir / sql_name
            _write_sql_from_object(store, digest, dest_sql)
            dumped_here.append(f"{UNASSIGNED_DIR}/{sql_name}")
            unassigned_rows.append(
                {
                    "name": db.name,
                    "type": db.db_type,
                    "file": f"{UNASSIGNED_DIR}/{sql_name}",
                    "checksum": sha256_file(dest_sql),
                    "reason": "no proven website association",
                }
            )
        _write_text(
            unassigned_dir / "README.txt",
            "\n".join(
                [
                    "Databases in this folder were discovered on the server but were not",
                    "mapped to a website. They are not guessed onto 50sea.com or any other domain.",
                    "Dokploy leftovers belong in _recovery/ instead of here unless you chose DUMP AS UNASSIGNED.",
                    "",
                    "Dumped: " + (", ".join(dumped_here) if dumped_here else "(none in this generation)"),
                    "Associated-unknown / not dumped: " + (", ".join(missing_here) if missing_here else "(none)"),
                    "",
                ]
            ),
        )

    _write_text(
        server_root / "README.txt",
        "\n".join(
            [
                "Shared server files that do not belong to a single website.",
                "Nginx files that match a hostname are copied into that website's nginx/ folder.",
                "This folder should stay small. If a site's files landed here, the layout is wrong.",
                "",
            ]
        ),
    )

    restore_result = validate_readable_tree(staging, domain_map)
    by_folder = {row.get("folder"): row for row in restore_result.get("websites") or []}
    for site in domain_map.sites:
        validation = by_folder.get(site.folder) or {}
        manifest_path = staging / site.folder / SITE_MANIFEST_NAME
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            payload["restore_validation"] = {
                "status": validation.get("status"),
                "checks": validation.get("checks") or [],
                "unresolved": validation.get("unresolved") or [],
                "excluded": validation.get("excluded") or [],
            }
            payload["file_count"] = _count_files(staging / site.folder)
            _write_text(manifest_path, json.dumps(payload, indent=2) + "\n")
            _write_text(staging / site.folder / INFO_JSON_NAME, json.dumps(payload, indent=2) + "\n")
        for row in website_rows:
            if row.get("folder") == site.folder:
                row["restore_validation"] = validation.get("status")
                row["status"] = "SUCCESS" if validation.get("ok") else "INCOMPLETE"

    overall = "SUCCESS"
    if restore_result.get("status") == "INCOMPLETE":
        overall = "INCOMPLETE"
    elif restore_result.get("status") == "PARTIAL":
        overall = "SUCCESS"

    manifest = {
        "format": 2,
        "backup_software": __app_name__,
        "version": __version__,
        "created_at": stamp,
        "master_generation": gen,
        "destination_layout": f"{READABLE_DIR}/<domain>/website|database|nginx|docker|{SITE_MANIFEST_NAME}",
        "websites": website_rows,
        "unassigned_databases": unassigned_rows,
        "recovery_databases": recovery_rows,
        "skipped_applications": domain_map.skipped,
        "server": {
            "nginx": f"{SERVER_DIR}/nginx",
            "folder": SERVER_DIR,
        },
        "blocked_docker_internal_files": blocked,
        "restore_validation": restore_result,
        "status": overall,
    }
    _write_text(staging / MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")

    if not replace_existing and final_root.exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise ReadableExportError(f"Refusing to replace existing {final_root}")

    previous = final_root.with_name(final_root.name + PREVIOUS_SUFFIX)
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
    if final_root.exists():
        final_root.rename(previous)
    staging.rename(final_root)
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
    manifest["root"] = str(final_root)
    return manifest


def _is_postgres_note(db_type: str) -> bool:
    return "postgres" in str(db_type or "").lower()


def export_from_store(
    destination: str | Path,
    *,
    applications: list[dict[str, Any]],
    database_inventory: list[dict[str, Any]] | None = None,
    nginx_root: str = "/etc/nginx",
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    store = MasterStore(destination)
    if not store.has_head():
        raise ReadableExportError("No master HEAD to export.")
    tree = store.load_tree()
    meta = store.load_meta()
    return export_readable_backup(
        destination=destination,
        store=store,
        tree=tree,
        applications=applications,
        database_inventory=database_inventory,
        meta=meta,
        nginx_root=nginx_root,
        timestamp=str(tree.get("timestamp") or meta.get("updated_at") or ""),
        generation=store.head_generation(),
        output_root=output_root,
    )
