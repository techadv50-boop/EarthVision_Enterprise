"""Per-user journal visibility for the citation archive."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation import Journal
from app.models.user import User, user_journals


async def _assigned_ids(db: AsyncSession, user: User) -> set[int]:
    result = await db.execute(
        select(user_journals.c.journal_id).where(user_journals.c.user_id == user.id)
    )
    return set(result.scalars().all())


async def allowed_journal_ids(
    db: AsyncSession, user: User, *, desk: str = "citation"
) -> Optional[set[int]]:
    """Journal IDs this user may see and cite from.

    ``None`` means every journal. An empty set means none.
    """
    if user.is_full_admin():
        return None
    assigned = await _assigned_ids(db, user)
    if desk == "authors":
        if not user.has_service("authors"):
            if user.service_privileges is None:
                return assigned
            return set()
        if user.sees_all_journals():
            return None
        return assigned if assigned else None
    if user.sees_all_journals() and user.has_service("citation"):
        return None
    if user.has_service("citation"):
        return assigned
    if user.service_privileges is None:
        return assigned
    return set()


async def user_can_access_journal(
    db: AsyncSession, user: User, journal_id: int, *, desk: str = "citation"
) -> bool:
    allowed = await allowed_journal_ids(db, user, desk=desk)
    if allowed is None:
        return True
    return journal_id in allowed


async def require_journal_access(
    db: AsyncSession, user: User, journal_id: int, *, desk: str = "citation"
) -> Journal:
    journal = await db.get(Journal, journal_id)
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
    if not await user_can_access_journal(db, user, journal.id, desk=desk):
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
