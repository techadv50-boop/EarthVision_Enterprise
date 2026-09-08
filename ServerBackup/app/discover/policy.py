"""Local approval policy for discovered applications. No secrets."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

POLICY_NAME = "applications-policy.json"
SNAPSHOT_NAME = "last-discovery.json"


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
        if app.get("change") == "removed":
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
        "change": item.get("change") or "",
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
        removed = dict(prev)
        removed["status"] = "SITE REMOVED — REQUIRES REVIEW"
        removed["change"] = "removed"
        removed["included"] = False
        removed["notes"] = list(removed.get("notes") or []) + [
            "No longer detected in active Nginx configuration."
        ]
        result.append(removed)
    return result
