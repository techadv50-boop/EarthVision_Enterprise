"""User administration routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_roles
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import TOOLBOX_IDS, AccountStatus, User, UserRole
from app.schemas.user import (
    AccountDecisionRequest,
    UserCreate,
    UserDetail,
    UserListResponse,
    UserUpdate,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("/toolboxes")
async def list_toolboxes(_: AdminUser) -> dict:
    """Catalog of toolbox ids admins can assign to clients."""
    return {
        "items": [
            {"id": tid, "label": tid.replace("_", " ").title()} for tid in TOOLBOX_IDS
        ]
    }


@router.get("", response_model=UserListResponse)
async def list_users(
    db: DbSession,
    _: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: UserRole | None = None,
    status: AccountStatus | None = None,
) -> UserListResponse:
    service = UserService(db)
    items, total = await service.list_users(
        page=page, page_size=page_size, role=role, status=status
    )
    return UserListResponse(
        items=[UserDetail.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserDetail, status_code=201)
async def create_user(
    data: UserCreate,
    db: DbSession,
    _: AdminUser,
) -> UserDetail:
    """Admin creates a client account (approved by default unless status is set)."""
    service = UserService(db)
    user = await service.create(data, public_registration=False)
    return UserDetail.model_validate(user)


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: str,
    db: DbSession,
    _: AdminUser,
) -> UserDetail:
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserDetail.model_validate(user)


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: str,
    data: UserUpdate,
    db: DbSession,
    current: CurrentUser,
) -> UserDetail:
    if current.role != UserRole.ADMIN and current.id != user_id:
        raise ForbiddenError("Cannot update other users")
    if current.role != UserRole.ADMIN:
        # Clients may only edit their own profile fields — never privileges.
        data.role = None
        data.is_active = None
        data.is_verified = None
        data.allowed_tools = None
        data.allowed_satellites = None
        data.account_status = None
    service = UserService(db)
    user = await service.update(user_id, data)
    return UserDetail.model_validate(user)


@router.post("/{user_id}/decision", response_model=UserDetail)
async def decide_account(
    user_id: str,
    data: AccountDecisionRequest,
    db: DbSession,
    _: AdminUser,
) -> UserDetail:
    """Approve, decline, or restrict a client account and assign services."""
    service = UserService(db)
    user = await service.decide(user_id, data)
    return UserDetail.model_validate(user)
