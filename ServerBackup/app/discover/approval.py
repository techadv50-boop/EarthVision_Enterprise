"""Helpers for the Application Discovery/Approval view. No production changes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.discover.policy import is_auto_excluded, set_approval


def application_id(app: dict[str, Any]) -> str:
    return str(app.get("application_id") or app.get("hostname") or "").strip()


def hostnames(app: dict[str, Any]) -> list[str]:
    names = [str(n) for n in (app.get("hostnames") or []) if n]
    primary = str(app.get("hostname") or "")
    if primary and primary not in names:
        names.insert(0, primary)
    return names


def split_approval_applications(
    applications: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (pending, approved, excluded). Removed rows are omitted."""
    live = [row for row in (applications or []) if row.get("change") != "removed"]
    excluded = [row for row in live if is_auto_excluded(row)]
    excluded_ids = {id(row) for row in excluded}
    pending = [row for row in live if id(row) not in excluded_ids and not row.get("included")]
    approved = [row for row in live if id(row) not in excluded_ids and row.get("included")]
    return pending, approved, excluded


def format_application_approval_block(app: dict[str, Any]) -> str:
    ident = application_id(app) or "—"
    lines = [
        ident,
        f"    {', '.join(hostnames(app)) or '—'}",
        f"    {app.get('type') or '—'}",
        f"    {app.get('root') or '—'}",
    ]
    files_dir = str(app.get("ojs_files_dir") or "").strip()
    if files_dir:
        lines.append(f"    OJS files: {files_dir}")
    if app.get("database_type") or app.get("database_name"):
        lines.append(f"    {str(app.get('database_type') or '').strip()} {str(app.get('database_name') or '').strip()}".strip())
    status = str(app.get("status") or "")
    if app.get("unused_default_root") or "UNUSED DEFAULT ROOT" in status:
        lines.append("    UNUSED DEFAULT ROOT")
    elif status and status not in {"READY", "NEW SITE DETECTED — REQUIRES APPROVAL"}:
        lines.append(f"    {status}")
    return "\n".join(lines)


def mark_row_approved(app: dict[str, Any]) -> None:
    app["included"] = True
    app["excluded"] = False
    status = str(app.get("status") or "")
    if "NEW SITE DETECTED" in status or (
        "REQUIRES APPROVAL" in status and "HOSTNAME" not in status and "REVIEW" not in status
    ):
        app["status"] = "READY"
    app["change"] = "unchanged"


def approve_selected_applications(
    destination: str | Path,
    applications: list[dict[str, Any]],
    selected_ids: list[str],
    *,
    include_unused_default: bool = False,
) -> list[str]:
    """Approve checked application_ids. Unused default roots stay excluded unless overridden."""
    wanted = {str(item).strip() for item in selected_ids if str(item).strip()}
    approved_ids: list[str] = []
    for app in applications:
        if app.get("change") == "removed":
            continue
        ident = application_id(app)
        if not ident or ident not in wanted:
            continue
        if is_auto_excluded(app) and not include_unused_default:
            continue
        set_approval(destination, ident, approved=True, excluded=False)
        mark_row_approved(app)
        approved_ids.append(ident)
    return approved_ids
