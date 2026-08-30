"""Async database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.database.base import Base

settings = get_settings()

_engine_kwargs: dict = {
    "echo": settings.debug,
    "future": True,
}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"timeout": 30}

engine = create_async_engine(settings.database_url, **_engine_kwargs)

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
        await conn.run_sync(_ensure_postgres_columns)
        if "sqlite" in settings.database_url:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=30000")


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
    _add_if_missing("articles", "citing_works", "JSON")
    _add_if_missing("users", "access_status", "VARCHAR(32) DEFAULT 'approved'")


def _ensure_postgres_columns(sync_conn) -> None:
    dialect = sync_conn.dialect.name
    if dialect not in ("postgresql", "postgres"):
        return
    sync_conn.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS access_status VARCHAR(32) DEFAULT 'approved'"
    )
    sync_conn.exec_driver_sql(
        "UPDATE users SET access_status = 'approved' WHERE access_status IS NULL"
    )

