"""Local approval policy for discovered applications. No secrets."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

POLICY_NAME = "applications-policy.json"
SNAPSHOT_NAME = "last-discovery.json"
MIGRATION_LEFTOVER_PREFIXES = (
    "/opt/dokploy-migrations/",
    "/root/dokploy-migration/",
)
CATCHALL_HOSTS = {"", "*", "_", "localhost"}


def _policy_path(destination: str | Path) -> Path:
    return Path(destination) / POLICY_NAME


def _snapshot_path(destination: str | Path) -> Path:
    return Path(destination) / SNAPSHOT_NAME


def load_policy(destination: str | Path) -> dict[str, Any]:
    path = _policy_path(destination)
    if not path.is_file():
        return {"applications": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"applications": {}}
    if not isinstance(data, dict):
        return {"applications": {}}
    apps = data.get("applications")
    if not isinstance(apps, dict):
        data["applications"] = {}
    return data


def save_policy(destination: str | Path, policy: dict[str, Any]) -> Path:
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    path = _policy_path(dest)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_snapshot(destination: str | Path) -> dict[str, Any]:
    path = _snapshot_path(destination)
    if not path.is_file():
        return {"applications": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"applications": []}
    return data if isinstance(data, dict) else {"applications": []}


def save_snapshot(destination: str | Path, snapshot: dict[str, Any]) -> Path:
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(dest)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def set_approval(destination: str | Path, application_id: str, *, approved: bool, excluded: bool = False) -> dict[str, Any]:
    policy = load_policy(destination)
    apps = policy.setdefault("applications", {})
    row = dict(apps.get(application_id) or {})
    row["approved"] = bool(approved) and not excluded
    row["excluded"] = bool(excluded)
    row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if approved and not excluded:
        row["approved_at"] = row["updated_at"]
    apps[application_id] = row
    save_policy(destination, policy)
    return row


def set_database_decision(
    destination: str | Path,
    name: str,
    *,
    excluded: bool = False,
    include_unassigned: bool = False,
) -> dict[str, Any]:
    """Record a review decision for an unassociated database. No production changes."""
    ident = str(name or "").strip()
    if not ident:
        raise ValueError("database name required")
    policy = load_policy(destination)
    dbs = policy.setdefault("databases", {})
    row = dict(dbs.get(ident) or {})
    row["excluded"] = bool(excluded)
    row["include_unassigned"] = bool(include_unassigned) and not excluded
    row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dbs[ident] = row
    save_policy(destination, policy)
    return row


def _is_migration_leftover_path(path: str) -> bool:
    cleaned = str(path or "").replace("\\", "/")
    if not cleaned or cleaned.startswith("docker:"):
        return False
    return any(cleaned == prefix.rstrip("/") or cleaned.startswith(prefix) for prefix in MIGRATION_LEFTOVER_PREFIXES)


def is_migration_leftover_database(row: dict[str, Any]) -> bool:
    """True for host leftovers referenced only under Dokploy migration copies."""
    if row.get("system") or str(row.get("status") or "").startswith("ASSOCIATED"):
        return False
    if "MIGRATION LEFTOVER" in str(row.get("status") or ""):
        return True
    refs = [item for item in (row.get("references") or []) if isinstance(item, dict)]
    paths = [str(item.get("path") or "") for item in refs if item.get("path")]
    blob = " ".join(paths) + " " + str(row.get("reason") or "")
    if paths:
        return all(_is_migration_leftover_path(path) for path in paths)
    return "/opt/dokploy-migrations" in blob or "/root/dokploy-migration" in blob


def apply_database_policy(inventory: list[dict[str, Any]], destination: str | Path) -> list[dict[str, Any]]:
    policy = load_policy(destination)
    stored = policy.get("databases") if isinstance(policy.get("databases"), dict) else {}
    result: list[dict[str, Any]] = []
    for row in inventory:
        item = dict(row)
        name = str(item.get("name") or "")
        rec = dict(stored.get(name) or {}) if name else {}
        status = str(item.get("status") or "")
        if item.get("system") or status.startswith("ASSOCIATED"):
            result.append(item)
            continue
        if rec.get("excluded"):
            item["status"] = "EXCLUDED — USER REVIEW"
            item["reason"] = rec.get("reason") or (
                "excluded after review; leftover schema is not part of the live sites"
            )
            item["excluded"] = True
            item["include_unassigned"] = False
            item["recovery"] = False
        elif rec.get("include_unassigned"):
            item["status"] = "INCLUDED — UNASSIGNED"
            item["reason"] = rec.get("reason") or "reviewed: dump under BACKUPS/_unassigned-databases"
            item["include_unassigned"] = True
            item["excluded"] = False
            item["recovery"] = False
        elif is_migration_leftover_database(item):
            item["status"] = "RECOVERY — DOKPLOY MIGRATION LEFTOVER"
            item["reason"] = item.get("reason") or (
                "only referenced under Dokploy migration copies "
                "(/opt/dokploy-migrations or /root/dokploy-migration); "
                "not an active Nginx application. Kept under BACKUPS/_recovery/databases "
                "so it is never silently discarded. It is not placed in a website folder."
            )
            item["excluded"] = False
            item["include_unassigned"] = False
            item["recovery"] = True
        result.append(item)
    return result


def acknowledge_removed_applications(destination: str | Path, application_ids: list[str]) -> list[str]:
    policy = load_policy(destination)
    apps = policy.setdefault("applications", {})
    stamped = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    acknowledged: list[str] = []
    for ident in application_ids:
        key = str(ident or "").strip()
        if not key:
            continue
        row = dict(apps.get(key) or {})
        row["removed_acknowledged"] = True
        row["updated_at"] = stamped
        apps[key] = row
        acknowledged.append(key)
    if acknowledged:
        save_policy(destination, policy)
    return acknowledged


def _hostnames(app: dict[str, Any]) -> list[str]:
    names = [str(n) for n in (app.get("hostnames") or []) if n]
    primary = str(app.get("hostname") or "")
    if primary and primary not in names:
        names.insert(0, primary)
    return names


def _policy_record(stored: dict[str, Any], app: dict[str, Any]) -> dict[str, Any]:
    ident = str(app.get("application_id") or "")
    if ident and ident in stored:
        return dict(stored.get(ident) or {})
    for host in _hostnames(app):
        if host in stored:
            return dict(stored.get(host) or {})
        old = f"{host}:{str(app.get('root') or '').rstrip('/')}"
        if old in stored:
            return dict(stored.get(old) or {})
    return {}


def _normalized_hosts(app: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for raw in _hostnames(app):
        name = str(raw or "").strip().lower().rstrip(".")
        if not name or name in CATCHALL_HOSTS:
            continue
        hosts.add(name)
        if name.startswith("www."):
            hosts.add(name[4:])
        else:
            hosts.add("www." + name)
    return hosts


def _hosts_from_legacy_record(app: dict[str, Any]) -> set[str]:
    hosts = _normalized_hosts(app)
    ident = str(app.get("application_id") or "")
    root = str(app.get("root") or "")
    candidates = []
    if ":" in ident:
        candidates.append(ident.split(":", 1)[1])
    if root:
        candidates.append(root)
    for path in candidates:
        leaf = str(path).rstrip("/").rsplit("/", 1)[-1].lower()
        if leaf and "." in leaf and leaf not in CATCHALL_HOSTS:
            hosts.add(leaf)
            if leaf.startswith("www."):
                hosts.add(leaf[4:])
            else:
                hosts.add("www." + leaf)
    return hosts


def classify_vanished_site(previous: dict[str, Any], live_apps: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinguish deleted sites from Docker cutovers of the same hostname."""
    prev_hosts = _hosts_from_legacy_record(previous)
    for live in live_apps:
        live_hosts = _normalized_hosts(live)
        if not prev_hosts or not (prev_hosts & live_hosts):
            continue
        live_id = str(live.get("application_id") or live.get("hostname") or "")
        live_docker = live.get("docker") if isinstance(live.get("docker"), dict) else None
        prev_root = str(previous.get("root") or "")
        if live_docker:
            return {
                "change": "migrated",
                "status": "SITE MIGRATED — NOW RUNNING IN DOCKER",
                "site_class": "migrated_docker",
                "replaced_by": live_id,
                "notes": [
                    f"Legacy host installation {previous.get('application_id')} "
                    f"({prev_root or 'no root'}) is no longer in active Nginx.",
                    f"The same hostname now runs as Docker application {live_id}.",
                    "The current Docker application is the authoritative backup source.",
                    "This old path is not a deleted website.",
                ],
            }
        return {
            "change": "migrated",
            "status": "SITE MIGRATED — LEGACY HOST INSTALL",
            "site_class": "legacy_host",
            "replaced_by": live_id,
            "notes": [
                f"Previous application {previous.get('application_id')} was replaced by {live_id}.",
                "The currently active application is the authoritative backup source.",
            ],
        }
    return {
        "change": "removed",
        "status": "SITE REMOVED — REQUIRES REVIEW",
        "site_class": "deleted",
        "replaced_by": "",
        "notes": ["No longer detected in active Nginx configuration."],
    }


