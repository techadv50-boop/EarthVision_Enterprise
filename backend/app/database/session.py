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


def _ensure_schema_columns(sync_conn) -> None:
    """Add columns introduced after initial create_all (SQLite and Postgres).

    ``create_all`` does not ALTER existing tables, so production Postgres must
    receive the same additive column fixes as SQLite.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    dialect = sync_conn.dialect.name
    is_sqlite = dialect == "sqlite"
    bool_false = "0" if is_sqlite else "false"
    json_type = "JSON" if is_sqlite else "JSONB"

    tables = set(inspector.get_table_names())
    if "users" in tables:
        columns = {c["name"] for c in inspector.get_columns("users")}
        if "allowed_tools" not in columns:
            sync_conn.execute(text(f"ALTER TABLE users ADD COLUMN allowed_tools {json_type}"))
            logger.info("Added users.allowed_tools column")
        if "allowed_satellites" not in columns:
            sync_conn.execute(
                text(f"ALTER TABLE users ADD COLUMN allowed_satellites {json_type}")
            )
            logger.info("Added users.allowed_satellites column")
        if "account_status" not in columns:
            # Existing accounts remain usable (approved). New public sign-ups use pending.
            sync_conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN account_status VARCHAR(32) "
                    f"NOT NULL DEFAULT 'approved'"
                )
            )
            logger.info("Added users.account_status column")
    if "satellite_providers" in tables:
        sat_cols = {c["name"] for c in inspector.get_columns("satellite_providers")}
        if "is_high_resolution" not in sat_cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE satellite_providers "
                    f"ADD COLUMN is_high_resolution BOOLEAN NOT NULL DEFAULT {bool_false}"
                )
            )
            logger.info("Added satellite_providers.is_high_resolution column")
        if "resolution_category" not in sat_cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE satellite_providers "
                    "ADD COLUMN resolution_category VARCHAR(32)"
                )
            )
            logger.info("Added satellite_providers.resolution_category column")
    if "tool_placements" in tables:
        place_cols = {c["name"] for c in inspector.get_columns("tool_placements")}
        if "applicable_resolutions" not in place_cols:
            sync_conn.execute(
                text(
                    f"ALTER TABLE tool_placements "
                    f"ADD COLUMN applicable_resolutions {json_type}"
                )
            )
            logger.info("Added tool_placements.applicable_resolutions column")
        if "applicable_satellites" not in place_cols:
            sync_conn.execute(
                text(
                    f"ALTER TABLE tool_placements "
                    f"ADD COLUMN applicable_satellites {json_type}"
                )
            )
            logger.info("Added tool_placements.applicable_satellites column")


# Back-compat alias for older imports / tests.
_ensure_sqlite_columns = _ensure_schema_columns


async def init_db() -> None:
    """Create database tables and seed bootstrap data."""
    from app.models import (  # noqa: F401
        api_key,
        bookmark,
        folder_repository,
        project,
        satellite_provider,
        scene,
        subscription,
        tool_tree,
        user,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive column fixes for both SQLite and Postgres (create_all is not ALTER).
        await conn.run_sync(_ensure_schema_columns)
    logger.info("Database tables initialized")

    from app.services.bootstrap import bootstrap_admin
    from app.services.satellite_provider_service import SatelliteProviderService

    async with AsyncSessionLocal() as session:
        await bootstrap_admin(session)
        await SatelliteProviderService(session).ensure_builtins()
        await session.commit()
