"""EarthVision Enterprise — FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.database.session import init_db
from app.middleware.request_logging import RequestLoggingMiddleware
from app.routers import build_api_router


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

    return app


app = create_app()
