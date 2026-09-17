"""Human-readable DISCOVERY REPORT. No passwords or secrets."""

from __future__ import annotations

from typing import Any

from app.discover.gate import assess_backup_gate, format_backup_gate


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
        f"    nginx/traefik file: {meta.get('source_file') or app.get('source_file') or '—'}",
        f"    root: {root or '—'}",
        f"    alias: {_fmt_list(meta.get('alias') or app.get('alias'))}",
        f"    proxy_pass: {_fmt_list(meta.get('proxy_pass') or app.get('proxy_pass'))}",
        f"    redirect: {meta.get('redirect_to') or app.get('redirect_to') or '(none)'}",
        f"    database: {_db_label(app) if _db_label(app) != '—' else (app.get('database_status') or 'UNRESOLVED')}",
        f"    ssl: {((app.get('ssl') or {}).get('mechanism') if isinstance(app.get('ssl'), dict) else '') or ('https' if app.get('https') else 'none')}",
        f"    ssl storage: {_fmt_list((app.get('ssl') or {}).get('storage_paths') or (app.get('ssl') or {}).get('acme_file') or (app.get('ssl') or {}).get('certificate'))}",
        f"    ssl restore: {((app.get('ssl') or {}).get('restore_procedure') if isinstance(app.get('ssl'), dict) else '') or 'not identified'}",
        f"    restore ready: {(app.get('restore') or {}).get('restore_ready') or 'NO'}",
        f"    status: {app.get('status') or '—'}",
    ]
    return lines


