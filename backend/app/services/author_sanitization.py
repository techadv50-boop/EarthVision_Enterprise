"""Cross-match authors so the same person is not listed twice in one issue."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TITLE = re.compile(r"\b(dr|prof|professor|mr|ms|mrs|miss|eng|engineer)\b\.?", re.I)
_SPLIT_PEOPLE = re.compile(r"[\n;|]+|(?:\s+and\s+)|(?:\s*&\s*)", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def split_author_names(raw: str | None) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if re.search(r"[\n;|]|(\s+and\s+)|&", text, re.I):
        parts = _SPLIT_PEOPLE.split(text)
    else:
        bits = [item.strip() for item in text.split(",") if item.strip()]
        if len(bits) == 2 and len(bits[0].split()) == 1 and len(bits[1].split()) <= 3:
            parts = [text]
        else:
            parts = bits if len(bits) > 1 else [text]
    return [item.strip(" ,") for item in parts if item and item.strip(" ,")]


def split_emails(raw: str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[\s,;|]+", raw or ""):
        email = item.strip().lower().strip("<>")
        if "@" in email and email not in seen:
            seen.add(email)
            out.append(email)
    return out


def name_key(name: str) -> str:
    text = _TITLE.sub(" ", name or "")
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def last_and_given(name: str) -> tuple[str, str]:
    raw = (name or "").strip()
    if "," in raw:
        last, given = raw.split(",", 1)
        return name_key(last), name_key(given)
    tokens = name_key(raw).split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[-1], " ".join(tokens[:-1])


def authors_match(left: str, right: str) -> bool:
    a = name_key(left)
    b = name_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    last_a, given_a = last_and_given(left)
    last_b, given_b = last_and_given(right)
    if not last_a or last_a != last_b:
        return False
    if given_a == given_b:
        return True
    if not given_a or not given_b:
        return False
    compact_a = given_a.replace(" ", "")
    compact_b = given_b.replace(" ", "")
    if compact_a == compact_b:
        return True
    if compact_a.startswith(compact_b) or compact_b.startswith(compact_a):
        return True
    initial_a = compact_a[0]
    initial_b = compact_b[0]
    if initial_a != initial_b:
        return False
    return len(compact_a) == 1 or len(compact_b) == 1


@dataclass
class AuthorOverlap:
    author: str
    matched_as: str
    issue_article_id: int
    issue_ojs: str
    issue_title: str
    reason: str


def find_author_overlaps(
    scheduled_authors: str | None,
    scheduled_emails: str | None,
    issue_rows: list[dict],
    *,
    skip_id: int | None = None,
) -> list[AuthorOverlap]:
    names = split_author_names(scheduled_authors)
    emails = set(split_emails(scheduled_emails))
    hits: list[AuthorOverlap] = []
    seen: set[tuple[int, str]] = set()
    for row in issue_rows:
        article_id = int(row.get("id") or 0)
        if skip_id and article_id == skip_id:
            continue
        ojs = str(row.get("ojs_number") or "")
        title = str(row.get("title") or "")
        other_names = split_author_names(str(row.get("author_names") or ""))
        other_emails = set(split_emails(str(row.get("author_emails") or "")))
        for email in emails & other_emails:
            key = (article_id, f"email:{email}")
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                AuthorOverlap(
                    author=email,
                    matched_as=email,
                    issue_article_id=article_id,
                    issue_ojs=ojs,
                    issue_title=title,
                    reason="email",
                )
            )
        for name in names:
            for other in other_names:
                if not authors_match(name, other):
                    continue
                key = (article_id, name_key(name) or name.lower())
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    AuthorOverlap(
                        author=name,
                        matched_as=other,
                        issue_article_id=article_id,
                        issue_ojs=ojs,
                        issue_title=title,
                        reason="author",
                    )
                )
    return hits


def overlap_message(hits: list[AuthorOverlap]) -> str:
    if not hits:
        return "No overlapping authors with the current issue."
    parts = []
    for hit in hits:
        where = hit.issue_ojs or f"article #{hit.issue_article_id}"
        if hit.reason == "email":
            parts.append(f"{hit.author} already appears on {where}")
        elif hit.author.lower() == hit.matched_as.lower():
            parts.append(f"{hit.author} already appears on {where}")
        else:
            parts.append(f"{hit.author} matches {hit.matched_as} on {where}")
    return (
        "This article cannot be published in the current issue because the same "
        "authors may not be part of the same issue. " + "; ".join(parts) + "."
    )
