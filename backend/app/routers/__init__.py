"""API routers package."""

from fastapi import APIRouter

from app.routers import (
    analytics,
    auth,
    bookmarks,
    catalog,
    detection,
    gis,
    health,
    ml,
    projects,
    raster,
    reports,
    subscriptions,
    terrain,
    users,
)


def build_api_router() -> APIRouter:
    api = APIRouter()
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(projects.router)
    api.include_router(bookmarks.router)
    api.include_router(catalog.router)
    api.include_router(gis.router)
    api.include_router(analytics.router)
    api.include_router(terrain.router)
    api.include_router(detection.router)
    api.include_router(ml.router)
    api.include_router(raster.router)
    api.include_router(subscriptions.router)
    api.include_router(reports.router)
    return api