def format_server_wide_discovery_report(result: dict[str, Any]) -> list[str]:
    totals = result.get("discovery_totals") if isinstance(result.get("discovery_totals"), dict) else {}
    classified = list(result.get("classified") or [])
    host_rows = [row for row in classified if row.get("kind") == "hostname"]
    lines = [
        "SERVER-WIDE DISCOVERY REPORT",
        f"  TOTAL HOSTNAMES DISCOVERED: {totals.get('hostnames_discovered', len(host_rows))}",
        f"  TOTAL UNIQUE WEBSITES: {totals.get('unique_websites', 0)}",
        f"  TOTAL APPLICATIONS: {totals.get('applications', 0)}",
        f"  TOTAL DATABASES: {totals.get('databases', 0)}",
        f"  TOTAL DOCKER APPLICATIONS: {totals.get('docker_applications', 0)}",
        f"  TOTAL DOCKER VOLUMES: {totals.get('docker_volumes', 0)}",
        f"  TOTAL NGINX SERVER BLOCKS: {totals.get('nginx_server_blocks', 0)}",
        f"  TOTAL HTTPS SITES: {totals.get('https_sites', 0)}",
        "",
        "DOMAIN | ROLE | APPLICATION | TYPE | SOURCE | DOCKER | DATABASE | NGINX | SSL | SIZE | FILES | STATUS",
    ]
    if host_rows:
        for row in host_rows:
            db = row.get("database")
            if db in {None, ""}:
                db = "UNRESOLVED"
            lines.append(
                " | ".join(
                    [
                        str(row.get("hostname") or "—"),
                        str(row.get("hostname_role") or "—"),
                        str(row.get("application") or "—"),
                        str(row.get("type") or "—"),
                        str(row.get("source_path") or row.get("discovery_source") or "—"),
                        str(row.get("docker") or "—"),
                        str(db),
                        str(row.get("nginx") or "—"),
                        str(row.get("ssl") or "—"),
                        str(row.get("size_bytes") if row.get("size_bytes") is not None else 0),
                        str(row.get("file_count") if row.get("file_count") is not None else 0),
                        str(row.get("classification") or row.get("status") or "—"),
                    ]
                )
            )
    else:
        lines.append("  (none)")
    lines.extend(["", "WHY NGINX-ONLY AND LABEL-ONLY DISCOVERY MISSED WEBSITES"])
    lines.append(
        "  Previous versions created backup applications only from `nginx -T` server_name."
    )
    lines.append(
        "  1.4.24 also read Docker Traefik Host() labels and VIRTUAL_HOST, then scanned"
    )
    lines.append(
        "  /etc/dokploy for Host() in YAML — but unmatched file Host() names were classified"
    )
    lines.append(
        "  as LEGACY leftovers, so they never appeared in the hostname or application inventory."
    )
    lines.append(
        "  Dokploy Application routes live in Traefik dynamic YAML (Host() + backend url),"
    )
    lines.append(
        "  not in docker inspect labels and not in nginx -T. Those YAML files are often"
    )
    lines.append(
        "  mode 600 root:root, so the serverbackup account can see the directory and still"
    )
    lines.append(
        "  read zero Host() rules from disk."
    )
    lines.append(
        "  This engine promotes live Traefik/Dokploy Host() routes to applications, including"
    )
    lines.append(
        "  routes harvested with docker exec against the Traefik API or mounted dynamic files."
    )
    lines.append(
        "  PUBLIC_HOST / SITE_URL are advertised aliases of the same compose project, not new websites. "
        "CORS, API URLs, and image documentation URLs are configuration/placeholder records."
    )
    lines.append("  No production hostname is hard-coded. A new Host() route is enough.")
    missed = [
        row
        for row in host_rows
        if "nginx -T" not in str(row.get("discovery_source") or "")
        and str(row.get("classification") or "") == "ACTIVE WEBSITE"
    ]
    if missed:
        for row in missed:
            lines.append(
                f"  {row.get('hostname')}  source={row.get('discovery_source') or '—'}  "
                f"{row.get('classification') or row.get('status')}"
            )
    else:
        lines.append("  (every classified hostname was also in nginx -T, or none extra were found)")
    lines.extend(["", "HOSTNAMES ABSENT FROM NGINX -T"])
    if missed:
        for row in missed:
            restore_missing = row.get("restore_missing") or []
            lines.append(f"  DOMAIN: {row.get('hostname')}")
            lines.append("    FOUND: YES")
            lines.append(f"    WHERE FOUND: {row.get('discovery_source') or '—'}")
            lines.append(f"    CONFIGURATION FILE: {row.get('nginx') or row.get('source_path') or '—'}")
            lines.append("    SERVER BLOCK: Traefik/Dokploy Host() route (not an Nginx server_name)")
            lines.append(f"    APPLICATION: {row.get('application') or '—'}")
            lines.append(f"    CONTAINER / DOCKER PROJECT: {row.get('docker') or '—'}")
            lines.append(f"    SOURCE/PERSISTENT PATH: {row.get('source_path') or '—'}")
            lines.append(f"    DATABASE: {row.get('database') or 'UNRESOLVED'}")
            lines.append(f"    SSL: {row.get('ssl') or 'none'}")
            ssl_detail = ""
            app_ssl = {}
            for app in result.get("applications") or []:
                if str(row.get("hostname") or "") in [str(n) for n in (app.get("hostnames") or [])]:
                    app_ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
                    break
            if app_ssl.get("restore_procedure"):
                lines.append(f"    SSL RESTORE: {app_ssl.get('restore_procedure')}")
            if app_ssl.get("storage_paths"):
                lines.append(f"    SSL STORAGE: {', '.join(str(p) for p in app_ssl.get('storage_paths') if p)}")
            elif app_ssl.get("acme_file"):
                lines.append(f"    SSL STORAGE: {app_ssl.get('acme_file')}")
            lines.append(f"    CURRENT STATUS: {row.get('classification') or row.get('status') or '—'}")
            lines.append(
                "    REASON PREVIOUS DISCOVERY MISSED IT: Host() lived in Traefik/Dokploy YAML "
                "(not nginx -T and not docker inspect labels). 1.4.24 classified unmatched file "
                "Host() as NOT ACTIVE leftovers. If the YAML is unreadable by serverbackup, "
                "disk scans return empty; 1.4.26 reads the live Traefik API / docker exec files. "
                "1.4.27 classifies Host() vs PUBLIC_HOST vs CORS/API/image URLs and probes PostgreSQL with pg_dump. "
                "1.4.28 traces each localhost proxy_pass target to the owning container/process via ss + /proc, "
                "so reverse-proxied sites resolve to a real application, persistent files, and database. "
                "1.4.29 also follows docker-proxy -container-ip, reads DATABASE_URL/DB_DATABASE-style env "
                "for database ownership, derives a compose project from the container name, and records the "
                "owning domain for cache/redis volumes so nothing is left UNRESOLVED."
            )
            lines.append(
                f"    RESTORE READY: {row.get('restore_ready') or 'NO'}"
                + (f"  missing: {', '.join(str(item) for item in restore_missing)}" if restore_missing else "")
            )
    else:
        lines.append("  (none)")
    lines.extend(["", "RESTORE READY BY WEBSITE"])
    restore_rows = [
        row
        for row in host_rows
        if (row.get("classification") == "ACTIVE WEBSITE" or row.get("application"))
        and not str(row.get("hostname_role") or "").startswith("alias")
    ]
    if restore_rows:
        for row in restore_rows:
            missing = row.get("restore_missing") or []
            lines.append(
                f"  {row.get('hostname')}: {row.get('restore_ready') or 'NO'}"
                + (f"  missing: {', '.join(str(item) for item in missing)}" if missing else "")
            )
    else:
        lines.append("  (none)")
    volumes = list(result.get("docker_volumes") or [])
    lines.extend(["", "DOCKER NAMED VOLUMES"])
    if volumes:
        for vol in volumes:
            lines.append(
                f"  {vol.get('name')}  container={vol.get('container') or '—'}  "
                f"mount={vol.get('mount_point') or '—'}  purpose={vol.get('purpose')}  "
                f"website={vol.get('website') or '—'}  backup={vol.get('backup_status')}  "
                f"{vol.get('classification')}"
            )
            if vol.get("notes"):
                lines.append(f"    {vol.get('notes')}")
    else:
        lines.append("  (none)")
    lines.extend(["", "DOCKER VOLUME MATRIX"])
    lines.append(
        "  VOLUME | CONTAINER | MOUNT | PURPOSE | APPLICATION | SCOPE | BACKUP METHOD | SOURCE | DESTINATION | SIZE | FILES | STATUS"
    )
    if volumes:
        for vol in volumes:
            lines.append(
                " | ".join(
                    [
                        str(vol.get("name") or "—"),
                        str(vol.get("container") or "—"),
                        str(vol.get("mount") or vol.get("mount_point") or "—"),
                        str(vol.get("purpose") or "—"),
                        str(vol.get("application") or vol.get("website") or "—"),
                        str(vol.get("scope") or "—"),
                        str(vol.get("backup_method") or vol.get("backup_status") or "—"),
                        str(vol.get("source") or vol.get("host_path") or "—"),
                        str(vol.get("destination") or vol.get("backup_destination") or "—"),
                        str(vol.get("size_bytes") if vol.get("size_bytes") is not None else 0),
                        str(vol.get("file_count") if vol.get("file_count") is not None else 0),
                        str(vol.get("status") or vol.get("classification") or "—"),
                    ]
                )
            )
    else:
        lines.append("  (none)")
    records = list(result.get("hostname_records") or [])
    lines.extend(["", "HOSTNAME INVESTIGATION"])
    lines.append("  Hostname strings from labels/env/compose/Traefik are classified. Only routing Host() becomes a website.")
    if records:
        for rec in records:
            lines.append(
                f"  {rec.get('hostname')}  role={rec.get('role')}  "
                f"source={rec.get('source') or '—'}  key={rec.get('key') or '—'}  "
                f"container={rec.get('container') or '—'}  "
                f"{'assigned website' if rec.get('assigned_website') else 'not a website folder'}"
            )
            if rec.get("evidence"):
                lines.append(f"    evidence: {rec.get('evidence')}")
    else:
        lines.append("  (none)")
    lines.extend(["", "SSL STORAGE AND RESTORE"])
    https_apps = [
        app
        for app in (result.get("applications") or [])
        if isinstance(app, dict) and app.get("https") and app.get("change") not in {"removed", "migrated"}
    ]
    if https_apps:
        for app in https_apps:
            ssl = app.get("ssl") if isinstance(app.get("ssl"), dict) else {}
            names = ", ".join(str(n) for n in (app.get("hostnames") or [app.get("hostname")]) if n)
            lines.append(f"  {app.get('hostname') or names}")
            lines.append(f"    hostnames: {names or '—'}")
            lines.append(f"    mechanism: {ssl.get('mechanism') or 'not identified'}")
            storage = ssl.get("storage_paths") or []
            if ssl.get("acme_file") and ssl.get("acme_file") not in storage:
                storage = [ssl.get("acme_file"), *storage]
            lines.append(f"    certificate files: {_fmt_list(ssl.get('certificate'))}")
            lines.append(f"    private key files: {_fmt_list(ssl.get('certificate_key'))}")
            lines.append(f"    acme/json store: {ssl.get('acme_file') or '(none)'}")
            lines.append(f"    persistent volume: {ssl.get('volume') or '(none)'}")
            lines.append(f"    storage paths: {_fmt_list(storage)}")
            lines.append(f"    restore: {ssl.get('restore_procedure') or ssl.get('backup_treatment') or 'not identified'}")
    else:
        lines.append("  (none)")
    backends = result.get("backend_owners") if isinstance(result.get("backend_owners"), dict) else {}
    proxy_apps = [
        app
        for app in (result.get("applications") or [])
        if isinstance(app, dict) and (app.get("proxy_pass") or [])
        and app.get("change") not in {"removed", "migrated"}
    ]
    if backends or proxy_apps:
        lines.extend(["", "REVERSE PROXY BACKEND RESOLUTION"])
        lines.append("  Each localhost proxy_pass target is traced to the process/container that serves it.")
        if backends:
            for port, owner in sorted(backends.items(), key=lambda item: str(item[0])):
                if not isinstance(owner, dict):
                    continue
                target = owner.get("container_id") or owner.get("cwd") or owner.get("comm") or "unresolved"
                lines.append(
                    f"  127.0.0.1:{port}  process={owner.get('comm') or '—'}  pid={owner.get('pid') or '—'}  "
                    f"container={(owner.get('container_id') or '')[:12] or '—'}  "
                    f"cwd={owner.get('cwd') or '—'}  unit={owner.get('unit') or '—'}"
                )
        else:
            lines.append("  (ss/proc backend resolution produced no listening-socket owners)")
        for app in proxy_apps:
            lines.append(
                f"  {app.get('hostname') or '—'}  proxy_pass={_fmt_list(app.get('proxy_pass'))}  "
                f"application={app.get('application_id') or '—'}  type={app.get('type') or '—'}  "
                f"database={_db_label(app) if _db_label(app) != '—' else (app.get('database_status') or 'UNRESOLVED')}"
            )
    lines.extend(["", "INFRASTRUCTURE / RECOVERY"])
    infra_hosts = [rec for rec in records if rec.get("role") == "infrastructure"]
    infra_vols = [vol for vol in volumes if vol.get("scope") == "infrastructure"]
    infra_dbs = [
        row
        for row in (result.get("database_inventory") or [])
        if row.get("infrastructure") or "INFRASTRUCTURE" in str(row.get("status") or "")
    ]
    if infra_hosts or infra_vols or infra_dbs:
        for rec in infra_hosts:
            lines.append(
                f"  hostname {rec.get('hostname')}  role=infrastructure  "
                f"source={rec.get('source') or '—'}  not a public website folder"
            )
        for vol in infra_vols:
            lines.append(
                f"  volume {vol.get('name')}  container={vol.get('container') or '—'}  "
                f"mount={vol.get('mount') or vol.get('mount_point') or '—'}  "
                f"dest={vol.get('destination') or '—'}  {vol.get('backup_status')}"
            )
        for row in infra_dbs:
            lines.append(
                f"  database {row.get('name')}  {row.get('type') or 'PostgreSQL'}  "
                f"container={row.get('docker_container') or '—'}  "
                f"dump={row.get('dump_destination') or '_server/infrastructure/databases/'}  "
                f"{row.get('status')}"
            )
    else:
        lines.append("  (none discovered)")
    return lines


