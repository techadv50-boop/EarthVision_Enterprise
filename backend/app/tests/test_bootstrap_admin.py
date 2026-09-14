"""Bootstrap admin upsert / password reset (in-memory SQLite)."""

from __future__ import annotations

import os

import pytest

# Avoid writing into repo-root data dirs during settings bootstrap.
os.environ.setdefault("IMAGERY_CACHE_DIR", "/tmp/ev-cache")
os.environ.setdefault("IMAGERY_DIR", "/tmp/ev-imagery")
os.environ.setdefault("UPLOADS_DIR", "/tmp/ev-uploads")
os.environ.setdefault("LOGS_DIR", "/tmp/ev-logs")


@pytest.mark.asyncio
async def test_bootstrap_creates_xdgen_and_earthvision_admins_and_resets_password():
    pytest.importorskip("aiosqlite")
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.core.security import hash_password, verify_password
    from app.database.base import Base
    from app.models.subscription import Subscription  # noqa: F401
    from app.models.user import User
    from app.services.bootstrap import bootstrap_admin

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        await bootstrap_admin(session)
        await session.commit()
        emails = sorted({u.email for u in (await session.execute(select(User))).scalars()})
        assert emails == ["admin@earthvision.io", "admin@xdgen.com"]

        user = (
            await session.execute(select(User).where(User.email == "admin@xdgen.com"))
        ).scalar_one()
        user.hashed_password = hash_password("WrongOldPassword")
        await session.commit()

        await bootstrap_admin(session)
        await session.commit()
        user = (
            await session.execute(select(User).where(User.email == "admin@xdgen.com"))
        ).scalar_one()
        settings = get_settings()
        assert verify_password(settings.admin_password, user.hashed_password)
    await engine.dispose()
