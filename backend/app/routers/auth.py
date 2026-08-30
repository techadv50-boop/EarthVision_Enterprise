"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, decode_token
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import (
    PasswordChange,
    PasswordReset,
    TokenRefresh,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = AuthService(db)
    if await service.get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    if await service.get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = await service.create_user(user_data, role_name="user", approved=False)
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        organization=user.organization,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[r.name for r in user.roles],
        access_status=user.portal_status(),
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = AuthService(db)
    user = await service.authenticate(credentials.username, credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    status_name = user.portal_status()
    if status_name == "pending":
        raise HTTPException(status_code=403, detail="Account is pending admin approval")
    if status_name == "restricted" or not user.is_active:
        raise HTTPException(status_code=403, detail="Account is restricted")
    return TokenResponse(**service.create_tokens(user))


@router.post("/reset-password")
async def reset_password(
    body: PasswordReset,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    import secrets

    settings = get_settings()
    expected = (settings.master_reset_password or "").encode()
    provided = (body.master_password or "").encode()
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid master reset password")
    service = AuthService(db)
    user = await service.reset_password_with_master(body.email, body.new_password)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"message": "Password reset successfully"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = int(payload["sub"])
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.user import Role

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.can_access_portal():
        raise HTTPException(status_code=401, detail="User not found")

    service = AuthService(db)
    return TokenResponse(**service.create_tokens(user))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        full_name=current_user.full_name,
        organization=current_user.organization,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        roles=[r.name for r in current_user.roles],
        access_status=current_user.portal_status(),
        created_at=current_user.created_at,
    )


@router.post("/change-password")
async def change_password(
    body: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.core.security import get_password_hash, verify_password

    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = get_password_hash(body.new_password)
    await db.flush()
    return {"message": "Password updated successfully"}
