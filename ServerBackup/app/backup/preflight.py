"""Per-website backup preflight and NEW-file attribution.

Read-only against production. Used by DRY RUN before BACKUP NOW.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.backup.domain_map import (
    DomainMap,
    SiteSpec,
    absolute_record_path,
    build_domain_map,
    classify_file,
    inferred_db_container,
)
from app.backup.restore_validate import predicted_restore_status
from app.utils.format import format_bytes

KIND_FOLDER = {
    "application": "website/application",
    "storage": "website/storage",
    "config": "website/config",
    "docker": "docker",
    "nginx": "nginx",
    "ssl": "ssl",
    "unmapped": "_server/unmapped",
    "blocked": "(blocked docker-internal)",
    "extra": "_server/extra",
}


def attribute_records(
    records: list[dict[str, Any]],
    domain_map: DomainMap,
    *,
    nginx_root: str = "/etc/nginx",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        placement = classify_file(record, domain_map, nginx_root=nginx_root)
        abs_path = placement.get("absolute") or absolute_record_path(record)
        if abs_path in seen:
            continue
        seen.add(abs_path)
        kind = placement.get("kind") or "unmapped"
        folder = placement.get("site_folder") or "_server"
        if kind == "blocked":
            folder = "(blocked)"
        rows.append(
            {
                "absolute": abs_path,
                "source_root": str(record.get("source_root") or ""),
                "relative": placement.get("relative") or "",
                "kind": kind,
                "site_folder": folder,
                "domain": placement.get("domain") or "",
                "size": int(record.get("size") or 0),
            }
        )
    return rows


def group_attributions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        folder = row.get("site_folder") or "_server"
        bucket = grouped.setdefault(
            folder,
            {
                "folder": folder,
                "domain": row.get("domain") or folder,
                "files": 0,
                "bytes": 0,
                "kinds": defaultdict(lambda: {"files": 0, "bytes": 0}),
                "sources": defaultdict(lambda: {"files": 0, "bytes": 0}),
            },
        )
        size = int(row.get("size") or 0)
        bucket["files"] += 1
        bucket["bytes"] += size
        kind = str(row.get("kind") or "unmapped")
        bucket["kinds"][kind]["files"] += 1
        bucket["kinds"][kind]["bytes"] += size
        source = str(row.get("source_root") or row.get("absolute") or "")
        bucket["sources"][source]["files"] += 1
        bucket["sources"][source]["bytes"] += size
    return grouped


def _db_dump_path(site: SiteSpec) -> str:
    if not site.databases:
        return "(none)"
    return f"{site.folder}/database/{site.databases[0].name}.sql"


def _db_container(site: SiteSpec) -> str:
    if site.databases and site.databases[0].docker_container:
        return site.databases[0].docker_container
    return inferred_db_container(site.docker) or "(none)"


def _persistent_source(site: SiteSpec) -> str:
    roots = site.all_file_roots()
    if roots:
        return ", ".join(roots)
    if site.named_volumes:
        return "named volumes only: " + ", ".join(f"volume:{name}" for name in site.named_volumes)
    docker = site.docker or {}
    return str(docker.get("workdir") or docker.get("container") or "(none)")


def _database_evidence(name: str, database_inventory: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Config evidence proving which application owns a database."""
    for row in database_inventory or []:
        if str(row.get("name") or "") != str(name or ""):
            continue
        refs = [str(item.get("path") or "") for item in (row.get("references") or []) if item.get("path")]
        return {
            "references": refs,
            "reason": str(row.get("reason") or ""),
            "status": str(row.get("status") or ""),
            "docker_container": str(row.get("docker_container") or ""),
            "engine": str(row.get("type") or ""),
        }
    return {"references": [], "reason": "", "status": "", "docker_container": "", "engine": ""}


