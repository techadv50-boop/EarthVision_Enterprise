"""Validate that each website backup folder can be restored later.

This does not modify production websites, Nginx, Docker, or databases.
A copy of files + SQL is not enough: each site folder must contain the
restore contract (manifest, dumps, configs, docker metadata).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from app.backup.checksum import sha256_file
from app.backup.domain_map import DomainMap, SiteSpec, inferred_db_container

MANIFEST_NAME = "manifest.json"
REQUIRED_MANIFEST_KEYS = (
    "canonical_hostname",
    "aliases",
    "application_id",
    "application_type",
    "database_name",
    "database_container",
    "nginx_configuration_files",
    "docker",
    "source_locations",
    "backup_timestamp",
    "backup_version",
    "file_count",
    "database_dump_filename",
    "checksums",
)


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _load_manifest(folder: Path) -> dict[str, Any]:
    path = folder / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _primary_dump_name(site: SiteSpec) -> str:
    if not site.databases:
        return ""
    return f"{site.databases[0].name}.sql"


def validate_website_folder(
    folder: str | Path,
    site: SiteSpec | None = None,
    *,
    expected_file_count: int | None = None,
) -> dict[str, Any]:
    """Inspect one BACKUPS/<domain> folder. Never touches production."""
    root = Path(folder)
    checks: list[dict[str, Any]] = []
    unresolved: list[str] = []
    excluded: list[str] = []
    missing_required = False

    def add(name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        nonlocal missing_required
        checks.append({"name": name, "ok": ok, "detail": detail, "required": required})
        if ok:
            return
        if required:
            missing_required = True
            unresolved.append(f"{name}: {detail}")
        else:
            excluded.append(f"{name}: {detail}")

    manifest = _load_manifest(root)
    add(
        "manifest.json",
        bool(manifest),
        "present" if manifest else "missing or invalid JSON",
    )
    if manifest:
        missing_keys = [key for key in REQUIRED_MANIFEST_KEYS if key not in manifest]
        add(
            "manifest fields",
            not missing_keys,
            "complete" if not missing_keys else "missing: " + ", ".join(missing_keys),
        )

    website_dir = root / "website"
    website_files = _count_files(website_dir)
    bind_roots = []
    if site is not None:
        bind_roots = [p for p in [site.application_root, *site.storage_roots] if p]
    if website_files > 0:
        add("website/", True, f"{website_files} files")
    elif bind_roots:
        add(
            "website/",
            True,
            "no files copied from documented bind-mount paths (source tree may be empty)",
            required=False,
        )
        excluded.append("website bind-mount paths recorded but no files were inventoried: " + ", ".join(bind_roots))
    else:
        add(
            "website/",
            True,
            "empty (proxy/Docker site with no bind-mounted host files)",
            required=False,
        )

    database_dir = root / "database"
    dump_name = ""
    if site is not None:
        dump_name = _primary_dump_name(site)
    if not dump_name and manifest.get("database_dump_filename"):
        dump_name = str(manifest.get("database_dump_filename") or "")
    dump_path = database_dir / dump_name if dump_name else None
    postgres_only = bool(
        site
        and site.databases
        and all("postgres" in str(db.db_type or "").lower() for db in site.databases)
    )
    if site is not None and site.databases:
        present = bool(dump_path and dump_path.is_file() and dump_path.stat().st_size > 0)
        if postgres_only and not present:
            add(
                "database dump",
                True,
                f"{site.databases[0].name} is PostgreSQL; SQL dump is omitted unless dumped",
                required=False,
            )
        else:
            add(
                "database dump",
                present,
                f"{site.folder}/database/{dump_name}" if present else f"missing {dump_name}",
            )
            if present and dump_path is not None:
                digest = sha256_file(dump_path)
                checksums = manifest.get("checksums") if isinstance(manifest.get("checksums"), dict) else {}
                recorded = str(checksums.get(f"database/{dump_name}") or checksums.get(dump_name) or "")
                if recorded:
                    add(
                        "database checksum",
                        recorded.lower() == digest.lower(),
                        digest if recorded.lower() == digest.lower() else f"mismatch recorded={recorded} actual={digest}",
                    )
                else:
                    add("database checksum", True, digest, required=False)
    else:
        add("database dump", True, "no associated database", required=False)

    nginx_dir = root / "nginx"
    nginx_files = _count_files(nginx_dir)
    if nginx_files:
        add("nginx/", True, f"{nginx_files} files")
    elif site is not None and site.nginx_source_files:
        add(
            "nginx/",
            True,
            "Nginx source files were recorded but not present in this inventory copy",
            required=False,
        )
        excluded.append("nginx source listed but not copied: " + ", ".join(site.nginx_source_files))
    else:
        add("nginx/", True, "no per-site Nginx file recorded", required=False)

    docker_dir = root / "docker"
    if site is not None and site.docker:
        info = docker_dir / "container-info.json"
        add(
            "docker metadata",
            info.is_file(),
            "docker/container-info.json" if info.is_file() else "missing docker/container-info.json",
        )
        compose_name = str((site.docker or {}).get("compose_file") or (site.docker or {}).get("compose_files") or "")
        compose_leaf = compose_name.rsplit("/", 1)[-1] if compose_name else ""
        if compose_leaf:
            compose_copied = (docker_dir / compose_leaf).is_file()
            add(
                "docker compose file",
                compose_copied,
                f"docker/{compose_leaf}" if compose_copied else f"{compose_leaf} was not copied (path may be outside inventory)",
                required=False,
            )
        if site.named_volumes:
            excluded.append(
                "named Docker volumes not copied from /var/lib/docker: " + ", ".join(site.named_volumes)
            )
            add(
                "named volumes",
                True,
                "recorded in docker metadata; not copied from Docker internal storage",
                required=False,
            )
    else:
        add("docker metadata", True, "not a Docker site", required=False)

    ssl_files = _count_files(nginx_dir / "ssl") if nginx_dir.exists() else 0
    if ssl_files:
        add("ssl material", True, f"{ssl_files} files under nginx/ssl", required=False)
    else:
        add(
            "ssl material",
            True,
            "Let's Encrypt files were not in this inventory; add /etc/letsencrypt to extra directories to include certificates",
            required=False,
        )
        excluded.append("SSL certificates not inventoried unless /etc/letsencrypt is an extra source")

    if expected_file_count is not None and expected_file_count > 0 and website_files + nginx_files == 0:
        add("file count", False, f"expected about {expected_file_count} inventoried files")

    if missing_required:
        status = "INCOMPLETE"
    elif excluded:
        status = "PARTIAL"
    else:
        status = "COMPLETE"

    return {
        "domain": (site.domain if site else manifest.get("canonical_hostname")) or root.name,
        "folder": root.name,
        "status": status,
        "ok": status != "INCOMPLETE",
        "checks": checks,
        "unresolved": unresolved,
        "excluded": excluded,
        "file_count": website_files + nginx_files + _count_files(database_dir) + _count_files(docker_dir),
        "website_files": website_files,
        "nginx_files": nginx_files,
        "ssl_files": ssl_files,
        "dump_filename": dump_name,
        "manifest": bool(manifest),
    }


def validate_readable_tree(
    root: str | Path,
    domain_map: DomainMap | None = None,
) -> dict[str, Any]:
    """Validate every website folder under BACKUPS/. Does not touch production."""
    base = Path(root)
    sites = list(domain_map.sites) if domain_map is not None else []
    rows: list[dict[str, Any]] = []
    if sites:
        for site in sites:
            rows.append(validate_website_folder(base / site.folder, site))
    else:
        for child in sorted(base.iterdir()) if base.is_dir() else []:
            if not child.is_dir() or child.name.startswith("_"):
                continue
            if not (child / MANIFEST_NAME).is_file() and not (child / "website").exists():
                continue
            rows.append(validate_website_folder(child))
    incomplete = [row for row in rows if row.get("status") == "INCOMPLETE"]
    partial = [row for row in rows if row.get("status") == "PARTIAL"]
    complete = [row for row in rows if row.get("status") == "COMPLETE"]
    overall = "INCOMPLETE" if incomplete else ("PARTIAL" if partial else "COMPLETE")
    return {
        "ok": not incomplete,
        "status": overall,
        "websites": rows,
        "complete": len(complete),
        "partial": len(partial),
        "incomplete": len(incomplete),
        "note": (
            "Restore validation checks each website folder locally. "
            "It does not start a production restore."
        ),
    }


def predicted_restore_status(site: SiteSpec, *, file_count: int, dump_expected: bool, dump_object_present: bool) -> dict[str, Any]:
    """Dry-run prediction: what restore validation will require after BACKUP NOW."""
    unresolved: list[str] = []
    excluded: list[str] = []
    if dump_expected and not dump_object_present:
        unresolved.append("database dump is not in this generation yet (created on BACKUP NOW)")
    if site.all_file_roots() and file_count <= 0:
        unresolved.append("no inventoried website files for documented persistent paths")
    if site.nginx_source_files and file_count >= 0:
        pass
    if site.named_volumes:
        excluded.append("named Docker volumes will not be copied: " + ", ".join(site.named_volumes))
    excluded.append("SSL certificates included only if /etc/letsencrypt is inventoried")
    if unresolved:
        status = "INCOMPLETE"
    elif excluded:
        status = "PARTIAL — restore-ready for bind-mounted files + SQL; named volumes/SSL caveats"
    else:
        status = "COMPLETE"
    docker = site.docker or {}
    return {
        "status": status,
        "ok": status != "INCOMPLETE",
        "unresolved": unresolved,
        "excluded": excluded,
        "application_id": site.application_id,
        "database_container": (site.databases[0].docker_container if site.databases else "")
        or inferred_db_container(docker),
    }


def format_restore_validation(result: dict[str, Any]) -> str:
    lines = [
        "RESTORE VALIDATION",
        f"  overall: {result.get('status')}",
        f"  complete={result.get('complete', 0)} partial={result.get('partial', 0)} incomplete={result.get('incomplete', 0)}",
        f"  {result.get('note') or ''}",
    ]
    for row in result.get("websites") or []:
        lines.append(f"  {row.get('domain')}: {row.get('status')}")
        for check in row.get("checks") or []:
            mark = "OK" if check.get("ok") else "FAIL"
            lines.append(f"    [{mark}] {check.get('name')}: {check.get('detail')}")
        for item in row.get("unresolved") or []:
            lines.append(f"    unresolved: {item}")
        for item in row.get("excluded") or []:
            lines.append(f"    excluded: {item}")
    return "\n".join(lines)
