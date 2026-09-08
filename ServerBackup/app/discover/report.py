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


def _detail_for(app: dict[str, Any], hostname: str) -> dict[str, Any]:
    details = app.get("hostname_details") or {}
    if isinstance(details, dict) and hostname in details and isinstance(details[hostname], dict):
        return details[hostname]
    files = app.get("source_files") or []
    source = str(app.get("source_file") or (files[0] if files else "") or "")
    return {
        "source_file": source,
        "root": app.get("root") or "",
        "alias": app.get("alias") or [],
        "proxy_pass": app.get("proxy_pass") or [],
        "redirect_to": app.get("redirect_to") or "",
        "listen": app.get("listen") or [],
    }


def _fmt_list(values: Any) -> str:
    if not values:
        return "(none)"
    if isinstance(values, list):
        return ", ".join(str(item) for item in values if item) or "(none)"
    return str(values)


def _hostname_lines(name: str, app: dict[str, Any]) -> list[str]:
    meta = _detail_for(app, name)
    names = _hostnames(app)
    canonical = str(app.get("hostname") or "")
    role = "canonical"
    if len(names) > 1 and name != canonical:
        role = f"alias of {canonical}"
    root = meta.get("root") or app.get("root") or "—"
    lines = [
        f"  {name}",
        f"    application: {app.get('application_id') or '—'}",
        f"    role: {role}",
        f"    nginx file: {meta.get('source_file') or app.get('source_file') or '—'}",
        f"    root: {root or '—'}",
        f"    alias: {_fmt_list(meta.get('alias') or app.get('alias'))}",
        f"    proxy_pass: {_fmt_list(meta.get('proxy_pass') or app.get('proxy_pass'))}",
        f"    redirect: {meta.get('redirect_to') or app.get('redirect_to') or '(none)'}",
        f"    database: {_db_label(app)}",
        f"    status: {app.get('status') or '—'}",
    ]
    return lines


def format_application_sections(
    applications: list[dict[str, Any]],
    *,
    databases: dict[str, Any] | None = None,
    nginx_inventory: list[dict[str, Any]] | None = None,
    parsed_hostnames: list[str] | None = None,
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
    hosts: list[tuple[str, dict[str, Any]]] = []
    seen_hosts: set[str] = set()
    for app in live:
        names = _hostnames(app)
        if not names:
            hosts.append((str(app.get("hostname") or "—"), app))
            continue
        for name in names:
            key = name.lower()
            if key in seen_hosts:
                continue
            seen_hosts.add(key)
            hosts.append((name, app))
    if parsed_hostnames:
        by_lower = {name.lower(): app for name, app in hosts}
        missing = [name for name in parsed_hostnames if name.lower() not in by_lower and name.lower() not in {"", "*"}]
        for name in missing:
            hosts.append((name, {"application_id": "MISSING", "status": "REQUIRES REVIEW", "hostname": name, "hostnames": [name]}))

    lines: list[str] = ["DISCOVERED HOSTNAMES"]
    if hosts:
        for name, app in hosts:
            lines.extend(_hostname_lines(name, app))
    else:
        lines.append("  (none)")

    lines.extend(["", "DISCOVERED APPLICATIONS"])
    lines.append(
        f"  total={len(live)} included={len(included)} excluded={len(excluded)} pending_approval={len(live) - len(included) - len(excluded)}"
    )
    lines.append("  application_id | hostnames | type | root | database | status")
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

    lines.extend(["", "HOSTNAME ALIASES"])
    aliased = [app for app in live if len(_hostnames(app)) > 1]
    if aliased:
        for app in aliased:
            names = _hostnames(app)
            canonical = str(app.get("hostname") or names[0])
            lines.append(f"  {app.get('application_id')}  canonical={canonical}  database={_db_label(app)}")
            for name in names:
                marker = " (canonical)" if name == canonical else ""
                meta = _detail_for(app, name)
                src = meta.get("source_file") or app.get("source_file") or "—"
                lines.append(f"    {name}{marker}")
                lines.append(f"      nginx file: {src}")
                lines.append(f"      root: {meta.get('root') or app.get('root') or '—'}")
                lines.append(f"      alias: {_fmt_list(meta.get('alias') or app.get('alias'))}")
                lines.append(f"      proxy_pass: {_fmt_list(meta.get('proxy_pass') or app.get('proxy_pass'))}")
    else:
        lines.append("  (none)")

    lines.extend(["", "EXCLUDED ROOTS"])
    excluded_roots = [
        app
        for app in live
        if app.get("excluded") or app.get("unused_default_root") or "EXCLUDED" in str(app.get("status") or "")
    ]
    if excluded_roots:
        for app in excluded_roots:
            lines.append(f"  {app.get('root') or '—'}  hostnames={', '.join(_hostnames(app)) or '—'}  {app.get('status')}")
            for note in app.get("notes") or []:
                lines.append(f"    note: {note}")
    else:
        lines.append("  (none)")

    if nginx_inventory:
        lines.extend(["", "NGINX SERVER BLOCKS"])
        for block in nginx_inventory:
            names = ", ".join(str(n) for n in (block.get("server_name") or []) if n) or "—"
            lines.append(f"  {block.get('source_file') or 'unknown'}")
            lines.append(f"    server_name: {names}")
            lines.append(f"    root: {block.get('root') or '—'}")
            lines.append(f"    alias: {_fmt_list(block.get('alias'))}")
            lines.append(f"    proxy_pass: {_fmt_list(block.get('proxy_pass'))}")
            lines.append(f"    redirect: {block.get('redirect_to') or '(none)'}")
            lines.append(f"    listen: {_fmt_list(block.get('listen'))}")

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
            for note in app.get("notes") or []:
                lines.append(f"    note: {note}")
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
        *format_application_sections(
            apps,
            databases=result.get("databases"),
            nginx_inventory=result.get("nginx_inventory") or result.get("servers"),
            parsed_hostnames=result.get("parsed_hostnames"),
        ),
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
