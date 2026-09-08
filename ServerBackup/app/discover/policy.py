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


def apply_policy(applications: list[dict[str, Any]], destination: str | Path) -> list[dict[str, Any]]:
    policy = load_policy(destination)
    snapshot = load_snapshot(destination)
    previous = {
        str(item.get("application_id") or item.get("hostname"))
        for item in (snapshot.get("applications") or [])
        if isinstance(item, dict)
    }
    stored = policy.get("applications") or {}
    result = []
    current_ids = set()
    for app in applications:
        row = dict(app)
        ident = str(row.get("application_id") or row.get("hostname") or "")
        current_ids.add(ident)
        rec = stored.get(ident) or stored.get(str(row.get("hostname") or "")) or {}
        if rec.get("excluded"):
            row["status"] = "EXCLUDED"
            row["included"] = False
            row["excluded"] = True
            row["change"] = "excluded"
        elif rec.get("approved"):
            row["included"] = True
            row["excluded"] = False
            row["change"] = "unchanged" if ident in previous else "new"
        else:
            row["included"] = False
            row["excluded"] = False
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
