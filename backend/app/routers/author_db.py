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
from app.database.session import get_db
from app.models.citation import AuthorArticle, AuthorArticleChange, AuthorDbJournal, Journal
from app.models.user import User
from app.schemas.author_db import (
    AUTHOR_DB_JOURNALS,
    FIELD_LABELS,
    AuthorArticleIn,
    AuthorArticleOut,
    AuthorArticlePatch,
    AuthorFieldChangeOut,
    AuthorImportResult,
    AuthorJournalIn,
    AuthorJournalOut,
    AuthorModificationOut,
    ReviewRound,
    WINGS,
)
from app.services.journal_access import allowed_journal_ids, require_journal_access

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
    "Journal",
    "Wing",
]


def _blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    }


async def _ensure_author_catalog(db: AsyncSession) -> list[AuthorDbJournal]:
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
    ):
        if field in data and data[field] is not None:
            nxt = str(data[field]).strip()
            prev = getattr(row, field) or ""
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
    for field in (
        "received_date",
        "review_date",
        "accepted_date",
        "publish_date",
        "email_sent_date",
        "galley_sent_date",
        "galley_received_date",
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
    for field in ("email_sent", "repeat_done"):
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
    await _ensure_author_catalog(db)
    existing = list((await db.execute(select(AuthorDbJournal))).scalars().all())
    needle = name.lower()
    for row in existing:
        if (row.name or "").strip().lower() == needle:
            raise HTTPException(status_code=409, detail="That journal name is already in the list.")
    abbr = (body.abbreviation or "").strip()
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
async def delete_author_article(article_id: int, db: Db, user: CurrentUser):
    if not user.is_full_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users cannot delete author-database records. Save a modification instead.",
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
            elif key in ("email_sent", "repeat_done"):
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
