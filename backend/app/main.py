"""SAT EYE — Offline Earth Observation Platform entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.database.session import init_db, AsyncSessionLocal
from app.middleware import RequestLoggingMiddleware
from app.routers import admin, analytics, auth, billing, geo, imagery, offline, raster
from app.services.auth_service import AuthService
from app.services.imagery_stack_service import ImageryStackService
from app.services.offline_layers_service import OfflineLayersService

setup_logging()
logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting {} (offline_mode={})...", settings.app_name, settings.offline_mode)
    await init_db()

    async with AsyncSessionLocal() as session:
        auth_service = AuthService(session)
        await auth_service.seed_default_data()
        await session.commit()

    # Seed offline basemaps, landmarks, DEM/DTM/DSM, and demo 20-date stack
    try:
        layers = OfflineLayersService()
        seed_result = layers.ensure_seed_data()
        demo = ImageryStackService().seed_demo_stack()
        logger.info(
            "Offline data ready: {} layer artifacts, demo stack images={}",
            seed_result.get("created"),
            demo.get("image_count"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Offline seed incomplete: {}", exc)

    logger.info("Database initialized and seeded")
    yield
    logger.info("Shutting down {}...", settings.app_name)


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "SAT EYE — Offline Earth Observation software for PC installation. "
        "Upload satellite imagery locally, browse multi-date stacks, run 148 GIS tools, "
        "and work with embedded basemaps, landmarks, DEM/DTM/DSM layers — no internet required."
    ),
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
app.include_router(offline.router, prefix=API_PREFIX)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "offline_mode": settings.offline_mode,
    }


@app.get("/api/config")
async def get_public_config():
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "offline_mode": settings.offline_mode,
        "cesium_ion_token": None if settings.offline_mode else (settings.cesium_ion_token or None),
        "gis_tools_count": 148,
    }