def _persistent_mounts(site: SiteSpec) -> list[str]:
    entries: list[str] = []
    docker = site.docker or {}
    for mount in docker.get("mounts") or []:
        if not isinstance(mount, dict):
            continue
        source = str(mount.get("source") or "")
        dest = str(mount.get("destination") or "")
        purpose = str(mount.get("purpose") or "")
        if mount.get("named_volume"):
            label = f"volume:{source} -> {dest}"
        else:
            label = f"bind:{source} -> {dest}"
        if purpose:
            label += f" ({purpose})"
        if label not in entries:
            entries.append(label)
    for name in site.named_volumes:
        label = f"volume:{name}"
        if not any(entry.startswith(f"volume:{name} ") or entry == label for entry in entries):
            entries.append(label)
    for root in site.storage_roots:
        if root and root not in entries:
            entries.append(f"bind:{root}")
    return entries


def build_preflight(
    *,
    applications: list[dict[str, Any]],
    database_inventory: list[dict[str, Any]] | None = None,
    inventory: list[dict[str, Any]] | None = None,
    nginx_root: str = "/etc/nginx",
    dump_objects: dict[str, str] | None = None,
    has_master: bool = False,
) -> dict[str, Any]:
    domain_map = build_domain_map(applications, database_inventory, approved_only=False)
    attributed = attribute_records(list(inventory or []), domain_map, nginx_root=nginx_root)
    grouped = group_attributions(attributed)
    objects = dict(dump_objects or {})
    app_by_id = {str(app.get("application_id") or ""): app for app in (applications or []) if isinstance(app, dict)}
    websites: list[dict[str, Any]] = []
    for site in domain_map.sites:
        stats = grouped.get(site.folder) or {"files": 0, "bytes": 0, "kinds": {}, "sources": {}}
        db = site.databases[0] if site.databases else None
        dump_expected = bool(site.databases)
        dump_present = bool(db and objects.get(db.name)) if has_master else dump_expected
        restore = predicted_restore_status(
            site,
            file_count=int(stats.get("files") or 0),
            dump_expected=dump_expected,
            dump_object_present=bool(dump_present),
        )
        kinds = stats.get("kinds") or {}
        nginx_bytes = int((kinds.get("nginx") or {}).get("bytes") or 0)
        website_bytes = int(stats.get("bytes") or 0) - nginx_bytes
        db_bytes = int(db.size_bytes) if db else 0
        unresolved = list(restore.get("unresolved") or [])
        excluded = list(restore.get("excluded") or [])
        docker = site.docker or {}
        app = app_by_id.get(site.application_id) or {}
        ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
        ssl_storage = list(ssl.get("storage_paths") or [])
        if ssl.get("acme_file") and ssl.get("acme_file") not in ssl_storage:
            ssl_storage = [ssl.get("acme_file"), *ssl_storage]
        evidence = _database_evidence(db.name, database_inventory) if db else {}
        containers = [c for c in [docker.get("container"), _db_container(site)] if c and c != "(none)"]
        websites.append(
            {
                "website": site.domain,
                "backup_folder": site.folder,
                "application_container": site.application_id
                or docker.get("container")
                or "(none)",
                "actual_source_paths": site.all_file_roots(),
                "persistent_data_source": _persistent_source(site),
                "persistent_mounts": _persistent_mounts(site),
                "containers": containers,
                "database": db.name if db else "(none)",
                "database_dump_path": _db_dump_path(site),
                "database_config_evidence": evidence.get("references") or [],
                "database_evidence_reason": evidence.get("reason") or "",
                "nginx_configuration": ", ".join(site.nginx_source_files) or "(none recorded)",
                "ssl_mechanism": str(ssl.get("mechanism") or ("https" if app.get("https") else "none")),
                "ssl_storage_paths": [str(p) for p in ssl_storage if p],
                "ssl_restore": str(ssl.get("restore_procedure") or ssl.get("backup_treatment") or ""),
                "estimated_website_backup_size": max(website_bytes, 0),
                "estimated_database_dump_size": db_bytes,
                "total_size": max(website_bytes, 0) + db_bytes,
                "number_of_files": int(stats.get("files") or 0),
                "unresolved_items": unresolved,
                "excluded_data": excluded,
                "restore_completeness_status": restore.get("status"),
                "aliases": [h for h in site.hostnames if h != site.domain],
                "application_type": site.website_type,
                "database_container": _db_container(site),
                "docker_compose_project": docker.get("compose_project") or "",
                "docker_compose_file": docker.get("compose_file") or docker.get("compose_files") or "",
                "kinds": {key: dict(value) for key, value in (kinds.items() if hasattr(kinds, "items") else [])},
                "sources": {
                    key: dict(value) for key, value in ((stats.get("sources") or {}).items())
                },
            }
        )

    excluded_rows: list[dict[str, Any]] = []
    for row in database_inventory or []:
        status = str(row.get("status") or "")
        if "EXCLUDED" in status or status.startswith("RECOVERY"):
            excluded_rows.append(
                {
                    "name": row.get("name"),
                    "status": status,
                    "reason": row.get("reason") or "",
                    "recovery_path": (
                        f"_recovery/databases/{row.get('name')}.sql"
                        if status.startswith("RECOVERY")
                        else f"_recovery/databases/{row.get('name')}.EXCLUDED.txt"
                    ),
                }
            )
    for db in domain_map.recovery_databases:
        if not any(item.get("name") == db.name for item in excluded_rows):
            excluded_rows.append(
                {
                    "name": db.name,
                    "status": "RECOVERY — DOKPLOY MIGRATION LEFTOVER",
                    "reason": "not a live website database; dumped under _recovery",
                    "recovery_path": f"_recovery/databases/{db.name}.sql",
                }
            )

    website_folders = {str(row.get("backup_folder") or "") for row in websites}
    website_files = 0
    infra_files = 0
    recovery_files = 0
    excluded_files = 0
    other_files = 0
    for key, stats in grouped.items():
        files = int(stats.get("files") or 0)
        folder = str(key or "")
        if folder in website_folders:
            website_files += files
        elif folder == "_server" or folder.startswith("_server/"):
            infra_files += files
        elif folder == "_recovery" or folder.startswith("_recovery/"):
            recovery_files += files
        elif folder in {"(blocked)", ""}:
            excluded_files += files
        else:
            other_files += files
    attributed_unique = len(attributed)
    classified_sum = website_files + infra_files + recovery_files + excluded_files + other_files
    file_reconciliation = {
        "inventoried": attributed_unique,
        "website": website_files,
        "infrastructure": infra_files,
        "recovery": recovery_files,
        "excluded": excluded_files,
        "other": other_files,
        "attributed": classified_sum,
        "ok": attributed_unique == classified_sum and other_files == 0,
    }

    return {
        "domain_map": domain_map,
        "attributed": attributed,
        "grouped": grouped,
        "websites": websites,
        "file_reconciliation": file_reconciliation,
        "infrastructure_databases": [
            {
                "name": db.name,
                "dump_path": f"_server/infrastructure/databases/{db.name}.sql",
                "size_bytes": db.size_bytes,
                "reason": "Dokploy/Traefik infrastructure database; not a website folder",
            }
            for db in domain_map.infrastructure_databases
        ],
        "recovery_databases": [
            {
                "name": db.name,
                "dump_path": f"_recovery/databases/{db.name}.sql",
                "size_bytes": db.size_bytes,
                "reason": "Dokploy migration leftover; not assigned to a live website folder",
            }
            for db in domain_map.recovery_databases
        ],
        "unassigned_databases": [
            {"name": db.name, "include_unassigned": db.include_unassigned}
            for db in domain_map.unassigned_databases
        ],
        "excluded": excluded_rows,
        "blocked_files": int((grouped.get("") or {}).get("files") or 0),
        "server_files": int((grouped.get("_server") or {}).get("files") or 0),
        "server_bytes": int((grouped.get("_server") or {}).get("bytes") or 0),
    }


