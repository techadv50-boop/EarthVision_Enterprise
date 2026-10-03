"""Services an admin can grant: citation, review, galley, and author database."""

from __future__ import annotations

from typing import Any

SERVICES = ("citation", "review", "authors", "galley")

SERVICE_LABELS = {
    "citation": "Citation project",
    "review": "Article review",
    "authors": "Author database",
    "galley": "Galley composition",
}

REVIEW_BRANCHES = ("references", "language")
REVIEW_BRANCH_LABELS = {
    "references": "Reference check",
    "language": "English checking",
}

AUTHOR_WINGS = ("in_process", "published")
AUTHOR_WING_LABELS = {
    "in_process": "Under process",
    "published": "Published",
}


def empty_privileges() -> dict[str, Any]:
    return {
        "services": [],
        "review_branches": [],
        "author_wings": [],
        "all_journals": False,
    }


def full_privileges() -> dict[str, Any]:
    return {
        "services": list(SERVICES),
        "review_branches": list(REVIEW_BRANCHES),
        "author_wings": list(AUTHOR_WINGS),
        "all_journals": True,
    }


def _uniq(values: list[str] | None, allowed: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        name = (raw or "").strip().lower()
        if name in allowed and name not in out:
            out.append(name)
    return out


def normalize_privileges(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    services = _uniq(data.get("services"), SERVICES)
    review_branches = _uniq(data.get("review_branches"), REVIEW_BRANCHES)
    author_wings = _uniq(data.get("author_wings"), AUTHOR_WINGS)
    if "review" not in services:
        review_branches = []
    if "authors" not in services:
        author_wings = []
    all_journals = bool(data.get("all_journals")) and "citation" in services
    return {
        "services": services,
        "review_branches": review_branches,
        "author_wings": author_wings,
        "all_journals": all_journals,
    }


def privileges_from_desks(desks: list[str] | None) -> dict[str, Any]:
    from app.core.desks import normalize_desks

    names = normalize_desks(desks)
    services = [desk for desk in names if desk in SERVICES]
    priv = empty_privileges()
    priv["services"] = services
    if "review" in services:
        priv["review_branches"] = list(REVIEW_BRANCHES)
    if "authors" in services:
        priv["author_wings"] = list(AUTHOR_WINGS)
    if "citation" in services:
        priv["all_journals"] = True
    return priv
