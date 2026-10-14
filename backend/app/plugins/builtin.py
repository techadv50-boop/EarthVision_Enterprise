"""Built-in tools. Each desk is a plugin so it can be upgraded or replaced alone."""

from __future__ import annotations

from typing import Any

BUILTIN_PLUGINS: list[dict[str, Any]] = [
    {
        "id": "citation-assistant",
        "name": "Citation Assistant",
        "description": (
            "Journals assigned to this account, archive search, and new-manuscript "
            "house citations from papers already stored on this shelf."
        ),
        "version": "1.0.0",
        "service": "citation",
        "route": "/journals",
        "icon": "book-open",
        "kind": "builtin",
        "package": "frontend/src/pages + backend/app/routers/citations.py",
    },
    {
        "id": "article-review",
        "name": "Article Review / Comparison",
        "description": (
            "Compare the References section of the file you sent to staff with the file they "
            "returned. Review English with in-depth AI tools before publish."
        ),
        "version": "1.0.0",
        "service": "review",
        "route": "/review",
        "icon": "git-compare",
        "kind": "builtin",
        "package": "frontend/src/pages/Review* + backend review routes",
    },
    {
        "id": "author-database",
        "name": "Author database",
        "description": (
            "Two wings: under process articles and published articles. Add OJS number, title, "
            "authors, emails, plagiarism, ORCID, review rounds, and galley dates."
        ),
        "version": "1.0.0",
        "service": "authors",
        "route": "/authors",
        "icon": "clipboard-list",
        "kind": "builtin",
        "package": "frontend/src/pages/Author* + backend/app/routers/author_db.py",
    },
    {
        "id": "galley-composition",
        "name": "Galley composition",
        "description": (
            "Choose a journal, fill the first page and body, and save a Word proof. The same "
            "account used for citations opens this desk — no second username or password."
        ),
        "version": "1.0.0",
        "service": "galley",
        "route": "/galley",
        "icon": "file-pen-line",
        "kind": "builtin",
        "package": "frontend/src/galley + backend/app/routers/galley.py",
    },
]

BUILTIN_BY_ID = {row["id"]: row for row in BUILTIN_PLUGINS}
PLUGIN_ID_RE = r"^[a-z0-9][a-z0-9-]{1,62}$"
MAX_PLUGIN_BYTES = 20 * 1024 * 1024
