"""EarthVision Enterprise — FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.database.session import init_db
from app.middleware.request_logging import RequestLoggingMiddleware
from app.routers import build_api_router

# Production UI build (frontend/dist). Served from the API so public tunnels
# only need one port and avoid Vite's many-module 503 failures.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    logger.info("Starting {} v{}", settings.app_name, settings.app_version)
    await init_db()
    yield
    logger.info("Shutting down {}", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "EarthVision Enterprise — Commercial Earth Observation Platform. "
            "Satellite imagery search, GIS analysis, remote sensing analytics, "
            "and machine learning for geospatial intelligence."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    api = build_api_router()
    app.include_router(api, prefix=settings.api_prefix)
    # Also mount health at root for load balancers
    from app.routers import health

    app.include_router(health.router)

    if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            """Serve built SPA files; fall back to index.html for client routes."""
            # Never shadow API / docs (registered above; this is last-resort only)
            candidate = (FRONTEND_DIST / full_path).resolve()
            try:
                candidate.relative_to(FRONTEND_DIST.resolve())
            except ValueError:
                return FileResponse(FRONTEND_DIST / "index.html")
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

        logger.info("Serving frontend from {}", FRONTEND_DIST)
    else:
        logger.warning("Frontend dist not found at {}; UI not mounted", FRONTEND_DIST)

    return app


app = create_app()
