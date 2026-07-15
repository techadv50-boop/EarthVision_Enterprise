"""Bookmark service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.bookmark import Bookmark
from app.models.user import User
from app.schemas.bookmark import BookmarkCreate, BookmarkUpdate


class BookmarkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user: User, data: BookmarkCreate) -> Bookmark:
        bookmark = Bookmark(user_id=user.id, **data.model_dump())
        self.session.add(bookmark)
        await self.session.flush()
        await self.session.refresh(bookmark)
        return bookmark

    async def list_for_user(self, user: User) -> list[Bookmark]:
        result = await self.session.execute(
            select(Bookmark)
            .where(Bookmark.user_id == user.id)
            .order_by(Bookmark.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, bookmark_id: str, user: User) -> Bookmark:
        result = await self.session.execute(
            select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == user.id)
        )
        bookmark = result.scalar_one_or_none()
        if bookmark is None:
            raise NotFoundError("Bookmark not found")
        return bookmark

    async def update(self, bookmark_id: str, user: User, data: BookmarkUpdate) -> Bookmark:
        bookmark = await self.get(bookmark_id, user)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(bookmark, key, value)
        await self.session.flush()
        await self.session.refresh(bookmark)
        return bookmark

    async def delete(self, bookmark_id: str, user: User) -> None:
        bookmark = await self.get(bookmark_id, user)
        await self.session.delete(bookmark)
        await self.session.flush()
