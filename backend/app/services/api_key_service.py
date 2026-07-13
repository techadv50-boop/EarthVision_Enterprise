"""API key management service."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.subscription import ApiKeyCreate


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    async def create(self, user: User, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        raw_key = f"ev_{secrets.token_urlsafe(32)}"
        expires_at = None
        if data.expires_days:
            expires_at = datetime.now(UTC) + timedelta(days=data.expires_days)
        api_key = ApiKey(
            user_id=user.id,
            name=data.name,
            description=data.description,
            key_prefix=raw_key[:10],
            key_hash=self._hash_key(raw_key),
            scopes=data.scopes,
            expires_at=expires_at,
            is_active=True,
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key, raw_key

    async def list_for_user(self, user: User) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke(self, key_id: str, user: User) -> None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise NotFoundError("API key not found")
        api_key.is_active = False
        await self.session.flush()

    async def resolve_user(self, raw_key: str) -> User:
        key_hash = self._hash_key(raw_key)
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise UnauthorizedError("Invalid API key")
        if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
            raise UnauthorizedError("API key expired")
        api_key.last_used_at = datetime.now(UTC)
        await self.session.flush()
        user_result = await self.session.execute(select(User).where(User.id == api_key.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            raise UnauthorizedError("API key owner inactive")
        return user
