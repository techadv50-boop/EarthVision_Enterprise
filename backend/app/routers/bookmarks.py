"""Bookmark routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.bookmark import BookmarkCreate, BookmarkResponse, BookmarkUpdate
from app.schemas.common import MessageResponse
from app.services.bookmark_service import BookmarkService

router = APIRouter(prefix="/bookmarks", tags=["Bookmarks"])


@router.get("", response_model=list[BookmarkResponse])
async def list_bookmarks(db: DbSession, user: CurrentUser) -> list[BookmarkResponse]:
    service = BookmarkService(db)
    items = await service.list_for_user(user)
    return [BookmarkResponse.model_validate(b) for b in items]


@router.post("", response_model=BookmarkResponse, status_code=201)
async def create_bookmark(
    data: BookmarkCreate, db: DbSession, user: CurrentUser
) -> BookmarkResponse:
    service = BookmarkService(db)
    bookmark = await service.create(user, data)
    return BookmarkResponse.model_validate(bookmark)


@router.patch("/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: str, data: BookmarkUpdate, db: DbSession, user: CurrentUser
) -> BookmarkResponse:
    service = BookmarkService(db)
    bookmark = await service.update(bookmark_id, user, data)
    return BookmarkResponse.model_validate(bookmark)


@router.delete("/{bookmark_id}", response_model=MessageResponse)
async def delete_bookmark(
    bookmark_id: str, db: DbSession, user: CurrentUser
) -> MessageResponse:
    service = BookmarkService(db)
    await service.delete(bookmark_id, user)
    return MessageResponse(message="Bookmark deleted")