def format_proposed_tree(preflight: dict[str, Any]) -> str:
    lines = [
        "PROPOSED BACKUP TREE (not written until you approve BACKUP NOW)",
        "BACKUPS/",
    ]
    websites = list(preflight.get("websites") or [])
    for row in websites:
        folder = row["backup_folder"]
        lines.append(f"├── {folder}/")
        prefix = "│   "
        lines.extend(
            [
                f"{prefix}├── website/",
                f"{prefix}│   ├── application/",
                f"{prefix}│   ├── storage/",
                f"{prefix}│   └── config/",
                f"{prefix}├── database/",
                f"{prefix}│   └── {PathName(row['database'])}",
                f"{prefix}├── nginx/",
                f"{prefix}├── docker/",
                f"{prefix}├── ssl/",
                f"{prefix}└── manifest.json",
            ]
        )
    recovery = list(preflight.get("recovery_databases") or [])
    if recovery:
        lines.append("├── _recovery/")
        lines.append("│   ├── README.txt")
        lines.append("│   └── databases/")
        for db in recovery:
            lines.append(f"│       └── {db['name']}.sql")
    lines.append("└── _server/")
    lines.append("    ├── nginx/")
    lines.append("    ├── docker/")
    lines.append("    ├── infrastructure/")
    infra_dbs = list(preflight.get("infrastructure_databases") or [])
    if infra_dbs:
        lines.append("    │   └── databases/")
        for db in infra_dbs:
            lines.append(f"    │       └── {db['name']}.sql")
    lines.append("    ├── system/")
    lines.append("    └── ssl/")
    return "\n".join(lines)


