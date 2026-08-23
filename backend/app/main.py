"""EarthVision Enterprise - FastAPI Application Entry Point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.database.session import init_db, AsyncSessionLocal
from app.middleware import RequestLoggingMiddleware
from app.routers import admin, analytics, auth, billing, citations, geo, imagery, raster
from app.services.auth_service import AuthService

setup_logging()
logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting EarthVision Enterprise...")
    await init_db()

    async with AsyncSessionLocal() as session:
        auth_service = AuthService(session)
        await auth_service.seed_default_data()
        await session.commit()

    logger.info("Database initialized and seeded")
    yield
    logger.info("Shutting down EarthVision Enterprise...")


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-grade Earth Observation Platform combining GIS, remote sensing, and AI analytics.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(geo.router, prefix=API_PREFIX)
app.include_router(imagery.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(raster.router, prefix=API_PREFIX)
app.include_router(billing.router, prefix=API_PREFIX)
app.include_router(citations.router, prefix=API_PREFIX)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/api/config")
async def get_public_config():
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "cesium_ion_token": settings.cesium_ion_token or None,
    }
