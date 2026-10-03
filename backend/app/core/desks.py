"""Workspace desks that can have their own admin account."""

from __future__ import annotations

DESKS = ("citation", "authors", "review", "users", "galley")

DESK_LABELS = {
    "citation": "Citation project",
    "authors": "Author database",
    "review": "Article review",
    "users": "Adding users",
    "galley": "Galley composition",
}


def desk_role(desk: str) -> str:
    return f"admin_{desk}"


def normalize_desks(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        name = (raw or "").strip().lower()
        if name in DESKS and name not in out:
            out.append(name)
    return out
