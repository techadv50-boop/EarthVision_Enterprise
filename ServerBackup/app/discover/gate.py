"""Backup completeness gate. Unresolved discovery blocks COMPLETE backup."""

from __future__ import annotations

from typing import Any


def assess_backup_gate(
    applications: list[dict[str, Any]] | None,
    databases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    apps = [row for row in (applications or []) if isinstance(row, dict)]
    live = [row for row in apps if row.get("change") != "removed"]
    excluded_apps = [
        row
        for row in live
        if row.get("excluded") or row.get("unused_default_root") or "EXCLUDED" in str(row.get("status") or "")
    ]
    pending_apps = [
        row
        for row in live
        if row not in excluded_apps and not row.get("included")
    ]
    approved_apps = [
        row
        for row in live
        if row.get("included") and row not in excluded_apps
    ]
    dbs = [row for row in (databases or []) if isinstance(row, dict) and not row.get("system")]
    associated = [row for row in dbs if str(row.get("status") or "").startswith("ASSOCIATED")]
    excluded_dbs = [row for row in dbs if "EXCLUDED" in str(row.get("status") or "")]
    unresolved_dbs = [row for row in dbs if row not in associated and row not in excluded_dbs]
    block = bool(pending_apps or unresolved_dbs)
    return {
        "applications_discovered": len(live),
        "applications_approved": len(approved_apps),
        "applications_excluded": len(excluded_apps),
        "applications_pending": len(pending_apps),
        "databases_discovered": len(dbs),
        "databases_associated": len(associated),
        "databases_unresolved": len(unresolved_dbs),
        "block_complete_backup": block,
        "pending_application_ids": [str(row.get("application_id") or "") for row in pending_apps],
        "unresolved_database_names": [str(row.get("name") or "") for row in unresolved_dbs],
    }


def format_backup_gate(gate: dict[str, Any]) -> list[str]:
    lines = [
        "BACKUP GATE",
        f"  Applications discovered: {gate.get('applications_discovered', 0)}",
        f"  Applications approved: {gate.get('applications_approved', 0)}",
        f"  Applications excluded: {gate.get('applications_excluded', 0)}",
        f"  Applications pending: {gate.get('applications_pending', 0)}",
        f"  Databases discovered: {gate.get('databases_discovered', 0)}",
        f"  Databases associated: {gate.get('databases_associated', 0)}",
        f"  Databases unresolved: {gate.get('databases_unresolved', 0)}",
    ]
    if gate.get("block_complete_backup"):
        lines.append("  Unresolved > 0:")
        lines.append("  BLOCK COMPLETE BACKUP")
        pending = gate.get("pending_application_ids") or []
        unresolved = gate.get("unresolved_database_names") or []
        if pending:
            lines.append("  pending applications: " + ", ".join(str(item) for item in pending))
        if unresolved:
            lines.append("  unresolved databases: " + ", ".join(str(item) for item in unresolved))
        lines.append("  DRY RUN and discovery remain allowed. BACKUP NOW cannot report COMPLETE.")
    else:
        lines.append("  Gate: CLEAR (approval still required before you choose to run BACKUP NOW)")
    return lines


def backup_gate_error(gate: dict[str, Any]) -> str:
    return "\n".join(
        [
            "BLOCK COMPLETE BACKUP",
            *format_backup_gate(gate)[1:],
            "Resolve pending applications and unassociated databases before BACKUP NOW.",
        ]
    )