def format_application_sections(
    applications: list[dict[str, Any]],
    *,
    databases: dict[str, Any] | None = None,
    nginx_inventory: list[dict[str, Any]] | None = None,
    parsed_hostnames: list[str] | None = None,
    database_inventory: list[dict[str, Any]] | None = None,
    inactive_hostnames: list[dict[str, Any]] | None = None,
    gate: dict[str, Any] | None = None,
    database_account: dict[str, Any] | None = None,
) -> list[str]:
    apps = list(applications or [])
    live = [a for a in apps if a.get("change") not in {"removed", "migrated"}]
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

    inventory = list(database_inventory or [])
    if not inventory:
        for name in (databases or {}).get("mariadb") or []:
            inventory.append({"name": name, "type": "MariaDB", "status": "DISCOVERED", "application_id": "", "reason": ""})
        for app in live:
            if app.get("database_name"):
                dname = str(app.get("database_name"))
                for row in inventory:
                    if row.get("name") == dname and not row.get("application_id"):
                        row["application_id"] = app.get("application_id")
                        row["status"] = "ASSOCIATED WITH APPLICATION"
        for row in inventory:
            if not row.get("application_id") and "ASSOCIATED" not in str(row.get("status") or "") and "EXCLUDED" not in str(row.get("status") or ""):
                row["status"] = "UNASSOCIATED DATABASE — REQUIRES REVIEW"
                row["reason"] = row.get("reason") or "no application association discovered"
    unassociated_rows = [
        row
        for row in inventory
        if not row.get("system") and "UNASSOCIATED" in str(row.get("status") or "")
    ]
    recovery_db_rows = [
        row
        for row in inventory
        if not row.get("system") and str(row.get("status") or "").startswith("RECOVERY")
    ]
    excluded_db_rows = [
        row
        for row in inventory
        if not row.get("system") and "EXCLUDED" in str(row.get("status") or "")
    ]
    lines.extend(["", "DISCOVERED DATABASES"])
    lines.append(
        "  DATABASE | ENGINE | CONTAINER | APPLICATION | WEBSITE/INFRASTRUCTURE | SIZE | TABLES | DUMP METHOD | DUMP DESTINATION | DUMP TEST | STATUS"
    )
    if inventory:
        for row in inventory:
            if row.get("system"):
                continue
            scope = "infrastructure" if row.get("infrastructure") or "INFRASTRUCTURE" in str(row.get("status") or "") else "website"
            if str(row.get("status") or "").startswith("RECOVERY"):
                scope = "recovery"
            dump_test = "not probed"
            if row.get("dump_capable") is True:
                dump_test = str(row.get("dump_probe") or "ok")
            elif row.get("dump_capable") is False:
                dump_test = str(row.get("dump_probe") or row.get("size_probe") or "FAILED")
            elif row.get("size_probe"):
                dump_test = str(row.get("size_probe"))
            lines.append(
                " | ".join(
                    [
                        str(row.get("name") or "—"),
                        str(row.get("type") or "MariaDB"),
                        str(row.get("docker_container") or "host"),
                        str(row.get("application_id") or "—"),
                        scope,
                        "unprobed" if row.get("size_bytes") is None else str(row.get("size_bytes")),
                        str(row.get("table_count") if row.get("table_count") is not None else "—"),
                        str(row.get("dump_method") or ("docker exec pg_dump" if "postgres" in str(row.get("type") or "").lower() else "mysqldump")),
                        str(row.get("dump_destination") or "—"),
                        dump_test,
                        str(row.get("status") or "—"),
                    ]
                )
            )
            if row.get("engine_version"):
                lines.append(f"      engine version: {row.get('engine_version')}  user: {row.get('postgres_user') or '—'}")
            if row.get("dump_tools"):
                tools = row.get("dump_tools") or {}
                lines.append(
                    "      tools: "
                    + ", ".join(f"{k}={v}" for k, v in tools.items() if v)
                )
            if "postgres" in str(row.get("type") or "").lower() and row.get("dump_capable") is not True:
                lines.append("      PostgreSQL dump is not validated; this application cannot be RESTORE READY.")
            if row.get("tables"):
                table_names = ", ".join(str(item.get("name") or item) for item in row.get("tables") or [] if item)
                if table_names:
                    lines.append(f"      table_names: {table_names}")
            if row.get("references"):
                paths = ", ".join(str(item.get("path") or "") for item in row.get("references") or [] if item.get("path"))
                if paths:
                    lines.append(f"      config references: {paths}")
        postgres = list((databases or {}).get("postgresql") or [])
        if not postgres:
            postgres = sorted(
                {
                    str(row.get("name"))
                    for row in inventory
                    if "postgres" in str(row.get("type") or "").lower() and row.get("name")
                }
            )
        lines.append(f"  PostgreSQL schemas: {', '.join(postgres) if postgres else '(none discovered)'}")
        maria_names = [
            str(row.get("name"))
            for row in inventory
            if not row.get("system") and "postgres" not in str(row.get("type") or "").lower() and row.get("name")
        ]
        lines.append(f"  MariaDB: {', '.join(maria_names) if maria_names else '(none discovered)'}")
        lines.append(f"  PostgreSQL: {', '.join(postgres) if postgres else '(none discovered)'}")
    else:
        lines.append("  (none discovered)")
    lines.extend(["", "UNASSOCIATED DATABASES"])
    if unassociated_rows:
        for row in unassociated_rows:
            lines.append(f"  {row.get('name')}")
            lines.append(f"    status: {row.get('status')}")
            lines.append(f"    reason: {row.get('reason') or 'no application association discovered'}")
            if row.get("table_count") is not None:
                lines.append(f"    tables: {row.get('table_count')}  size_bytes: {row.get('size_bytes') or 0}")
            if row.get("row_count") is not None:
                lines.append(f"    rows: {row.get('row_count')}")
            if row.get("tables"):
                table_names = ", ".join(str(item.get("name") or item) for item in row.get("tables") or [] if item)
                if table_names:
                    lines.append(f"    table_names: {table_names}")
    else:
        lines.append("  (none)")
    lines.extend(["", "RECOVERY DATABASES"])
    if recovery_db_rows:
        for row in recovery_db_rows:
            lines.append(f"  {row.get('name')}")
            lines.append(f"    status: {row.get('status')}")
            lines.append(f"    reason: {row.get('reason') or 'Dokploy migration leftover'}")
            lines.append("    kept under BACKUPS/_recovery/databases — not a website folder, not silently discarded")
    else:
        lines.append("  (none)")
    lines.extend(["", "EXCLUDED DATABASES"])
    if excluded_db_rows:
        for row in excluded_db_rows:
            lines.append(f"  {row.get('name')}")
            lines.append(f"    status: {row.get('status')}")
            lines.append(f"    reason: {row.get('reason') or 'excluded'}")
    else:
        lines.append("  (none)")
    account = database_account or {}
    lines.extend(["", "DATABASE ACCOUNT"])
    if account:
        lines.append(f"  configured user: {account.get('configured_user') or '—'}")
        lines.append(f"  current_user(): {account.get('current_user') or '—'}")
        if account.get("session_user"):
            lines.append(f"  USER(): {account.get('session_user')}")
        lines.append(f"  source: {account.get('source') or '—'}")
        lines.append(f"  using root: {'yes' if account.get('using_root') else 'no'}")
        if account.get("grants"):
            lines.append(f"  grants: {'; '.join(str(g) for g in account.get('grants') or [])}")
        if account.get("least_privilege"):
            lines.append(f"  least-privilege later: {account.get('least_privilege')}")
        lines.append("  Passwords are not shown. Credentials were not changed.")
    else:
        lines.append("  (not probed)")

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

    lines.extend(["", "NOT ACTIVE IN CURRENT SERVER CONFIGURATION"])
    inactive = list(inactive_hostnames or [])
    if inactive:
        for row in inactive:
            lines.append(f"  {row.get('hostname')}")
            lines.append(f"    verdict: {row.get('verdict') or 'NOT ACTIVE IN CURRENT SERVER CONFIGURATION'}")
            for item in row.get("evidence") or []:
                loc = f" {item.get('file')}" if item.get("file") else ""
                lines.append(f"    evidence: {item.get('source')}{loc} — {item.get('detail')}")
                if item.get("root"):
                    lines.append(f"      configured root: {item.get('root')} (not treated as an active application)")
    else:
        lines.append("  (none)")
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
    computed_gate = gate or assess_backup_gate(live, inventory)
    lines.extend(["", *format_backup_gate(computed_gate)])
    new_apps = [a for a in apps if a.get("change") == "new" or "NEW SITE DETECTED" in str(a.get("status") or "")]
    removed_apps = [a for a in apps if a.get("change") == "removed" or "SITE REMOVED" in str(a.get("status") or "")]
    migrated_apps = [a for a in apps if a.get("change") == "migrated" or "SITE MIGRATED" in str(a.get("status") or "")]
    lines.extend(["", "SITE CLASSIFICATION"])
    lines.append("  1. currently active website")
    active = [a for a in live if a.get("included") and not a.get("excluded")]
    if active:
        for app in active:
            lines.append(f"    ACTIVE  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('type')}")
    else:
        lines.append("    (none approved yet)")
    lines.append("  2. migrated application now running in Docker")
    docker_migrated = [a for a in migrated_apps if a.get("site_class") == "migrated_docker" or "DOCKER" in str(a.get("status") or "")]
    if docker_migrated:
        for app in docker_migrated:
            lines.append(
                f"    MIGRATED TO DOCKER  {app.get('application_id')}  {', '.join(_hostnames(app))}  "
                f"replaced_by={app.get('replaced_by') or '—'}"
            )
            lines.append("    Old /var/www path is a legacy host install, not a deleted website.")
    else:
        lines.append("    (none)")
    lines.append("  3. old/legacy host installation")
    legacy = [a for a in migrated_apps if a not in docker_migrated]
    if legacy:
        for app in legacy:
            lines.append(f"    LEGACY HOST  {app.get('application_id')}  {', '.join(_hostnames(app))}")
    else:
        lines.append("    (none)")
    lines.append("  4. genuinely deleted website")
    if removed_apps:
        for app in removed_apps:
            lines.append(f"    DELETED  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('status')}")
    else:
        lines.append("    (none)")
    lines.extend(["", "NEW APPLICATIONS"])
    if new_apps:
        for app in new_apps:
            lines.append(
                f"  NEW SITE DETECTED — REQUIRES APPROVAL  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('type')}  {app.get('root') or ''}"
            )
            lines.append(f"    database: {_db_label(app)}")
            lines.append("    Requires explicit approval before the first backup of this application.")
    else:
        lines.append("  (none)")
    lines.extend(["", "REMOVED APPLICATIONS"])
    if removed_apps:
        for app in removed_apps:
            lines.append(f"  Previously discovered: {app.get('application_id')} ({', '.join(_hostnames(app))})")
            lines.append("  No longer detected in active Nginx configuration.")
            lines.append("  This is classified as a genuinely deleted website (no live hostname match).")
            lines.append("  Master data is NOT deleted. Review before removing from the backup set.")
    else:
        lines.append("  (none)")
    lines.extend(["", "MIGRATED APPLICATIONS"])
    if migrated_apps:
        for app in migrated_apps:
            lines.append(f"  {app.get('status')}  {app.get('application_id')} ({', '.join(_hostnames(app))})")
            lines.append(f"  replaced_by={app.get('replaced_by') or '—'}")
            for note in app.get("notes") or []:
                lines.append(f"    note: {note}")
    else:
        lines.append("  (none)")
    lines.extend(["", "REQUIRES REVIEW"])
    review_lines: list[str] = []
    if review:
        for app in review:
            review_lines.append(f"  {app.get('application_id')}  {', '.join(_hostnames(app))}  {app.get('status')}")
            for note in app.get("notes") or []:
                review_lines.append(f"    note: {note}")
    for row in unassociated_rows:
        review_lines.append(f"  database {row.get('name')}  {row.get('status')}")
        review_lines.append(f"    reason: {row.get('reason') or 'no application association discovered'}")
    if review_lines:
        lines.extend(review_lines)
    else:
        lines.append("  (none)")
    return lines


def format_discovery_report(result: dict[str, Any]) -> str:
    apps = list(result.get("applications") or [])
    lines = [
        "DISCOVERY REPORT",
        f"Host: {result.get('hostname') or 'unknown'}",
        f"Source: {result.get('discovery_source') or 'nginx -T + docker + on-disk configs'}",
        f"Nginx: {'OK' if result.get('nginx_ok') else 'FAILED'}",
        "",
        *format_server_wide_discovery_report(result),
        "",
        *format_application_sections(
            apps,
            databases=result.get("databases"),
            nginx_inventory=result.get("nginx_inventory") or result.get("servers"),
            parsed_hostnames=result.get("parsed_hostnames"),
            database_inventory=result.get("database_inventory"),
            inactive_hostnames=result.get("inactive_hostnames"),
            gate=result.get("backup_gate"),
            database_account=result.get("database_account"),
        ),
    ]
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
