"""Author database management: under-process and published articles."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.dependencies import require_service
from app.core.security import verify_password
from app.database.session import get_db
from app.models.citation import AuthorArticle, AuthorArticleChange, AuthorDbJournal, AuthorIssueSet, Journal
from app.models.user import User
from app.schemas.author_db import (
    AUTHOR_DB_JOURNALS,
    COMMENT_MAX,
    DEFAULT_STAGE_DAYS,
    EDITORIAL_STATUSES,
    FIELD_LABELS,
    FIXED_STAGE_LABELS,
    STAGE_KEY_PATTERN,
    AuthorArticleDeleteIn,
    AuthorArticleIn,
    AuthorArticleOut,
    AuthorArticlePatch,
    AuthorFieldChangeOut,
    AuthorImportResult,
    AuthorIssueSetIn,
    AuthorIssueSetOut,
    AuthorIssueArticleOut,
    AuthorJournalIn,
    AuthorJournalOut,
    AuthorModificationOut,
    AuthorOverlapOut,
    AuthorSanitizeCheckIn,
    AuthorSanitizeCheckOut,
    ReviewRound,
    WINGS,
)
from app.services.journal_access import allowed_journal_ids, require_journal_access, is_removed_journal, purge_removed_journals
from app.services.author_sanitization import find_author_overlaps, overlap_message

router = APIRouter(prefix="/author-articles", tags=["Author database"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(require_service("authors"))]

EXCEL_HEADERS = [
    "OJS number",
    "Title",
    "Author names",
    "Email addresses of authors",
    "Email sent date",
    "Plagiarism",
    "ORCID ID",
    "Receive date",
    "Round 1 review sent date",
    "Round 1 review receive date",
    "Round 2 review sent date",
    "Round 2 review receive date",
    "Round 3 review sent date",
    "Round 3 review receive date",
    "Acceptance date",
    "Galley sent date",
    "Galley received date",
    "Publish date",
    "Status",
    "Soft reminder sent",
    "Second reminder sent",
    "Last reminder sent",
    "Comments",
    "Current state",
    "Current-state date",
    "Days allowed",
    "Current state passed",
    "Journal",
    "Wing",
]


def _blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _editorial_status(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not text:
        return "Submission"
    for label in EDITORIAL_STATUSES:
        if text.lower() == label.lower():
            return label
    lowered = text.lower()
    aliases = {
        "submission": "Submission",
        "waiting for reviewer to be assigned": "Waiting for reviewer to be assigned",
        "waiting for reviewer": "Waiting for reviewer to be assigned",
        "request for revisions": "Request for revisions",
        "revisions have been submitted": "Revisions have been submitted",
        "sent for copy editing": "Sent for copy editing",
        "copy editing": "Sent for copy editing",
    }
    return aliases.get(lowered, "Submission")


def _stage_label(key: Optional[str]) -> str:
    text = (key or "").strip()
    if not text:
        return "(none)"
    match = re.fullmatch(r"round_(\d+)_(sent|received)", text)
    if match:
        kind = "review sent date" if match.group(2) == "sent" else "review receive date"
        return f"Round {match.group(1)} {kind}"
    return FIXED_STAGE_LABELS.get(text, text)


def _current_stage(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if re.fullmatch(STAGE_KEY_PATTERN, text):
        return text
    lowered = text.lower().strip()
    aliases = {
        "none": "",
        "(none)": "",
        "acceptance date": "accepted_date",
        "accepted date": "accepted_date",
        "galley sent date": "galley_sent_date",
        "galley received date": "galley_received_date",
        "publish date": "publish_date",
    }
    if lowered in aliases:
        return aliases[lowered]
    round_match = re.fullmatch(r"round (\d+) review (sent|receive(?:d)?) date", lowered)
    if round_match:
        kind = "sent" if round_match.group(2).startswith("sent") else "received"
        return f"round_{int(round_match.group(1))}_{kind}"
    return ""


def _stage_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_DAYS
    return max(1, min(days, 365))


def _comments(value: Optional[str]) -> str:
    text = str(value or "")
    if len(text) > COMMENT_MAX:
        return text[:COMMENT_MAX]
    return text


def _normalize_rounds(raw: Any, *, fallback_received: Optional[str] = None) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        if isinstance(item, ReviewRound):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        sent = _blank(item.get("sent_date") or item.get("review_sent_date"))
        received = _blank(item.get("received_date") or item.get("review_received_date"))
        if not sent and not received and rounds:
            continue
        rounds.append({"round": len(rounds) + 1, "sent_date": sent, "received_date": received})
    if not rounds:
        rounds = [
            {
                "round": 1,
                "sent_date": None,
                "received_date": _blank(fallback_received),
            }
        ]
    return rounds


def _format_rounds(rounds: list[dict[str, Any]]) -> str:
    parts = []
    for item in rounds:
        number = item.get("round") or len(parts) + 1
        sent = item.get("sent_date") or "(empty)"
        received = item.get("received_date") or "(empty)"
        parts.append(f"Round {number}: sent {sent}, received {received}")
    return "; ".join(parts) if parts else "(empty)"


def _match_catalog_name(needle: str, catalog: list[AuthorDbJournal]) -> Optional[str]:
    text = (needle or "").strip().lower()
    if not text:
        return None
    for row in catalog:
        abbr = (row.abbreviation or "").strip().lower()
        name = (row.name or "").strip().lower()
        if text in {abbr, name}:
            return row.name
    for abbr, name in AUTHOR_DB_JOURNALS:
        if text in {abbr.lower(), name.lower()}:
            return name
    return None


def _row_snapshot(row: AuthorArticle) -> dict[str, Any]:
    return {
        "journal_id": row.journal_id,
        "journal_title": row.journal_title or "",
        "journal_name": row.journal_title or None,
        "ojs_number": row.ojs_number or "",
        "title": row.title or "",
        "author_names": row.author_names or "",
        "author_emails": row.author_emails or "",
        "email_sent_date": row.email_sent_date,
        "plagiarism": row.plagiarism or "",
        "orcid_id": row.orcid_id or "",
        "received_date": row.received_date,
        "review_rounds": _normalize_rounds(row.review_rounds, fallback_received=row.review_date),
        "accepted_date": row.accepted_date,
        "galley_sent_date": row.galley_sent_date,
        "galley_received_date": row.galley_received_date,
        "publish_date": row.publish_date,
        "editorial_status": row.editorial_status or "Submission",
        "soft_reminder_sent": row.soft_reminder_sent,
        "second_reminder_sent": row.second_reminder_sent,
        "last_reminder_sent": row.last_reminder_sent,
        "comments": row.comments or "",
        "current_stage": row.current_stage or "",
        "current_stage_started": row.current_stage_started,
        "current_stage_days": int(row.current_stage_days or DEFAULT_STAGE_DAYS),
        "current_stage_passed": bool(row.current_stage_passed),
    }


async def _ensure_author_catalog(db: AsyncSession) -> list[AuthorDbJournal]:
    rows = list((await db.execute(select(AuthorDbJournal).order_by(AuthorDbJournal.id))).scalars().all())
    removed = False
    for row in rows:
        if (row.name or "").strip().lower() == "demo extra journal" or is_removed_journal(
            row.name, row.abbreviation
        ):
            await db.delete(row)
            removed = True
    if removed:
        await db.flush()
        rows = list((await db.execute(select(AuthorDbJournal).order_by(AuthorDbJournal.id))).scalars().all())
    have = {(row.name or "").strip().lower() for row in rows}
    added = False
    for abbr, name in AUTHOR_DB_JOURNALS:
        if name.strip().lower() not in have:
            db.add(AuthorDbJournal(name=name, abbreviation=abbr))
            have.add(name.strip().lower())
            added = True
    if added:
        await db.flush()
        rows = list((await db.execute(select(AuthorDbJournal).order_by(AuthorDbJournal.id))).scalars().all())
    return rows


def _display(value: Any) -> str:
    if value is None:
        return "(empty)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    return text or "(empty)"


def _account_label(user: User) -> str:
    name = (user.full_name or "").strip()
    email = (user.email or "").strip()
    username = (user.username or "").strip()
    if name and email:
        return f"{name} ({email})"
    if email:
        return email
    return username or f"user #{user.id}"


def _modification_out(change: AuthorArticleChange) -> AuthorModificationOut:
    raw = change.changes or []
    fields = [
        AuthorFieldChangeOut(
            field=str(item.get("field") or ""),
            label=str(item.get("label") or item.get("field") or ""),
            previous=str(item.get("previous") if item.get("previous") is not None else "(empty)"),
            new=str(item.get("new") if item.get("new") is not None else "(empty)"),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    return AuthorModificationOut(
        mod_number=change.mod_number,
        changed_at=change.changed_at,
        account=change.account_name or change.account_email or change.account_username or "Unknown account",
        account_username=change.account_username or "",
        account_email=change.account_email or "",
        account_name=change.account_name or "",
        changes=fields,
        snapshot=change.snapshot if isinstance(change.snapshot, dict) else {},
    )


def _payload(row: AuthorArticle) -> AuthorArticleOut:
    journal = row.journal
    mods = [_modification_out(item) for item in sorted(row.changes or [], key=lambda item: item.mod_number)]
    return AuthorArticleOut(
        id=row.id,
        wing=row.wing,
        journal_id=row.journal_id,
        journal_name=(
            row.journal_title
            or ((journal.name or journal.abbreviation) if journal else None)
            or None
        ),
        journal_title=row.journal_title or "",
        owner_id=row.owner_id,
        ojs_number=row.ojs_number or "",
        title=row.title or "",
        author_names=row.author_names or "",
        author_emails=row.author_emails or "",
        email_sent=bool(row.email_sent),
        email_sent_date=row.email_sent_date,
        plagiarism=row.plagiarism or "",
        orcid_id=row.orcid_id or "",
        received_date=row.received_date,
        review_date=row.review_date,
        review_rounds=[ReviewRound.model_validate(item) for item in _normalize_rounds(row.review_rounds, fallback_received=row.review_date)],
        accepted_date=row.accepted_date,
        galley_sent_date=row.galley_sent_date,
        galley_received_date=row.galley_received_date,
        publish_date=row.publish_date,
        editorial_status=row.editorial_status or "Submission",
        soft_reminder_sent=row.soft_reminder_sent,
        second_reminder_sent=row.second_reminder_sent,
        last_reminder_sent=row.last_reminder_sent,
        comments=row.comments or "",
        current_stage=row.current_stage or "",
        current_stage_started=row.current_stage_started,
        current_stage_days=int(row.current_stage_days or DEFAULT_STAGE_DAYS),
        current_stage_passed=bool(row.current_stage_passed),
        repeat_done=bool(row.repeat_done),
        doi_in_pdf=row.doi_in_pdf or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
        original_snapshot=row.original_snapshot if isinstance(row.original_snapshot, dict) else {},
        modifications=mods,
    )


def _load_options():
    return (selectinload(AuthorArticle.journal), selectinload(AuthorArticle.changes))


async def _require_author_journal(db: AsyncSession, user: User, journal_id: int) -> Journal:
    journal = await db.get(Journal, journal_id)
    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found")
    abbr = (journal.abbreviation or "").strip().lower()
    name = (journal.name or "").strip().lower()
    catalog_keys = {item[0].lower() for item in AUTHOR_DB_JOURNALS} | {
        item[1].lower() for item in AUTHOR_DB_JOURNALS
    }
    if abbr in catalog_keys or name in catalog_keys:
        return journal
    return await require_journal_access(db, user, journal_id, desk="authors")


def _require_wing(user: User, wing: str) -> None:
    if not user.has_author_wing(wing):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not granted that author-database wing",
        )


async def _canon_journal(db: AsyncSession, title: Optional[str]) -> str:
    text = (title or "").strip()
    if not text:
        return ""
    catalog = await _ensure_author_catalog(db)
    return _match_catalog_name(text, catalog) or text


def _issue_brief(row: AuthorArticle) -> AuthorIssueArticleOut:
    journal = row.journal_title or (
        ((row.journal.name or row.journal.abbreviation) if row.journal else "") or ""
    )
    return AuthorIssueArticleOut(
        id=row.id,
        wing=row.wing or "",
        journal_title=row.journal_title or "",
        journal_name=journal or None,
        ojs_number=row.ojs_number or "",
        title=row.title or "",
        author_names=row.author_names or "",
        author_emails=row.author_emails or "",
    )


def _journal_aliases(text: Optional[str]) -> set[str]:
    needle = (text or "").strip().lower()
    if not needle:
        return set()
    out = {needle}
    for abbr, name in AUTHOR_DB_JOURNALS:
        if needle in {abbr.lower(), name.lower()}:
            out.add(abbr.lower())
            out.add(name.lower())
    return out


def _same_journal(row: AuthorArticle, canon: str) -> bool:
    if not canon:
        return True
    wanted = _journal_aliases(canon)
    have = _journal_aliases(row.journal_title)
    if row.journal is not None:
        have |= _journal_aliases(row.journal.name)
        have |= _journal_aliases(row.journal.abbreviation)
    return bool(wanted & have)


async def _issue_set_row(db: AsyncSession, journal_title: str) -> Optional[AuthorIssueSet]:
    canon = await _canon_journal(db, journal_title)
    row = (
        await db.execute(select(AuthorIssueSet).where(AuthorIssueSet.journal_title == canon))
    ).scalar_one_or_none()
    if row is None and canon:
        row = (
            await db.execute(select(AuthorIssueSet).where(AuthorIssueSet.journal_title == ""))
        ).scalar_one_or_none()
    return row


async def _current_issue_articles(
    db: AsyncSession, user: User, journal_title: str
) -> list[AuthorArticle]:
    stored = await _issue_set_row(db, journal_title)
    if stored is None:
        return []
    ids: list[int] = []
    for item in stored.article_ids or []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    rows = list(
        (
            await db.execute(
                select(AuthorArticle)
                .options(*_load_options())
                .where(AuthorArticle.id.in_(ids), AuthorArticle.wing == "published")
            )
        ).scalars().all()
    )
    visible: list[AuthorArticle] = []
    for row in rows:
        try:
            visible.append(await _load_row(db, row.id, user))
        except HTTPException:
            continue
    return visible


async def _author_overlaps(
    db: AsyncSession,
    user: User,
    *,
    author_names: Optional[str],
    author_emails: Optional[str],
    journal_title: Optional[str],
    skip_id: Optional[int] = None,
) -> list:
    rows = await _current_issue_articles(db, user, journal_title or "")
    payload = [
        {
            "id": row.id,
            "ojs_number": row.ojs_number,
            "title": row.title,
            "author_names": row.author_names,
            "author_emails": row.author_emails,
        }
        for row in rows
    ]
    return find_author_overlaps(author_names, author_emails, payload, skip_id=skip_id)


async def _forbid_same_issue_authors(
    db: AsyncSession,
    user: User,
    *,
    author_names: Optional[str],
    author_emails: Optional[str],
    journal_title: Optional[str],
    skip_id: Optional[int] = None,
) -> None:
    hits = await _author_overlaps(
        db,
        user,
        author_names=author_names,
        author_emails=author_emails,
        journal_title=journal_title,
        skip_id=skip_id,
    )
    if hits:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=overlap_message(hits))


async def _add_to_current_issue(db: AsyncSession, row: AuthorArticle) -> None:
    canon = await _canon_journal(db, row.journal_title)
    stored = (
        await db.execute(select(AuthorIssueSet).where(AuthorIssueSet.journal_title == canon))
    ).scalar_one_or_none()
    if stored is None:
        return
    ids: list[int] = []
    for item in stored.article_ids or []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if row.id in ids:
        return
    ids.append(row.id)
    stored.article_ids = ids
    stored.updated_at = datetime.now(timezone.utc)
    flag_modified(stored, "article_ids")


async def _visible_query(db: AsyncSession, user: User, wing: Optional[str]):
    stmt = select(AuthorArticle).options(*_load_options()).order_by(AuthorArticle.id.desc())
    if wing:
        stmt = stmt.where(AuthorArticle.wing == wing)
    allowed = await allowed_journal_ids(db, user, desk="authors")
    if allowed is not None:
        if not allowed:
            stmt = stmt.where(AuthorArticle.owner_id == user.id, AuthorArticle.journal_id.is_(None))
        else:
            stmt = stmt.where(
                or_(AuthorArticle.journal_id.in_(allowed), AuthorArticle.owner_id == user.id)
            )
    return stmt


async def _load_row(db: AsyncSession, article_id: int, user: User) -> AuthorArticle:
    row = (
        await db.execute(
            select(AuthorArticle).options(*_load_options()).where(AuthorArticle.id == article_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    allowed = await allowed_journal_ids(db, user, desk="authors")
    if allowed is None:
        return row
    if row.owner_id == user.id:
        return row
    if row.journal_id and row.journal_id in allowed:
        return row
    raise HTTPException(status_code=404, detail="Article not found")


async def _journal_label(db: AsyncSession, journal_id: Optional[int]) -> str:
    if not journal_id:
        return "(empty)"
    journal = await db.get(Journal, journal_id)
    if journal is None:
        return str(journal_id)
    return journal.abbreviation or journal.name or str(journal_id)


async def _record_modifications(
    db: AsyncSession,
    row: AuthorArticle,
    user: User,
    diffs: list[dict[str, str]],
    snapshot: Optional[dict[str, Any]] = None,
) -> None:
    if not diffs:
        return
    nxt = int(
        (
            await db.execute(
                select(func.max(AuthorArticleChange.mod_number)).where(
                    AuthorArticleChange.article_id == row.id
                )
            )
        ).scalar()
        or 0
    ) + 1
    db.add(
        AuthorArticleChange(
            article_id=row.id,
            mod_number=nxt,
            changed_at=datetime.now(timezone.utc),
            user_id=user.id,
            account_username=user.username or "",
            account_email=user.email or "",
            account_name=_account_label(user),
            changes=diffs,
            snapshot=snapshot or {},
        )
    )


async def _apply_update(
    db: AsyncSession,
    row: AuthorArticle,
    user: User,
    data: dict[str, Any],
) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    if not row.original_snapshot:
        row.original_snapshot = _row_snapshot(row)
        flag_modified(row, "original_snapshot")
    if "wing" in data and data["wing"] is not None:
        wing = str(data["wing"]).strip().lower()
        if wing not in WINGS:
            raise HTTPException(status_code=400, detail="Wing must be in_process or published")
        _require_wing(user, wing)
        if row.wing != wing:
            if wing == "published":
                names = data["author_names"] if data.get("author_names") is not None else row.author_names
                emails = data["author_emails"] if data.get("author_emails") is not None else row.author_emails
                journal = data["journal_title"] if data.get("journal_title") is not None else row.journal_title
                await _forbid_same_issue_authors(
                    db,
                    user,
                    author_names=str(names or ""),
                    author_emails=str(emails or ""),
                    journal_title=str(journal or ""),
                    skip_id=row.id,
                )
            diffs.append(
                {
                    "field": "wing",
                    "label": FIELD_LABELS["wing"],
                    "previous": "Under process" if row.wing == "in_process" else "Published",
                    "new": "Under process" if wing == "in_process" else "Published",
                }
            )
            row.wing = wing
    if "journal_id" in data:
        journal_id = data["journal_id"]
        if journal_id is not None:
            await _require_author_journal(db, user, int(journal_id))
            journal_id = int(journal_id)
        if row.journal_id != journal_id:
            diffs.append(
                {
                    "field": "journal_id",
                    "label": FIELD_LABELS["journal_id"],
                    "previous": await _journal_label(db, row.journal_id),
                    "new": await _journal_label(db, journal_id),
                }
            )
            row.journal_id = journal_id
    if "journal_title" in data and data["journal_title"] is not None:
        nxt = str(data["journal_title"]).strip()
        catalog = await _ensure_author_catalog(db)
        nxt = _match_catalog_name(nxt, catalog) or nxt
        prev = row.journal_title or ""
        if prev != nxt:
            diffs.append(
                {
                    "field": "journal_title",
                    "label": FIELD_LABELS["journal_title"],
                    "previous": _display(prev),
                    "new": _display(nxt),
                }
            )
            row.journal_title = nxt
    for field in (
        "ojs_number",
        "title",
        "author_names",
        "author_emails",
        "plagiarism",
        "orcid_id",
        "doi_in_pdf",
        "editorial_status",
        "comments",
        "current_stage",
    ):
        if field in data and data[field] is not None:
            nxt = str(data[field])
            if field == "editorial_status":
                nxt = _editorial_status(nxt)
            elif field == "comments":
                nxt = _comments(nxt)
            elif field == "current_stage":
                nxt = _current_stage(nxt)
            else:
                nxt = nxt.strip()
            prev = getattr(row, field) or ""
            if prev != nxt:
                diffs.append(
                    {
                        "field": field,
                        "label": FIELD_LABELS[field],
                        "previous": _stage_label(prev) if field == "current_stage" else _display(prev),
                        "new": _stage_label(nxt) if field == "current_stage" else _display(nxt),
                    }
                )
                setattr(row, field, nxt)
    for field in (
        "received_date",
        "review_date",
        "accepted_date",
        "publish_date",
        "email_sent_date",
        "galley_sent_date",
        "galley_received_date",
        "soft_reminder_sent",
        "second_reminder_sent",
        "last_reminder_sent",
        "current_stage_started",
    ):
        if field in data:
            nxt = _blank(data[field] if data[field] is None else str(data[field]))
            prev = getattr(row, field)
            if (prev or None) != nxt:
                diffs.append(
                    {
                        "field": field,
                        "label": FIELD_LABELS[field],
                        "previous": _display(prev),
                        "new": _display(nxt),
                    }
                )
                setattr(row, field, nxt)
    if "review_rounds" in data and data["review_rounds"] is not None:
        nxt = _normalize_rounds(data["review_rounds"])
        prev = _normalize_rounds(row.review_rounds, fallback_received=row.review_date)
        if _format_rounds(prev) != _format_rounds(nxt):
            diffs.append(
                {
                    "field": "review_rounds",
                    "label": FIELD_LABELS["review_rounds"],
                    "previous": _format_rounds(prev),
                    "new": _format_rounds(nxt),
                }
            )
            row.review_rounds = nxt
            flag_modified(row, "review_rounds")
            if nxt:
                row.review_date = nxt[0].get("received_date")
    for field in ("email_sent", "repeat_done", "current_stage_passed"):
        if field in data and data[field] is not None:
            nxt = bool(data[field])
            prev = bool(getattr(row, field))
            if prev != nxt:
                diffs.append(
                    {
                        "field": field,
                        "label": FIELD_LABELS[field],
                        "previous": _display(prev),
                        "new": _display(nxt),
                    }
                )
                setattr(row, field, nxt)
    if "current_stage_days" in data and data["current_stage_days"] is not None:
        nxt = _stage_days(data["current_stage_days"])
        prev = int(row.current_stage_days or DEFAULT_STAGE_DAYS)
        if prev != nxt:
            diffs.append(
                {
                    "field": "current_stage_days",
                    "label": FIELD_LABELS["current_stage_days"],
                    "previous": _display(prev),
                    "new": _display(nxt),
                }
            )
            row.current_stage_days = nxt
    if diffs:
        row.updated_at = datetime.now(timezone.utc)
        content_changed = any(item.get("field") != "wing" for item in diffs)
        await _record_modifications(
            db,
            row,
            user,
            diffs,
            snapshot=_row_snapshot(row) if content_changed else None,
        )
    return diffs


async def _reload(db: AsyncSession, article_id: int) -> AuthorArticle:
    return (
        await db.execute(
            select(AuthorArticle).options(*_load_options()).where(AuthorArticle.id == article_id)
        )
    ).scalar_one()


@router.get("", response_model=list[AuthorArticleOut])
async def list_author_articles(
    db: Db,
    user: CurrentUser,
    wing: Optional[str] = Query(default=None),
):
    if wing and wing not in WINGS:
        raise HTTPException(status_code=400, detail="Wing must be in_process or published")
    if wing:
        _require_wing(user, wing)
    rows = list((await db.execute(await _visible_query(db, user, wing))).scalars().all())
    if not wing:
        rows = [row for row in rows if user.has_author_wing(row.wing)]
    return [_payload(row) for row in rows]


@router.get("/journals", response_model=list[AuthorJournalOut])
async def list_author_journals(db: Db, user: CurrentUser):
    await purge_removed_journals(db)
    catalog = await _ensure_author_catalog(db)
    out: list[AuthorJournalOut] = [
        AuthorJournalOut(id=None, name=row.name, abbreviation=row.abbreviation or None)
        for row in catalog
    ]
    seen = {(row.name or "").strip().lower() for row in catalog}
    seen.update((row.abbreviation or "").strip().lower() for row in catalog if row.abbreviation)
    cite_rows = list((await db.execute(select(Journal).order_by(Journal.name))).scalars().all())
    allowed = await allowed_journal_ids(db, user, desk="authors")
    others = cite_rows
    if allowed is not None:
        others = [row for row in cite_rows if row.id in allowed]
    for row in others:
        name = (row.name or "").strip()
        abbr = (row.abbreviation or "").strip()
        if is_removed_journal(name, abbr):
            continue
        if name.lower() in seen or abbr.lower() in seen:
            continue
        out.append(AuthorJournalOut(id=row.id, name=row.name, abbreviation=row.abbreviation))
        if name:
            seen.add(name.lower())
        if abbr:
            seen.add(abbr.lower())
    return out


@router.post("/journals", response_model=AuthorJournalOut, status_code=status.HTTP_201_CREATED)
async def add_author_journal(body: AuthorJournalIn, db: Db, user: CurrentUser):
    if not user.is_full_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can add a journal name to the author database.",
        )
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Enter the journal name.")
    abbr = (body.abbreviation or "").strip()
    if name.lower() == "demo extra journal" or is_removed_journal(name, abbr):
        raise HTTPException(status_code=400, detail="That journal name was removed.")
    await _ensure_author_catalog(db)
    existing = list((await db.execute(select(AuthorDbJournal))).scalars().all())
    needle = name.lower()
    for row in existing:
        if (row.name or "").strip().lower() == needle:
            raise HTTPException(status_code=409, detail="That journal name is already in the list.")
    row = AuthorDbJournal(name=name, abbreviation=abbr, created_by=user.id)
    db.add(row)
    await db.flush()
    return AuthorJournalOut(id=None, name=row.name, abbreviation=row.abbreviation or None)


@router.get("/template")
async def download_import_template():
    book = Workbook()
    sheet = book.active
    sheet.title = "Author database"
    sheet.append(EXCEL_HEADERS)
    sheet.append(
        [
            "IJIST-2024-118",
            "Sample title",
            "Ali Khan; Sara Ahmed",
            "ali@example.com; sara@example.com",
            "2024-01-05",
            "9%",
            "0000-0002-1825-0097",
            "2024-01-12",
            "2024-01-20",
            "2024-02-01",
            "",
            "",
            "",
            "",
            "2024-03-10",
            "2024-03-12",
            "2024-03-18",
            "",
            "Submission",
            "",
            "",
            "",
            "",
            "",
            "",
            "7",
            "No",
            "IJIST",
            "in_process",
        ]
    )
    buf = io.BytesIO()
    book.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="author-database-template.xlsx"'},
    )


@router.get("/sanitization", response_model=AuthorIssueSetOut)
async def get_issue_sanitization(
    db: Db,
    user: CurrentUser,
    journal_title: str = Query(default=""),
):
    if not (user.has_author_wing("published") or user.has_author_wing("in_process")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not granted that author-database wing",
        )
    canon = await _canon_journal(db, journal_title)
    stored = (
        await db.execute(select(AuthorIssueSet).where(AuthorIssueSet.journal_title == canon))
    ).scalar_one_or_none()
    selected_ids = []
    if stored is not None:
        for item in stored.article_ids or []:
            try:
                selected_ids.append(int(item))
            except (TypeError, ValueError):
                continue
    published_rows = list((await db.execute(await _visible_query(db, user, "published"))).scalars().all())
    scheduled_rows: list[AuthorArticle] = []
    if user.has_author_wing("in_process"):
        scheduled_rows = list((await db.execute(await _visible_query(db, user, "in_process"))).scalars().all())
    if canon:
        published_rows = [row for row in published_rows if _same_journal(row, canon)]
        scheduled_rows = [row for row in scheduled_rows if _same_journal(row, canon)]
    current = [_issue_brief(row) for row in published_rows if row.id in selected_ids]
    return AuthorIssueSetOut(
        journal_title=canon or journal_title,
        label=(stored.label if stored else "Current issue"),
        article_ids=[row.id for row in current],
        current_issue=current,
        published=[_issue_brief(row) for row in published_rows],
        scheduled=[_issue_brief(row) for row in scheduled_rows],
    )


@router.put("/sanitization", response_model=AuthorIssueSetOut)
async def save_issue_sanitization(body: AuthorIssueSetIn, db: Db, user: CurrentUser):
    _require_wing(user, "published")
    canon = await _canon_journal(db, body.journal_title)
    wanted: list[int] = []
    for item in body.article_ids or []:
        try:
            wanted.append(int(item))
        except (TypeError, ValueError):
            continue
    unique: list[int] = []
    for article_id in wanted:
        if article_id not in unique:
            unique.append(article_id)
    saved_ids: list[int] = []
    for article_id in unique:
        row = await _load_row(db, article_id, user)
        if row.wing != "published":
            raise HTTPException(
                status_code=400,
                detail=f"OJS {row.ojs_number or article_id} is not in published articles.",
            )
        if canon and not _same_journal(row, canon):
            raise HTTPException(
                status_code=400,
                detail=f"OJS {row.ojs_number or article_id} is not in {canon}.",
            )
        saved_ids.append(row.id)
    stored = (
        await db.execute(select(AuthorIssueSet).where(AuthorIssueSet.journal_title == canon))
    ).scalar_one_or_none()
    label = (body.label or "").strip() or "Current issue"
    if stored is None:
        stored = AuthorIssueSet(
            journal_title=canon,
            label=label,
            article_ids=saved_ids,
            owner_id=user.id,
        )
        db.add(stored)
    else:
        stored.label = label
        stored.article_ids = saved_ids
        stored.owner_id = user.id
        stored.updated_at = datetime.now(timezone.utc)
        flag_modified(stored, "article_ids")
    await db.flush()
    return await get_issue_sanitization(db, user, journal_title=canon)


@router.post("/sanitization/check", response_model=AuthorSanitizeCheckOut)
async def check_issue_sanitization(body: AuthorSanitizeCheckIn, db: Db, user: CurrentUser):
    scheduled = None
    authors = body.author_names
    emails = body.author_emails
    journal = body.journal_title
    ojs = body.ojs_number
    title = body.title
    skip_id = None
    if body.article_id is not None:
        row = await _load_row(db, body.article_id, user)
        scheduled = _issue_brief(row)
        authors = row.author_names
        emails = row.author_emails
        journal = row.journal_title or journal
        ojs = row.ojs_number
        title = row.title
        skip_id = row.id
    elif not authors.strip() and not emails.strip():
        raise HTTPException(
            status_code=400,
            detail="Select a scheduled article or enter the author names to check.",
        )
    hits = await _author_overlaps(
        db,
        user,
        author_names=authors,
        author_emails=emails,
        journal_title=journal,
        skip_id=skip_id,
    )
    if scheduled is None:
        scheduled = AuthorIssueArticleOut(
            id=0,
            wing="in_process",
            journal_title=journal,
            journal_name=journal or None,
            ojs_number=ojs,
            title=title,
            author_names=authors,
            author_emails=emails,
        )
    allowed = not hits
    message = overlap_message(hits) if hits else "No overlapping authors with the current issue. This article may be published."
    return AuthorSanitizeCheckOut(
        allowed=allowed,
        message=message,
        journal_title=await _canon_journal(db, journal),
        scheduled=scheduled,
        overlaps=[
            AuthorOverlapOut(
                author=hit.author,
                matched_as=hit.matched_as,
                issue_article_id=hit.issue_article_id,
                issue_ojs=hit.issue_ojs,
                issue_title=hit.issue_title,
                reason=hit.reason,
            )
            for hit in hits
        ],
    )


@router.post("/sanitization/publish", response_model=AuthorSanitizeCheckOut)
async def publish_after_sanitization(body: AuthorSanitizeCheckIn, db: Db, user: CurrentUser):
    if body.article_id is None:
        raise HTTPException(status_code=400, detail="Select the scheduled article to publish.")
    _require_wing(user, "published")
    row = await _load_row(db, body.article_id, user)
    if row.wing == "published":
        raise HTTPException(status_code=400, detail="That article is already published.")
    hits = await _author_overlaps(
        db,
        user,
        author_names=row.author_names,
        author_emails=row.author_emails,
        journal_title=row.journal_title,
        skip_id=row.id,
    )
    if hits:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=overlap_message(hits))
    await _apply_update(db, row, user, {"wing": "published"})
    await _add_to_current_issue(db, row)
    await db.flush()
    return AuthorSanitizeCheckOut(
        allowed=True,
        message="Article moved to published articles and added to the current issue.",
        journal_title=await _canon_journal(db, row.journal_title),
        scheduled=_issue_brief(await _reload(db, row.id)),
        overlaps=[],
    )


@router.post("", response_model=AuthorArticleOut, status_code=status.HTTP_201_CREATED)
async def create_author_article(body: AuthorArticleIn, db: Db, user: CurrentUser):
    wing = (body.wing or "in_process").strip().lower()
    if wing not in WINGS:
        raise HTTPException(status_code=400, detail="Wing must be in_process or published")
    _require_wing(user, wing)
    if body.journal_id is not None:
        await _require_author_journal(db, user, body.journal_id)
    catalog = await _ensure_author_catalog(db)
    title = (body.journal_title or "").strip()
    if not title and body.journal_id is not None:
        journal = await db.get(Journal, body.journal_id)
        if journal is not None:
            title = journal.name or journal.abbreviation or ""
    title = _match_catalog_name(title, catalog) or title
    if wing == "published":
        await _forbid_same_issue_authors(
            db,
            user,
            author_names=body.author_names,
            author_emails=body.author_emails,
            journal_title=title,
        )
    rounds = _normalize_rounds(body.review_rounds, fallback_received=body.review_date)
    row = AuthorArticle(
        wing=wing,
        journal_id=body.journal_id,
        journal_title=title,
        owner_id=user.id,
        ojs_number=(body.ojs_number or "").strip(),
        title=(body.title or "").strip(),
        author_names=(body.author_names or "").strip(),
        author_emails=(body.author_emails or "").strip(),
        email_sent=bool(body.email_sent_date) or bool(body.email_sent),
        email_sent_date=_blank(body.email_sent_date),
        plagiarism=(body.plagiarism or "").strip(),
        orcid_id=(body.orcid_id or "").strip(),
        received_date=_blank(body.received_date),
        review_date=rounds[0].get("received_date") if rounds else _blank(body.review_date),
        review_rounds=rounds,
        accepted_date=_blank(body.accepted_date),
        galley_sent_date=_blank(body.galley_sent_date),
        galley_received_date=_blank(body.galley_received_date),
        publish_date=_blank(body.publish_date),
        editorial_status=_editorial_status(body.editorial_status),
        soft_reminder_sent=_blank(body.soft_reminder_sent),
        second_reminder_sent=_blank(body.second_reminder_sent),
        last_reminder_sent=_blank(body.last_reminder_sent),
        comments=_comments(body.comments),
        current_stage=_current_stage(body.current_stage),
        current_stage_started=_blank(body.current_stage_started),
        current_stage_days=_stage_days(body.current_stage_days),
        current_stage_passed=bool(body.current_stage_passed),
        repeat_done=bool(body.repeat_done),
        doi_in_pdf=(body.doi_in_pdf or "").strip(),
    )
    if not row.title and not row.ojs_number:
        raise HTTPException(status_code=400, detail="Enter an OJS number or a title.")
    db.add(row)
    await db.flush()
    row.original_snapshot = _row_snapshot(row)
    flag_modified(row, "original_snapshot")
    await db.flush()
    return _payload(await _reload(db, row.id))


@router.get("/{article_id}", response_model=AuthorArticleOut)
async def get_author_article(article_id: int, db: Db, user: CurrentUser):
    return _payload(await _load_row(db, article_id, user))


@router.patch("/{article_id}", response_model=AuthorArticleOut)
async def update_author_article(
    article_id: int, body: AuthorArticlePatch, db: Db, user: CurrentUser
):
    row = await _load_row(db, article_id, user)
    await _apply_update(db, row, user, body.model_dump(exclude_unset=True))
    await db.flush()
    db.expire(row, ["changes", "journal"])
    return _payload(await _reload(db, row.id))


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_author_article(
    article_id: int,
    db: Db,
    user: CurrentUser,
    body: Optional[AuthorArticleDeleteIn] = None,
):
    if not user.is_full_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users cannot delete author-database records. Save a modification instead.",
        )
    password = (body.password if body else "") or ""
    password = password.strip()
    if not password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enter the admin password to delete this OJS record.",
        )
    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That password is not correct.",
        )
    row = await _load_row(db, article_id, user)
    await db.delete(row)
    await db.flush()
    return None


def _norm_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _header_key(header: str) -> Optional[str]:
    mapped = HEADER_MAP.get(header)
    if mapped:
        return mapped
    sent = re.fullmatch(r"round (\d+) review sent date", header)
    if sent:
        return f"r{sent.group(1)}_sent"
    received = re.fullmatch(r"round (\d+) review receive(?:d)? date", header)
    if received:
        return f"r{received.group(1)}_received"
    return None


def _is_date_key(key: str) -> bool:
    return key in {
        "received_date",
        "review_date",
        "accepted_date",
        "publish_date",
        "email_sent_date",
        "galley_sent_date",
        "galley_received_date",
        "soft_reminder_sent",
        "second_reminder_sent",
        "last_reminder_sent",
        "current_stage_started",
    } or bool(re.fullmatch(r"r\d+_(sent|received)", key))


async def _resolve_author_journal(db: AsyncSession, user: User, name: str) -> tuple[Optional[int], str]:
    catalog_rows = await _ensure_author_catalog(db)
    canonical = _match_catalog_name(name, catalog_rows)
    journal_id = await _journal_by_name(db, user, name)
    if journal_id is not None:
        return journal_id, canonical or name.strip()
    if canonical:
        return None, canonical
    return None, ""


def _rounds_from_import(item: dict[str, str]) -> list[dict[str, Any]]:
    by_n: dict[int, dict[str, Any]] = {}
    for key, value in item.items():
        match = re.fullmatch(r"r(\d+)_(sent|received)", key)
        if not match:
            continue
        slot = by_n.setdefault(int(match.group(1)), {})
        field = "sent_date" if match.group(2) == "sent" else "received_date"
        slot[field] = value
    ordered = [
        {
            "round": number,
            "sent_date": by_n[number].get("sent_date"),
            "received_date": by_n[number].get("received_date"),
        }
        for number in sorted(by_n)
    ]
    return _normalize_rounds(ordered, fallback_received=item.get("review_date"))


HEADER_MAP = {
    "ojs": "ojs_number",
    "ojs number": "ojs_number",
    "ojs no": "ojs_number",
    "title": "title",
    "author names": "author_names",
    "authors": "author_names",
    "author name": "author_names",
    "email": "author_emails",
    "emails": "author_emails",
    "email addresses": "author_emails",
    "email addresses of authors": "author_emails",
    "author emails": "author_emails",
    "email sent": "email_sent",
    "if the email sent": "email_sent",
    "email sent date": "email_sent_date",
    "plagiarism": "plagiarism",
    "orcid": "orcid_id",
    "orcid id": "orcid_id",
    "receive date": "received_date",
    "received date": "received_date",
    "review date": "review_date",
    "round 1 review sent date": "r1_sent",
    "round 1 review receive date": "r1_received",
    "round 2 review sent date": "r2_sent",
    "round 2 review receive date": "r2_received",
    "accepted date": "accepted_date",
    "acceptance date": "accepted_date",
    "accept date": "accepted_date",
    "galley sent date": "galley_sent_date",
    "gally sent date": "galley_sent_date",
    "galley received date": "galley_received_date",
    "gally received date": "galley_received_date",
    "publish date": "publish_date",
    "published date": "publish_date",
    "status": "editorial_status",
    "editorial status": "editorial_status",
    "soft reminder sent": "soft_reminder_sent",
    "second reminder sent": "second_reminder_sent",
    "last reminder sent": "last_reminder_sent",
    "comments": "comments",
    "comment": "comments",
    "current state": "current_stage",
    "current stage": "current_stage",
    "current-state date": "current_stage_started",
    "current state date": "current_stage_started",
    "days allowed": "current_stage_days",
    "current state passed": "current_stage_passed",
    "repeat done": "repeat_done",
    "repeat": "repeat_done",
    "doi": "doi_in_pdf",
    "doi in pdf": "doi_in_pdf",
    "journal": "journal",
    "wing": "wing",
}


def _parse_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "y", "yes", "true", "done", "sent"}


def _parse_date(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if isinstance(value, float):
        try:
            from openpyxl.utils.datetime import from_excel

            return from_excel(value).date().isoformat()
        except Exception:
            return text
    return text[:32]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value).strip()


def _read_table(data: bytes, filename: str) -> list[dict[str, str]]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        import csv

        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    else:
        book = load_workbook(io.BytesIO(data), data_only=True)
        sheet = book.active
        rows = [[cell for cell in line] for line in sheet.iter_rows(values_only=True)]
    if not rows:
        return []
    headers = [_norm_header(col) for col in rows[0]]
    mapped = [_header_key(header) for header in headers]
    if not any(mapped):
        raise HTTPException(
            status_code=400,
            detail="That file does not use the author-database column names. Download the Excel template.",
        )
    out: list[dict[str, str]] = []
    for raw in rows[1:]:
        if raw is None:
            continue
        item: dict[str, str] = {}
        empty = True
        for idx, key in enumerate(mapped):
            if not key or idx >= len(raw):
                continue
            value = raw[idx]
            if _is_date_key(key):
                parsed = _parse_date(value)
                item[key] = parsed or ""
            elif key in ("email_sent", "repeat_done", "current_stage_passed"):
                item[key] = "yes" if _parse_bool(value) else "no"
            else:
                item[key] = _cell(value)
            if item[key]:
                empty = False
        if not empty:
            out.append(item)
    return out


async def _journal_by_name(db: AsyncSession, user: User, name: str) -> Optional[int]:
    needle = name.strip().lower()
    if not needle:
        return None
    journals = list((await db.execute(select(Journal))).scalars().all())
    allowed = await allowed_journal_ids(db, user, desk="authors")
    for journal in journals:
        label = (journal.abbreviation or journal.name or "").strip().lower()
        full = (journal.name or "").strip().lower()
        if needle in {label, full} and (allowed is None or journal.id in allowed):
            return journal.id
    return None


@router.post("/import", response_model=AuthorImportResult)
async def import_author_articles(
    db: Db,
    user: CurrentUser,
    file: UploadFile = File(...),
    wing: str = Query(default="in_process"),
):
    wing = (wing or "in_process").strip().lower()
    if wing not in WINGS:
        raise HTTPException(status_code=400, detail="Wing must be in_process or published")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The Excel file is empty.")
    try:
        table = _read_table(data, file.filename or "import.xlsx")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read that Excel file. {exc}") from exc

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    articles: list[AuthorArticleOut] = []
    for index, item in enumerate(table, start=2):
        title = item.get("title") or ""
        ojs = item.get("ojs_number") or ""
        if not title and not ojs:
            skipped += 1
            continue
        journal_id = None
        journal_title = ""
        if item.get("journal"):
            journal_id, journal_title = await _resolve_author_journal(db, user, item["journal"])
            if journal_id is None and not journal_title:
                errors.append(f"Row {index}: journal “{item['journal']}” was not found or is not assigned.")
                skipped += 1
                continue
        wanted_wing = (item.get("wing") or wing).strip().lower()
        if wanted_wing in {"under process", "under-process", "in process"}:
            wanted_wing = "in_process"
        if wanted_wing in {"published articles", "published"}:
            wanted_wing = "published"
        if wanted_wing not in WINGS:
            wanted_wing = wing
        existing = None
        if ojs:
            stmt = select(AuthorArticle).options(*_load_options()).where(
                AuthorArticle.ojs_number == ojs, AuthorArticle.wing == wanted_wing
            )
            if journal_id is not None:
                stmt = stmt.where(AuthorArticle.journal_id == journal_id)
            existing = (await db.execute(stmt.order_by(AuthorArticle.id.desc()))).scalars().first()
            if existing is not None:
                try:
                    await _load_row(db, existing.id, user)
                except HTTPException:
                    existing = None
        rounds = _rounds_from_import(item)
        payload = {
            "wing": wanted_wing,
            "journal_id": journal_id if journal_id is not None else (existing.journal_id if existing else None),
            "journal_title": journal_title or (existing.journal_title if existing else ""),
            "ojs_number": ojs,
            "title": title,
            "author_names": item.get("author_names") or "",
            "author_emails": item.get("author_emails") or "",
            "email_sent": _parse_bool(item.get("email_sent")) or bool(item.get("email_sent_date")),
            "email_sent_date": item.get("email_sent_date") or None,
            "plagiarism": item.get("plagiarism") or "",
            "orcid_id": item.get("orcid_id") or "",
            "received_date": item.get("received_date") or None,
            "review_date": item.get("review_date") or None,
            "review_rounds": rounds,
            "accepted_date": item.get("accepted_date") or None,
            "galley_sent_date": item.get("galley_sent_date") or None,
            "galley_received_date": item.get("galley_received_date") or None,
            "publish_date": item.get("publish_date") or None,
            "editorial_status": _editorial_status(item.get("editorial_status")),
            "soft_reminder_sent": item.get("soft_reminder_sent") or None,
            "second_reminder_sent": item.get("second_reminder_sent") or None,
            "last_reminder_sent": item.get("last_reminder_sent") or None,
            "comments": _comments(item.get("comments")),
            "current_stage": _current_stage(item.get("current_stage")),
            "current_stage_started": item.get("current_stage_started") or None,
            "current_stage_days": _stage_days(item.get("current_stage_days") or DEFAULT_STAGE_DAYS),
            "current_stage_passed": _parse_bool(item.get("current_stage_passed")),
            "repeat_done": _parse_bool(item.get("repeat_done")),
            "doi_in_pdf": item.get("doi_in_pdf") or "",
        }
        try:
            if existing is None:
                created_row = await create_author_article(AuthorArticleIn(**payload), db, user)
                created += 1
                articles.append(created_row)
            else:
                await _apply_update(db, existing, user, payload)
                await db.flush()
                db.expire(existing, ["changes", "journal"])
                updated += 1
                articles.append(_payload(await _reload(db, existing.id)))
        except HTTPException as exc:
            errors.append(f"Row {index}: {exc.detail}")
            skipped += 1
    return AuthorImportResult(
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
        articles=articles,
    )
