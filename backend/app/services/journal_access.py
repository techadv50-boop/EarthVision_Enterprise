"""Per-user journal visibility for the citation archive."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation import Journal
from app.models.user import User, user_journals


async def allowed_journal_ids(db: AsyncSession, user: User) -> Optional[set[int]]:
    """Journal IDs this user may see and cite from.

    ``None`` means every journal (citation admin). An empty set means none.
    """
    if user.is_citation_admin():
        return None
    result = await db.execute(
        select(user_journals.c.journal_id).where(user_journals.c.user_id == user.id)
    )
    return set(result.scalars().all())


async def user_can_access_journal(db: AsyncSession, user: User, journal_id: int) -> bool:
    allowed = await allowed_journal_ids(db, user)
    if allowed is None:
        return True
    return journal_id in allowed


async def require_journal_access(db: AsyncSession, user: User, journal_id: int) -> Journal:
    journal = await db.get(Journal, journal_id)
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
    if not await user_can_access_journal(db, user, journal.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
    return journal


async def set_user_journals(db: AsyncSession, user: User, journal_ids: list[int]) -> list[int]:
    unique_ids = list(dict.fromkeys(int(jid) for jid in journal_ids))
    if unique_ids:
        result = await db.execute(select(Journal).where(Journal.id.in_(unique_ids)))
        found = {journal.id for journal in result.scalars().all()}
        missing = [jid for jid in unique_ids if jid not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more journals were not found",
            )
    await db.execute(delete(user_journals).where(user_journals.c.user_id == user.id))
    for journal_id in unique_ids:
        await db.execute(
            insert(user_journals).values(user_id=user.id, journal_id=journal_id)
        )
    await db.flush()
    db.expire(user, ["allowed_journals"])
    return unique_ids