def is_auto_excluded(app: dict[str, Any]) -> bool:
    status = str(app.get("status") or "")
    return bool(
        app.get("excluded")
        or app.get("unused_default_root")
        or app.get("change") == "excluded"
        or "UNUSED DEFAULT ROOT" in status
        or (status.startswith("EXCLUDED") and "REQUIRES APPROVAL" not in status)
    )


def approve_all_applications(
    destination: str | Path,
    applications: list[dict[str, Any]],
    *,
    include_unused_default: bool = False,
) -> list[str]:
    """Approve discovered applications. Skips unused default roots unless explicitly overridden."""
    approved_ids: list[str] = []
    for app in applications:
        if app.get("change") in {"removed", "migrated"}:
            continue
        auto_excluded = is_auto_excluded(app)
        if auto_excluded and not include_unused_default:
            continue
        ident = str(app.get("application_id") or app.get("hostname") or "")
        if not ident:
            continue
        set_approval(destination, ident, approved=True, excluded=False)
        approved_ids.append(ident)
    return approved_ids


def snapshot_application_row(item: dict[str, Any]) -> dict[str, Any]:
    """Persist enough discovery fields for the approval UI without a live SSH round-trip."""
    return {
        "application_id": item.get("application_id"),
        "hostname": item.get("hostname"),
        "hostnames": list(item.get("hostnames") or [item.get("hostname")]),
        "hostname_details": item.get("hostname_details") or {},
        "type": item.get("type"),
        "root": item.get("root"),
        "status": item.get("status"),
        "database_type": item.get("database_type"),
        "database_name": item.get("database_name"),
        "source_file": item.get("source_file"),
        "alias": list(item.get("alias") or []),
        "proxy_pass": list(item.get("proxy_pass") or []),
        "redirect_to": item.get("redirect_to") or "",
        "ojs_files_dir": item.get("ojs_files_dir") or "",
        "unused_default_root": bool(item.get("unused_default_root")),
        "excluded": bool(item.get("excluded")),
        "included": bool(item.get("included")),
        "notes": list(item.get("notes") or []),
        "estimated_bytes": int(item.get("estimated_bytes") or 0),
        "source_paths": list(item.get("source_paths") or []),
        "persistent_data_paths": list(item.get("persistent_data_paths") or []),
        "docker": item.get("docker"),
        "configuration_paths": list(item.get("configuration_paths") or []),
        "source_files": list(item.get("source_files") or []),
        "change": item.get("change") or "",
        "site_class": item.get("site_class") or "",
        "replaced_by": item.get("replaced_by") or "",
    }


