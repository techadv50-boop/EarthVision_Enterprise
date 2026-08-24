"""Async database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.database.base import Base

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_sqlite_columns)


def _ensure_sqlite_columns(sync_conn) -> None:
    """Add newly introduced columns on existing SQLite DBs (create_all won't alter)."""
    dialect = sync_conn.dialect.name
    if dialect != "sqlite":
        return

    def _add_if_missing(table: str, column: str, ddl_type: str) -> None:
        rows = sync_conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
            )

    _add_if_missing("copernicus_tokens", "oauth_state", "VARCHAR(128)")
    _add_if_missing("copernicus_tokens", "oauth_state_expires_at", "DATETIME")
    _add_if_missing("crawl_jobs", "pages_crawled", "INTEGER DEFAULT 0")
    _add_if_missing("crawl_jobs", "phase", "VARCHAR(32)")
    _add_if_missing("crawl_jobs", "message", "VARCHAR(500)")
    _add_if_missing("crawl_jobs", "inventory", "JSON")

