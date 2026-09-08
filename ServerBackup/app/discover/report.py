"""Human-readable DISCOVERY REPORT. No passwords or secrets."""

from __future__ import annotations

from typing import Any

from app.utils.format import format_bytes


def format_discovery_report(result: dict[str, Any]) -> str:
    apps = list(result.get("applications") or [])
    new = [a for a in apps if a.get("change") == "new" or str(a.get("status") or "").startswith("NEW SITE")]
    removed = [a for a in apps if a.get("change") == "removed" or "REMOVED" in str(a.get("status") or "")]
    changed = [a for a in apps if a.get("change") not in {"new", "removed", "unchanged", "excluded", None}]
    review = [a for a in apps if "REVIEW" in str(a.get("status") or "") or a.get("status") == "NEW SITE DETECTED"]
    approved = [a for a in apps if a.get("included")]
    ojs = [a for a in apps if a.get("type") == "OJS"]
    lines = [
        "DISCOVERY REPORT",
        f"Host: {result.get('hostname') or 'unknown'}",
        f"Source: {result.get('discovery_source') or 'nginx -T'}",
        f"Nginx: {'OK' if result.get('nginx_ok') else 'FAILED'}",
        f"Total discovered applications: {len([a for a in apps if a.get('change') != 'removed'])}",
        f"Approved: {len(approved)}",
        f"Needs review: {len(review)}",
        f"Removed since last run: {len(removed)}",
        "",
        "DISCOVERED APPLICATIONS",
        "Hostname | Type | Root | Database | Persistent Data | Status",
    ]
    for app in apps:
        db = ""
        if app.get("database_type") or app.get("database_name"):
            db = f"{app.get('database_type') or ''}: {app.get('database_name') or ''}".strip(": ")
        persist = ", ".join(app.get("persistent_data_paths") or []) or "—"
        root = app.get("root") or (app.get("docker") or {}).get("compose_file") or ", ".join(app.get("proxy_pass") or []) or "—"
        lines.append(
            f"{app.get('hostname')} | {app.get('type')} | {root} | {db or '—'} | {persist} | {app.get('status')}"
        )
        for note in app.get("notes") or []:
            lines.append(f"    note: {note}")
    lines.extend(["", "NEW APPLICATIONS"])
    if new:
        for app in new:
            lines.append(f"  NEW SITE DETECTED  {app.get('hostname')}  {app.get('type')}  {app.get('root') or ''}")
            lines.append(f"    database: {app.get('database_type') or '—'} {app.get('database_name') or ''}".rstrip())
            lines.append(f"    persistent: {', '.join(app.get('persistent_data_paths') or []) or '—'}")
            lines.append(f"    estimated size: {format_bytes(int(app.get('estimated_bytes') or 0))}")
            lines.append("    Requires approval before the first backup of this site.")
    else:
        lines.append("  (none)")
    lines.extend(["", "REMOVED APPLICATIONS"])
    if removed:
        for app in removed:
            lines.append(f"  Previously backed up: {app.get('hostname')}")
            lines.append("  No longer detected in active Nginx configuration.")
            lines.append("  Master data is NOT deleted. Review before removing from the backup set.")
    else:
        lines.append("  (none)")
    if changed:
        lines.extend(["", "CHANGED APPLICATIONS"])
        for app in changed:
            lines.append(f"  {app.get('hostname')}: {app.get('change')}")
    lines.extend(["", "OJS INSTALLATIONS"])
    if ojs:
        for app in ojs:
            lines.append(f"  {app.get('hostname')}")
            lines.append(f"    application root: {app.get('root')}")
            lines.append(f"    OJS private files: {app.get('ojs_files_dir') or 'MISSING'}")
            if app.get("notes"):
                lines.append(f"    status: {app.get('status')} ({'; '.join(app.get('notes'))})")
    else:
        lines.append("  (none)")
    dbs = result.get("databases") or {}
    lines.extend(
        [
            "",
            "DATABASES",
            f"  MariaDB: {', '.join(dbs.get('mariadb') or []) or '(none discovered)'}",
            f"  PostgreSQL: {', '.join(dbs.get('postgresql') or []) or '(none discovered)'}",
            "",
            "PERSISTENT STORAGE",
        ]
    )
    persist_all = sorted({p for app in apps for p in (app.get("persistent_data_paths") or [])})
    if persist_all:
        lines.extend(f"  {path}" for path in persist_all)
    else:
        lines.append("  (none beyond application roots)")
    if result.get("errors"):
        lines.extend(["", "ERRORS / WARNINGS"])
        lines.extend(f"  {item}" for item in result["errors"])
    lines.extend(
        [
            "",
            "Backup engine is unchanged in this discovery build.",
            "DISCOVER → CLASSIFY → VALIDATE → SHOW USER → APPROVE.",
            "BACKUP NOW still uses the previous source list until discovery is wired in.",
        ]
    )
    return "\n".join(lines)
