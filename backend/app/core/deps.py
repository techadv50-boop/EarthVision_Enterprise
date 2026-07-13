"""FastAPI dependency injection providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.database.session import get_db_session
from app.models.user import User, UserRole
from app.services.user_service import UserService

security = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> User:
    """Resolve the authenticated user from the Bearer token."""
    if credentials is None:
        raise UnauthorizedError("Missing authentication credentials")
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedError(str(exc)) from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token subject")
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Dependency factory enforcing role-based access."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles and user.role != UserRole.ADMIN:
            raise ForbiddenError("Insufficient permissions")
        return user

    return checker


async def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> User | None:
    """Return the current user if authenticated, otherwise None."""
    if credentials is None:
        return None
    try:
        return await get_current_user(db, credentials)
    except UnauthorizedError:
        return None


async def get_api_key_user(
    db: DbSession,
    x_api_key: Annotated[str | None, Header()] = None,
) -> User | None:
    """Authenticate via API key header when present."""
    if not x_api_key:
        return None
    from app.services.api_key_service import ApiKeyService

    service = ApiKeyService(db)
    return await service.resolve_user(x_api_key)


AsyncSessionDep = DbSession
