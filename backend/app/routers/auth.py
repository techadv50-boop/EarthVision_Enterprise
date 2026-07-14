"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.exceptions import UnauthorizedError
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserCreate
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: DbSession) -> UserResponse:
    service = UserService(db)
    user = await service.create(
        UserCreate(
            email=data.email,
            password=data.password,
            full_name=data.full_name,
            organization=data.organization,
        )
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: DbSession) -> TokenResponse:
    service = UserService(db)
    user = await service.authenticate(data.email, data.password)
    settings = get_settings()
    access = create_access_token(
        user.id, claims={"role": user.role.value, "email": user.email}
    )
    refresh = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        payload = decode_token(data.refresh_token)
    except ValueError as exc:
        raise UnauthorizedError(str(exc)) from exc
    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")
    user_id = payload.get("sub")
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found")
    settings = get_settings()
    access = create_access_token(
        user.id, claims={"role": user.role.value, "email": user.email}
    )
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: PasswordChangeRequest, user: CurrentUser, db: DbSession
) -> MessageResponse:
    service = UserService(db)
    await service.change_password(user, data.current_password, data.new_password)
    return MessageResponse(message="Password updated successfully")
