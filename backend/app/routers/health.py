"""Health and system routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    db_kind = "sqlite" if "sqlite" in settings.database_url else "postgresql"
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        database=db_kind,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/api-info")
async def api_info() -> dict:
    """Lightweight API metadata (kept off '/' so the SPA can own the root URL)."""
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "api": settings.api_prefix,
    }