def PathName(database: str) -> str:
    name = str(database or "").strip()
    if not name or name == "(none)":
        return "(none associated)"
    return f"{name}.sql"


def format_new_file_attribution(
    *,
    counts: dict[str, int],
    grouped: dict[str, dict[str, Any]],
    has_master: bool,
    file_reconciliation: dict[str, Any] | None = None,
) -> str:
    new_count = int((counts or {}).get("new") or 0)
    lines = [
        "NEW FILE ATTRIBUTION",
        f"  NEW={new_count} MODIFIED={int((counts or {}).get('modified') or 0)} "
        f"DELETED={int((counts or {}).get('deleted') or 0)} "
        f"RENAMED={int((counts or {}).get('renamed') or 0)} "
        f"MOVED={int((counts or {}).get('moved') or 0)}",
    ]
    if not has_master:
        lines.append(
            "  Why NEW is large on a first baseline: there is no master HEAD yet, so every "
            "inventoried live file is counted as NEW. These are not newly created websites. "
            "They are the current files of the active Docker/Nginx applications that would "
            "become generation 1."
        )
    else:
        lines.append("  NEW files are paths that are not in the current master tree.")
    if not grouped:
        lines.append("  (no inventory grouped yet)")
        return "\n".join(lines)
    ordered = sorted(
        grouped.values(),
        key=lambda item: (0 if not str(item.get("folder") or "").startswith("_") else 1, str(item.get("folder") or "")),
    )
    total_files = 0
    total_bytes = 0
    for bucket in ordered:
        folder = bucket.get("folder") or "_server"
        files = int(bucket.get("files") or 0)
        size = int(bucket.get("bytes") or 0)
        total_files += files
        total_bytes += size
        if folder == "":
            label = "(blocked docker-internal — not copied)"
        else:
            label = folder
        lines.append(f"  {label}: {files} files  {format_bytes(size)}")
        kinds = bucket.get("kinds") or {}
        for kind, stats in sorted(kinds.items(), key=lambda item: item[0]):
            dest = KIND_FOLDER.get(kind, kind)
            lines.append(
                f"    {dest}: {int(stats.get('files') or 0)} files  {format_bytes(int(stats.get('bytes') or 0))}"
            )
        sources = bucket.get("sources") or {}
        for source, stats in sorted(sources.items(), key=lambda item: (-int(item[1].get("files") or 0), item[0])):
            if not source:
                continue
            lines.append(
                f"    source {source}: {int(stats.get('files') or 0)} files  {format_bytes(int(stats.get('bytes') or 0))}"
            )
    lines.append(f"  attributed total: {total_files} files  {format_bytes(total_bytes)}")
    recon = file_reconciliation or {}
    if recon:
        extra_other = f"+ other {recon.get('other')} " if recon.get("other") else ""
        lines.append(
            "  FILE ACCOUNTING  inventoried="
            f"{recon.get('inventoried')} = website {recon.get('website')} "
            f"+ infrastructure {recon.get('infrastructure')} "
            f"+ recovery {recon.get('recovery')} "
            f"+ excluded {recon.get('excluded')} "
            f"{extra_other}"
            f"(sum {recon.get('attributed')})  "
            f"{'OK' if recon.get('ok') else 'MISMATCH'}"
        )
    if not has_master and new_count and recon.get("inventoried") not in {None, new_count}:
        lines.append(
            f"  NEW={new_count} vs unique inventoried={recon.get('inventoried')} — "
            "every inventoried file must have exactly one classification."
        )
    return "\n".join(lines)


