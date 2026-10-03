"""Author database management: under-process and published articles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.citation import AuthorArticle
from app.models.user import User
from app.schemas.author_db import AuthorArticleIn, AuthorArticleOut, AuthorArticlePatch, WINGS
from app.services.journal_access import allowed_journal_ids, require_journal_access

router = APIRouter(prefix="/author-articles", tags=["Author database"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _payload(row: AuthorArticle) -> AuthorArticleOut:
    journal = row.journal
    return AuthorArticleOut(
        id=row.id,
        wing=row.wing,
        journal_id=row.journal_id,
        journal_name=(journal.abbreviation or journal.name) if journal else None,
        owner_id=row.owner_id,
        ojs_number=row.ojs_number or "",
        title=row.title or "",
        author_names=row.author_names or "",
        author_emails=row.author_emails or "",
        email_sent=bool(row.email_sent),
        plagiarism=row.plagiarism or "",
        orcid_id=row.orcid_id or "",
        received_date=row.received_date,
        review_date=row.review_date,
        accepted_date=row.accepted_date,
        publish_date=row.publish_date,
        repeat_done=bool(row.repeat_done),
        doi_in_pdf=row.doi_in_pdf or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _visible_query(db: AsyncSession, user: User, wing: Optional[str]):
    stmt = select(AuthorArticle).options(selectinload(AuthorArticle.journal)).order_by(
        AuthorArticle.id.desc()
    )
    if wing:
        stmt = stmt.where(AuthorArticle.wing == wing)
    allowed = await allowed_journal_ids(db, user)
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
            select(AuthorArticle)
            .options(selectinload(AuthorArticle.journal))
            .where(AuthorArticle.id == article_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    allowed = await allowed_journal_ids(db, user)
    if allowed is None:
        return row
    if row.owner_id == user.id:
        return row
    if row.journal_id and row.journal_id in allowed:
        return row
    raise HTTPException(status_code=404, detail="Article not found")


@router.get("", response_model=list[AuthorArticleOut])
async def list_author_articles(
    db: Db,
    user: CurrentUser,
    wing: Optional[str] = Query(default=None),
):
    if wing and wing not in WINGS:
        raise HTTPException(status_code=400, detail="Wing must be in_process or published")
    rows = list((await db.execute(await _visible_query(db, user, wing))).scalars().all())
    return [_payload(row) for row in rows]


@router.post("", response_model=AuthorArticleOut, status_code=status.HTTP_201_CREATED)
async def create_author_article(body: AuthorArticleIn, db: Db, user: CurrentUser):
    wing = (body.wing or "in_process").strip().lower()
    if wing not in WINGS:
        raise HTTPException(status_code=400, detail="Wing must be in_process or published")
    if body.journal_id is not None:
        await require_journal_access(db, user, body.journal_id)
    row = AuthorArticle(
        wing=wing,
        journal_id=body.journal_id,
        owner_id=user.id,
        ojs_number=(body.ojs_number or "").strip(),
        title=(body.title or "").strip(),
        author_names=(body.author_names or "").strip(),
        author_emails=(body.author_emails or "").strip(),
        email_sent=bool(body.email_sent),
        plagiarism=(body.plagiarism or "").strip(),
        orcid_id=(body.orcid_id or "").strip(),
        received_date=_blank(body.received_date),
        review_date=_blank(body.review_date),
        accepted_date=_blank(body.accepted_date),
        publish_date=_blank(body.publish_date),
        repeat_done=bool(body.repeat_done),
        doi_in_pdf=(body.doi_in_pdf or "").strip(),
    )
    if not row.title and not row.ojs_number:
        raise HTTPException(status_code=400, detail="Enter an OJS number or a title.")
    db.add(row)
    await db.flush()
    loaded = (
        await db.execute(
            select(AuthorArticle)
            .options(selectinload(AuthorArticle.journal))
            .where(AuthorArticle.id == row.id)
        )
    ).scalar_one()
    return _payload(loaded)


@router.patch("/{article_id}", response_model=AuthorArticleOut)
async def update_author_article(
    article_id: int, body: AuthorArticlePatch, db: Db, user: CurrentUser
):
    row = await _load_row(db, article_id, user)
    data = body.model_dump(exclude_unset=True)
    if "wing" in data and data["wing"] is not None:
        wing = data["wing"].strip().lower()
        if wing not in WINGS:
            raise HTTPException(status_code=400, detail="Wing must be in_process or published")
        row.wing = wing
        data.pop("wing")
    if "journal_id" in data:
        journal_id = data.pop("journal_id")
        if journal_id is not None:
            await require_journal_access(db, user, journal_id)
        row.journal_id = journal_id
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
            setattr(row, field, str(data[field]).strip())
    for field in ("received_date", "review_date", "accepted_date", "publish_date"):
        if field in data:
            setattr(row, field, _blank(data[field]))
    for field in ("email_sent", "repeat_done"):
        if field in data and data[field] is not None:
            setattr(row, field, bool(data[field]))
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    loaded = (
        await db.execute(
            select(AuthorArticle)
            .options(selectinload(AuthorArticle.journal))
            .where(AuthorArticle.id == row.id)
        )
    ).scalar_one()
    return _payload(loaded)


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_author_article(article_id: int, db: Db, user: CurrentUser):
    row = await _load_row(db, article_id, user)
    await db.delete(row)
    await db.flush()
    return None
