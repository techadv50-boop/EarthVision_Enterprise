"""Async database session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.database.base import Base

settings = get_settings()

engine_kwargs: dict = {
    "echo": settings.database_echo,
    "future": True,
}

if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = settings.database_pool_size
    engine_kwargs["max_overflow"] = settings.database_max_overflow
    engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(settings.database_url, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _ensure_sqlite_columns(sync_conn) -> None:
    """Add columns introduced after initial create_all (SQLite has no auto-alter)."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "users" in tables:
        columns = {c["name"] for c in inspector.get_columns("users")}
        if "allowed_tools" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN allowed_tools JSON"))
            logger.info("Added users.allowed_tools column")
    if "satellite_providers" in tables:
        sat_cols = {c["name"] for c in inspector.get_columns("satellite_providers")}
        if "is_high_resolution" not in sat_cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE satellite_providers "
                    "ADD COLUMN is_high_resolution BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            logger.info("Added satellite_providers.is_high_resolution column")


async def init_db() -> None:
    """Create database tables and seed bootstrap data."""
    from app.models import (  # noqa: F401
        api_key,
        bookmark,
        project,
        satellite_provider,
        scene,
        subscription,
        user,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(_ensure_sqlite_columns)
    logger.info("Database tables initialized")

    from app.services.bootstrap import bootstrap_admin
    from app.services.satellite_provider_service import SatelliteProviderService

    async with AsyncSessionLocal() as session:
        await bootstrap_admin(session)
        await SatelliteProviderService(session).ensure_builtins()
        await session.commit()