def _fmt(values: Any) -> str:
    if not values:
        return "(none)"
    if isinstance(values, (list, tuple)):
        items = [str(v) for v in values if v]
        return ", ".join(items) if items else "(none)"
    return str(values)


def _resolution_reasons(row: dict[str, Any]) -> list[str]:
    """Attribution-level problems only.

    Whether every live file has been inventoried yet is a restore-completeness
    matter (shown separately as RESTORE STATUS / REMAINING UNRESOLVED ITEMS),
    not an attribution failure — image-based Docker apps legitimately have no
    bind-mounted host files.
    """
    reasons: list[str] = []
    app = str(row.get("application_container") or "")
    app_type = str(row.get("application_type") or "")
    has_app = bool(row.get("docker_compose_project")) or bool(row.get("actual_source_paths"))
    if app.startswith("reverse-proxy") or (app_type == "Reverse Proxy" and not has_app):
        reasons.append("reverse-proxy backend not traced to a real application")
    if str(row.get("database") or "(none)") == "(none)" and app_type not in {"Static", "Other"}:
        reasons.append("no database identified for an application site")
    return reasons


def format_attribution_report(preflight: dict[str, Any]) -> str:
    """Per-domain attribution: everything needed to restore each website.

    One block per public domain. This is the report a human administrator
    reads to confirm that ``BACKUPS/<domain>/`` will contain the real
    application, files, and database — not just the Nginx front door.
    """
    lines = [
        "PER-DOMAIN ATTRIBUTION REPORT",
        "  One block per active website. Everything required to restore that",
        "  website is attributed to its own BACKUPS/<domain>/ folder.",
    ]
    websites = list(preflight.get("websites") or [])
    needs_attention: list[str] = []
    for row in websites:
        if _resolution_reasons(row):
            needs_attention.append(str(row.get("website")))
    unassigned = [db.get("name") for db in (preflight.get("unassigned_databases") or [])]
    lines.append(
        f"  RESOLUTION SUMMARY: {len(websites) - len(needs_attention)}/{len(websites)} domains fully resolved"
        + (f"; NEEDS ATTENTION: {', '.join(needs_attention)}" if needs_attention else "; all domains resolved")
    )
    if unassigned:
        lines.append(f"  UNASSIGNED DATABASES (require review, not discarded): {', '.join(str(n) for n in unassigned)}")
    if not websites:
        lines.append("  (no active websites attributed yet)")
    for row in websites:
        aliases = row.get("aliases") or []
        lines.extend(
            [
                "",
                f"  DOMAIN: {row.get('website')}",
                f"    APPLICATION: {row.get('application_type') or 'Unknown'} "
                f"({row.get('application_container')})",
                f"    ALIASES: {_fmt(aliases)}",
                f"    ACTUAL SOURCE PATHS: {_fmt(row.get('actual_source_paths'))}",
                f"    DOCKER PROJECT: {row.get('docker_compose_project') or '(none)'}",
                f"    CONTAINERS: {_fmt(row.get('containers'))}",
                f"    PERSISTENT VOLUMES/BIND MOUNTS: {_fmt(row.get('persistent_mounts'))}",
                f"    DATABASE: {row.get('database')}",
                f"    DATABASE CONTAINER: {row.get('database_container') or '(host)'}",
                f"    DATABASE CONFIG EVIDENCE: {_fmt(row.get('database_config_evidence'))}",
            ]
        )
        if row.get("database_evidence_reason"):
            lines.append(f"      evidence detail: {row.get('database_evidence_reason')}")
        lines.extend(
            [
                f"    NGINX CONFIG: {row.get('nginx_configuration')}",
                f"    SSL: {row.get('ssl_mechanism')}",
                f"      ssl storage: {_fmt(row.get('ssl_storage_paths'))}",
                f"      ssl restore: {row.get('ssl_restore') or 'not identified'}",
                f"    ESTIMATED SIZE: website "
                f"{format_bytes(int(row.get('estimated_website_backup_size') or 0))} + database "
                f"{format_bytes(int(row.get('estimated_database_dump_size') or 0))} = "
                f"{format_bytes(int(row.get('total_size') or 0))} "
                f"({row.get('number_of_files')} files)",
                f"    RESTORE STATUS: {row.get('restore_completeness_status')}",
            ]
        )
        reasons = _resolution_reasons(row)
        lines.append(
            f"    RESOLVED: {'YES' if not reasons else 'NEEDS ATTENTION — ' + '; '.join(reasons)}"
        )
        unresolved = row.get("unresolved_items") or []
        if unresolved:
            lines.append(f"    REMAINING UNRESOLVED ITEMS: {_fmt(unresolved)}")
    recovery = list(preflight.get("recovery_databases") or [])
    if recovery:
        lines.extend(["", "  _recovery/ (leftover/legacy data — kept, never silently discarded)"])
        for db in recovery:
            lines.append(
                f"    {db.get('name')} -> {db.get('dump_path')}  {db.get('reason')}"
            )
    infra = list(preflight.get("infrastructure_databases") or [])
    if infra:
        lines.extend(["", "  _server/ (genuinely server-wide infrastructure)"])
        for db in infra:
            lines.append(f"    {db.get('name')} -> {db.get('dump_path')}  {db.get('reason')}")
    return "\n".join(lines)


