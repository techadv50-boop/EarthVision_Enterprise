"""Human-readable DISCOVERY REPORT. No passwords or secrets."""

from __future__ import annotations

from typing import Any

from app.utils.format import format_bytes


def _hostnames(app: dict[str, Any]) -> list[str]:
    names = [str(n) for n in (app.get("hostnames") or []) if n]
    primary = str(app.get("hostname") or "")
    if primary and primary not in names:
        names.insert(0, primary)
    return names


def _db_label(app: dict[str, Any]) -> str:
    if app.get("database_type") or app.get("database_name"):
        return f"{app.get('database_type') or ''} {app.get('database_name') or ''}".strip()
    return "—"


def format_application_sections(
    applications: list[dict[str, Any]],
    *,
    databases: dict[str, Any] | None = None,
) -> list[str]:
    apps = list(applications or [])
    live = [a for a in apps if a.get("change") != "removed"]
    included = [a for a in live if a.get("included")]
    excluded = [
        a
        for a in live
        if a.get("excluded") or a.get("unused_default_root") or "EXCLUDED" in str(a.get("status") or "")
    ]
    review = [
        a
        for a in apps
        if "REVIEW" in str(a.get("status") or "") and "REQUIRES APPROVAL" not in str(a.get("status") or "")
    ]
    ojs = [a for a in live if a.get("type") == "OJS"]
    lines: list[str] = ["DISCOVERED HOSTNAMES"]
    hosts: list[tuple[str, dict[str, Any]]] = []
    for app in live:
        names = _hostnames(app)
        if not names:
            hosts.append((str(app.get("hostname") or "—"), app))
            continue
        for name in names:
            hosts.append((name, app))
    if hosts:
        for name, app in hosts:
            root = app.get("root") or ", ".join(app.get("proxy_pass") or []) or "—"
            alias = ""
            names = _hostnames(app)
            if len(names) > 1:
                others = [h for h in names if h != name]
                alias = f"  alias-of {app.get('application_id')} ({', '.join(others)})"
            lines.append(f"  {name} -> {root}{alias}")
    else:
        lines.append("  (none)")
    lines.extend(
        [
            "",
            "DISCOVERED APPLICATIONS",
            f"  total={len(live)} included={len(included)} excluded={len(excluded)} pending_approval={len(live) - len(included) - len(excluded)}",
            "  application_id | hostnames | type | root | database | status",
        ]
    )
    if live:
        for app in live:
            names = ", ".join(_hostnames(app)) or str(app.get("hostname") or "—")
            root = app.get("root") or ", ".join(app.get("proxy_pass") or []) or "—"
            lines.append(
                f"  {app.get('application_id')} | {names} | {app.get('type')} | {root} | {_db_label(app)} | {app.get('status')}"
            )
            for note in app.get("notes") or []:
                lines.append(f"    note: {note}")
    else:
        lines.append("  (none)")
    dbs = databases if isinstance(databases, dict) else {}
    lines.extend(["", "DATABASES"])
    mariadb = list(dbs.get("mariadb") or [])
    postgres = list(dbs.get("postgresql") or [])
    if not mariadb:
        mariadb = sorted(
            {
                str(app.get("database_name"))
                for app in live
                if app.get("database_type") == "MariaDB" and app.get("database_name")
            }
        )
    if not postgres:
        postgres = sorted(
            {
                str(app.get("database_name"))
                for app in live
                if app.get("database_type") == "PostgreSQL" and app.get("database_name")
            }
        )
    lines.append(f"  MariaDB: {', '.join(mariadb) if mariadb else '(none discovered)'}")
    for app in live:
        if app.get("database_type") == "MariaDB" and app.get("database_name"):
            lines.append(
                f"    {app.get('database_name')} <- {app.get('application_id')} ({', '.join(_hostnames(app))})"
            )
    lines.append(f"  PostgreSQL: {', '.join(postgres) if postgres else '(none discovered)'}")
    for app in live:
        if app.get("database_type") == "PostgreSQL" and app.get("database_name"):
            lines.append(
                f"    {app.get('database_name')} <- {app.get('application_id')} ({', '.join(_hostnames(app))})"
            )
    lines.extend(["", "OJS FILES_DIR"])
    if ojs:
        for app in ojs:
            lines.append(f"  {', '.join(_hostnames(app))}")
            lines.append(f"    application root: {app.get('root')}")
            lines.append(f"    OJS private files: {app.get('ojs_files_dir') or 'MISSING'}")
    else:
        lines.append("  (none)")
    lines.extend(["", "INCLUDED APPLICATIONS"])
    if included:
        for app in included:
            lines.append(f"  {app.get('application_id')}  {', '.join(_hostnames(app))}  APPROVED")
    else:
        lines.append("  (none)  approved=0")
    lines.extend(["", "EXCLUDED APPLICATIONS"])
    if excluded:
        for app in excluded:
            lines.append(f"  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('status')}")
            for note in app.get("notes") or []:
                lines.append(f"    note: {note}")
    else:
        lines.append("  (none)")
    lines.extend(["", "REQUIRES REVIEW"])
    if review:
        for app in review:
            lines.append(f"  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('status')}")
    else:
        lines.append("  (none)")
    return lines


def format_discovery_report(result: dict[str, Any]) -> str:
    apps = list(result.get("applications") or [])
    new = [a for a in apps if a.get("change") == "new" or "NEW SITE DETECTED" in str(a.get("status") or "")]
    removed = [a for a in apps if a.get("change") == "removed" or "SITE REMOVED" in str(a.get("status") or "")]
    lines = [
        "DISCOVERY REPORT",
        f"Host: {result.get('hostname') or 'unknown'}",
        f"Source: {result.get('discovery_source') or 'nginx -T'}",
        f"Nginx: {'OK' if result.get('nginx_ok') else 'FAILED'}",
        "",
        *format_application_sections(apps, databases=result.get("databases")),
        "",
        "NEW APPLICATIONS",
    ]
    if new:
        for app in new:
            lines.append(
                f"  NEW SITE DETECTED  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('type')}  {app.get('root') or ''}"
            )
            lines.append(f"    database: {_db_label(app)}")
            lines.append(f"    estimated size: {format_bytes(int(app.get('estimated_bytes') or 0))}")
            lines.append("    Requires explicit approval before the first backup of this application.")
    else:
        lines.append("  (none)")
    lines.extend(["", "REMOVED APPLICATIONS"])
    if removed:
        for app in removed:
            lines.append(f"  Previously discovered: {app.get('application_id')} ({', '.join(_hostnames(app))})")
            lines.append("  No longer detected in active Nginx configuration.")
            lines.append("  Master data is NOT deleted. Review before removing from the backup set.")
    else:
        lines.append("  (none)")
    if result.get("errors"):
        lines.extend(["", "ERRORS / WARNINGS"])
        lines.extend(f"  {item}" for item in result["errors"])
    lines.extend(
        [
            "",
            "DISCOVER → CLASSIFY → VALIDATE → SHOW USER → APPROVE → DRY RUN → BACKUP.",
            "A newly discovered application or hostname alias is not backed up until it is approved.",
            "Removed sites are kept in the master until you review them.",
            "BACKUP NOW is not run by discovery or DRY RUN.",
        ]
    )
    return "\n".join(lines)