def apply_policy(applications: list[dict[str, Any]], destination: str | Path) -> list[dict[str, Any]]:
    policy = load_policy(destination)
    snapshot = load_snapshot(destination)
    previous_apps = [item for item in (snapshot.get("applications") or []) if isinstance(item, dict)]
    previous = {
        str(item.get("application_id") or item.get("hostname"))
        for item in previous_apps
        if item.get("application_id") or item.get("hostname")
    }
    previous_hosts = {
        str(item.get("application_id") or ""): set(_hostnames(item))
        for item in previous_apps
    }
    stored = policy.get("applications") or {}
    result = []
    current_ids = set()
    for app in applications:
        row = dict(app)
        ident = str(row.get("application_id") or row.get("hostname") or "")
        current_ids.add(ident)
        rec = _policy_record(stored, row)
        auto_excluded = bool(row.get("excluded") or row.get("unused_default_root") or "UNUSED DEFAULT ROOT" in str(row.get("status") or ""))
        prev_hosts = previous_hosts.get(ident) or set()
        current_hosts = set(_hostnames(row))
        new_hosts = sorted(current_hosts - prev_hosts) if ident in previous else []
        if rec.get("excluded") or auto_excluded:
            if "UNUSED DEFAULT ROOT" not in str(row.get("status") or ""):
                row["status"] = "EXCLUDED — UNUSED DEFAULT ROOT" if row.get("unused_default_root") else "EXCLUDED"
            row["included"] = False
            row["excluded"] = True
            row["change"] = "excluded"
            row["site_class"] = "excluded"
        elif rec.get("approved"):
            if new_hosts:
                row["included"] = False
                row["excluded"] = False
                row["change"] = "new_hostname"
                row["status"] = "NEW HOSTNAME DETECTED — REQUIRES APPROVAL"
                row["notes"] = list(row.get("notes") or []) + [
                    "New hostname alias(es): " + ", ".join(new_hosts)
                ]
            else:
                row["included"] = True
                row["excluded"] = False
                row["change"] = "unchanged" if ident in previous else "new"
                status = str(row.get("status") or "")
                if "NEW SITE DETECTED" in status or (
                    "REQUIRES APPROVAL" in status and "HOSTNAME" not in status and "REVIEW" not in status
                ):
                    row["status"] = "READY"
                    row["site_class"] = "active"
        else:
            row["included"] = False
            row["excluded"] = False
            if ident in previous and new_hosts:
                row["change"] = "new_hostname"
                if row.get("status") == "READY":
                    row["status"] = "NEW HOSTNAME DETECTED — REQUIRES APPROVAL"
                row["notes"] = list(row.get("notes") or []) + [
                    "New hostname alias(es): " + ", ".join(new_hosts)
                ]
            else:
                row["change"] = "unchanged" if ident in previous else "new"
                if row.get("status") == "READY":
                    row["status"] = "NEW SITE DETECTED — REQUIRES APPROVAL"
        if not row.get("site_class"):
            row["site_class"] = "active" if row.get("included") else str(row.get("change") or "active")
        result.append(row)
    previous_map: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("applications") or []:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("application_id") or item.get("hostname") or "")
        if ident:
            previous_map[ident] = item
    for ident, rec in stored.items():
        previous_map.setdefault(ident, {"application_id": ident, "hostname": ident, **rec})
    for ident, prev in previous_map.items():
        if ident in current_ids:
            continue
        vanished = dict(prev)
        classification = classify_vanished_site(vanished, result)
        rec = stored.get(ident) or {}
        vanished["included"] = False
        vanished["excluded"] = classification["change"] == "migrated"
        vanished["change"] = classification["change"]
        vanished["site_class"] = classification["site_class"]
        vanished["replaced_by"] = classification.get("replaced_by") or ""
        vanished["notes"] = list(vanished.get("notes") or []) + list(classification.get("notes") or [])
        if classification["change"] == "migrated":
            vanished["status"] = classification["status"]
        else:
            vanished["status"] = "SITE REMOVED — REQUIRES REVIEW"
            if rec.get("removed_acknowledged"):
                vanished["status"] = "SITE REMOVED — ACKNOWLEDGED"
        result.append(vanished)
    return result