def format_preflight_report(preflight: dict[str, Any]) -> str:
    lines = [
        "PREFLIGHT VALIDATION REPORT",
        "  BACKUP NOW is not started by this report.",
        "",
        "  1 Website | 2 Backup folder | 3 Application/container | 4 Persistent data source | "
        "5 Database | 6 Database dump path | 7 Nginx configuration | 8 Estimated website backup size | "
        "9 Estimated database dump size | 10 Total size | 11 Number of files | 12 Unresolved items | "
        "13 Excluded data | 14 Restore completeness status",
    ]
    for row in preflight.get("websites") or []:
        unresolved = row.get("unresolved_items") or []
        excluded = row.get("excluded_data") or []
        lines.extend(
            [
                "",
                f"  WEBSITE: {row.get('website')}",
                f"    1. Website: {row.get('website')}",
                f"    2. Backup folder: BACKUPS/{row.get('backup_folder')}/",
                f"    3. Application/container: {row.get('application_container')}",
                f"    4. Persistent data source: {row.get('persistent_data_source')}",
                f"    5. Database: {row.get('database')}",
                f"    6. Database dump path: {row.get('database_dump_path')}",
                f"    7. Nginx configuration: {row.get('nginx_configuration')}",
                f"    8. Estimated website backup size: {format_bytes(int(row.get('estimated_website_backup_size') or 0))}",
                f"    9. Estimated database dump size: {format_bytes(int(row.get('estimated_database_dump_size') or 0))}",
                f"    10. Total size: {format_bytes(int(row.get('total_size') or 0))}",
                f"    11. Number of files: {row.get('number_of_files')}",
                f"    12. Unresolved items: {'; '.join(unresolved) if unresolved else '(none)'}",
                f"    13. Excluded data: {'; '.join(excluded) if excluded else '(none)'}",
                f"    14. Restore completeness status: {row.get('restore_completeness_status')}",
            ]
        )
    recovery = list(preflight.get("recovery_databases") or [])
    lines.extend(["", "RECOVERY / UNASSIGNED DATA"])
    if recovery:
        for db in recovery:
            lines.append(
                f"  {db.get('name')} -> {db.get('dump_path')}  "
                f"{format_bytes(int(db.get('size_bytes') or 0))}  {db.get('reason')}"
            )
            lines.append(
                "    This leftover is NOT deleted. It is kept out of website folders on purpose. "
                "Discover EXCLUDE FROM BACKUP skips the dump but still writes a recovery note."
            )
    else:
        lines.append("  (none)")
    excluded = list(preflight.get("excluded") or [])
    lines.extend(["", "EXCLUDED DATABASES"])
    if excluded:
        for row in excluded:
            lines.append(f"  {row.get('name')}  {row.get('status')}")
            if row.get("reason"):
                lines.append(f"    {row.get('reason')}")
            if row.get("recovery_path"):
                lines.append(f"    recovery option: {row.get('recovery_path')}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)
