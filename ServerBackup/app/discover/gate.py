"""Backup completeness gate. Unresolved discovery blocks COMPLETE backup."""

from __future__ import annotations

from typing import Any


def assess_backup_gate(
    applications: list[dict[str, Any]] | None,
    databases: list[dict[str, Any]] | None = None,
    *,
    volumes: list[dict[str, Any]] | None = None,
    classified: list[dict[str, Any]] | None = None,
    scan_coverage: dict[str, Any] | None = None,
    hostname_records: list[dict[str, Any]] | None = None,
    file_reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    apps = [row for row in (applications or []) if isinstance(row, dict)]
    live = [row for row in apps if row.get("change") not in {"removed", "migrated"}]
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
    included_unassigned = [
        row
        for row in dbs
        if row not in associated
        and row not in excluded_dbs
        and (row.get("include_unassigned") or "INCLUDED — UNASSIGNED" in str(row.get("status") or ""))
    ]
    recovery_dbs = [
        row
        for row in dbs
        if row not in associated
        and row not in excluded_dbs
        and row not in included_unassigned
        and (row.get("recovery") or str(row.get("status") or "").startswith("RECOVERY"))
    ]
    unresolved_dbs = [
        row
        for row in dbs
        if row not in associated
        and row not in excluded_dbs
        and row not in included_unassigned
        and row not in recovery_dbs
    ]
    volume_rows = [row for row in (volumes or []) if isinstance(row, dict)]
    unresolved_volumes = [
        row
        for row in volume_rows
        if str(row.get("backup_status") or "")
        in {"UNRESOLVED", "BLOCKING", "UNRESOLVED_REQUIRES_REVIEW"}
        or str(row.get("classification") or "").startswith("UNRESOLVED")
    ]
    unexplained = [
        row
        for row in (classified or [])
        if isinstance(row, dict)
        and str(row.get("classification") or "").startswith("UNRESOLVED")
        and row.get("kind") in {"nginx", "volume", "hostname", "hostname-investigation"}
    ]
    unresolved_hostnames = [
        row
        for row in (hostname_records or classified or [])
        if isinstance(row, dict)
        and (
            str(row.get("classification") or "").startswith("UNRESOLVED")
            or (
                row.get("kind") == "hostname-investigation"
                and str(row.get("role") or row.get("type") or "") in {"application-hostname"}
                and not row.get("assigned_website")
            )
        )
        and str(row.get("hostname") or "")
    ]
    unresolved_app_dbs = [
        row
        for row in live
        if row not in excluded_apps
        and str(row.get("database_status") or "") == "UNRESOLVED"
    ]
    coverage = scan_coverage if isinstance(scan_coverage, dict) else {}
    incomplete_reasons = [str(item) for item in (coverage.get("incomplete_reasons") or []) if item]
    docker_unprobed = [
        row
        for row in dbs
        if row.get("docker_container")
        and row.get("size_bytes") is None
        and row.get("size_probe")
        and "EXCLUDED" not in str(row.get("status") or "")
        and not str(row.get("status") or "").startswith("RECOVERY")
    ]
    postgres_unvalidated = [
        row
        for row in dbs
        if "postgres" in str(row.get("type") or "").lower()
        and not row.get("dump_capable")
        and "EXCLUDED" not in str(row.get("status") or "")
        and not row.get("system")
    ]
    recon = file_reconciliation if isinstance(file_reconciliation, dict) else {}
    file_mismatch = bool(recon) and not recon.get("ok", True)
    # Documented, non-blocking observations. Unexplained Nginx/hostname leftovers
    # and inactive/legacy hostnames are recorded (kept under _server or noted as
    # NOT ACTIVE) but must not stop an otherwise-complete backup. Genuinely
    # unresolved persistent volumes and active-website database problems still
    # block, so no live application data is silently lost.
    unexplained_descriptions = [
        f"{row.get('kind') or 'item'}: {row.get('hostname') or row.get('application') or row.get('source_path') or row.get('nginx') or 'unnamed'}"
        for row in unexplained
    ]
    warnings = list(unexplained_descriptions)
    warnings.extend(
        f"inactive/legacy hostname: {row.get('hostname')}"
        for row in unresolved_hostnames
        if row.get("hostname")
    )
    block = bool(
        pending_apps
        or unresolved_dbs
        or unresolved_volumes
        or unresolved_app_dbs
        or incomplete_reasons
        or docker_unprobed
        or postgres_unvalidated
        or file_mismatch
    )
    return {
        "warnings": warnings,
        "unexplained_descriptions": unexplained_descriptions,
        "applications_discovered": len(live),
        "applications_approved": len(approved_apps),
        "applications_excluded": len(excluded_apps),
        "applications_pending": len(pending_apps),
        "databases_discovered": len(dbs),
        "databases_associated": len(associated),
        "databases_unresolved": len(unresolved_dbs) + len(unresolved_app_dbs),
        "volumes_discovered": len(volume_rows),
        "volumes_unresolved": len(unresolved_volumes),
        "unexplained_items": len(unexplained),
        "unresolved_website_databases": [str(row.get("hostname") or row.get("application_id") or "") for row in unresolved_app_dbs],
        "incomplete_reasons": incomplete_reasons,
        "unprobed_docker_databases": [str(row.get("name") or "") for row in docker_unprobed],
        "unvalidated_postgres_databases": [str(row.get("name") or "") for row in postgres_unvalidated],
        "unresolved_hostnames": [str(row.get("hostname") or "") for row in unresolved_hostnames],
        "file_reconciliation_ok": recon.get("ok") if recon else True,
        "file_reconciliation": recon,
        "block_complete_backup": block,
        "pending_application_ids": [str(row.get("application_id") or "") for row in pending_apps],
        "unresolved_database_names": [str(row.get("name") or "") for row in unresolved_dbs],
        "unresolved_volume_names": [str(row.get("name") or "") for row in unresolved_volumes],
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
        f"  Docker volumes discovered: {gate.get('volumes_discovered', 0)}",
        f"  Docker volumes unresolved: {gate.get('volumes_unresolved', 0)}",
    ]
    if gate.get("block_complete_backup"):
        lines.append("  Unresolved > 0:")
        lines.append("  BLOCK COMPLETE BACKUP")
        pending = gate.get("pending_application_ids") or []
        unresolved = gate.get("unresolved_database_names") or []
        volumes = gate.get("unresolved_volume_names") or []
        if pending:
            lines.append("  pending applications: " + ", ".join(str(item) for item in pending))
        if unresolved:
            lines.append("  unresolved databases: " + ", ".join(str(item) for item in unresolved))
        if volumes:
            lines.append("  unresolved volumes: " + ", ".join(str(item) for item in volumes))
        website_dbs = gate.get("unresolved_website_databases") or []
        if website_dbs:
            lines.append("  unresolved website databases: " + ", ".join(str(item) for item in website_dbs))
        unprobed = gate.get("unprobed_docker_databases") or []
        if unprobed:
            lines.append("  unprobed docker database sizes: " + ", ".join(str(item) for item in unprobed))
        postgres = gate.get("unvalidated_postgres_databases") or []
        if postgres:
            lines.append("  PostgreSQL without validated pg_dump: " + ", ".join(str(item) for item in postgres))
        hosts = gate.get("unresolved_hostnames") or []
        if hosts:
            lines.append("  unresolved/suspicious hostnames: " + ", ".join(str(item) for item in hosts))
        if gate.get("file_reconciliation_ok") is False:
            recon = gate.get("file_reconciliation") or {}
            lines.append(
                "  file-count discrepancy: inventoried="
                f"{recon.get('inventoried')} website={recon.get('website')} "
                f"infrastructure={recon.get('infrastructure')} recovery={recon.get('recovery')} "
                f"excluded={recon.get('excluded')}"
                + (f" other={recon.get('other')}" if recon.get("other") else "")
                + f" attributed={recon.get('attributed')}"
            )
        incomplete = gate.get("incomplete_reasons") or []
        if incomplete:
            lines.append("  incomplete discovery:")
            for item in incomplete:
                lines.append(f"    {item}")
        # Guarantee the block is never silent: if none of the itemized reasons
        # above were printed, spell out the remaining blocking counters.
        printed_any = any(
            gate.get(key)
            for key in (
                "pending_application_ids",
                "unresolved_database_names",
                "unresolved_volume_names",
                "unresolved_website_databases",
                "unprobed_docker_databases",
                "unvalidated_postgres_databases",
                "incomplete_reasons",
            )
        ) or gate.get("file_reconciliation_ok") is False
        if not printed_any:
            lines.append(
                "  reason: "
                + ", ".join(
                    f"{label}={gate.get(key)}"
                    for label, key in (
                        ("pending_apps", "applications_pending"),
                        ("unresolved_dbs", "databases_unresolved"),
                        ("unresolved_volumes", "volumes_unresolved"),
                    )
                    if gate.get(key)
                )
                or "  a completeness check failed; see the warnings below and the full discovery report."
            )
        lines.append("  DRY RUN and discovery remain allowed. BACKUP NOW cannot report COMPLETE.")
    else:
        lines.append("  Gate: CLEAR (approval still required before you choose to run BACKUP NOW)")
    warnings = gate.get("warnings") or []
    if warnings:
        lines.append("  WARNINGS (documented, non-blocking — kept under _server/_recovery, not lost):")
        for item in warnings:
            lines.append(f"    {item}")
    return lines


def backup_gate_error(gate: dict[str, Any]) -> str:
    return "\n".join(
        [
            "BLOCK COMPLETE BACKUP",
            *format_backup_gate(gate)[1:],
            "Resolve pending applications, unassociated databases, and unexplained persistent Docker volumes before BACKUP NOW.",
        ]
    )
