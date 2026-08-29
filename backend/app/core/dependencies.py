"""FastAPI dependency injection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.database.session import get_db
from app.models.subscription import APIKey
from app.models.user import Role, User

security = HTTPBearer(auto_error=False)


async def _load_user_from_token(
    db: AsyncSession,
    token: str,
    *,
    allowed_types: tuple[str, ...] = ("access",),
) -> User:
    payload = decode_token(token)
    if payload is None or payload.get("type") not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == int(user_id))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    return user


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _load_user_from_token(db, credentials.credentials, allowed_types=("access",))


async def get_current_user_tile_compatible(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[Optional[str], Query(description="JWT access or tile token for Cesium")] = None,
) -> User:
    """Authenticate via Bearer header OR ``?token=`` query param.

    Cesium UrlTemplateImageryProvider cannot send Authorization headers, so tile
    URLs should append ``?token=${access_token}`` (or a short-lived tile JWT).
    """
    raw = None
    if credentials is not None:
        raw = credentials.credentials
    elif token:
        raw = token

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated (provide Bearer header or token query param)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _load_user_from_token(db, raw, allowed_types=("access", "tile"))


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
    return current_user


async def get_api_key_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
) -> User:
    """Authenticate via X-API-Key header (SHA-256 hash lookup against APIKey model)."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    key_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if api_key.expires_at is not None:
        expires = api_key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key expired",
            )

    api_key.last_used_at = datetime.now(timezone.utc)

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == api_key.user_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key user not found or inactive",
        )

    await db.flush()
    return user


async def get_current_user_or_api_key(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
) -> User:
    """Accept either Bearer JWT or X-API-Key authentication."""
    if x_api_key:
        return await get_api_key_user(db=db, x_api_key=x_api_key)
    return await get_current_user(credentials=credentials, db=db)


async def require_citation_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Admin role sees Journals, Search, and user management. User role does not."""
    if current_user.is_citation_admin():
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin role required",
    )


def require_permission(resource: str, action: str):
    async def permission_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.is_superuser:
            return current_user
        if not current_user.has_permission(resource, action):
            # Also accept admin:all as wildcard
            if current_user.has_permission("admin", "all"):
                return current_user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action}",
            )
        return current_user

    return permission_checker
