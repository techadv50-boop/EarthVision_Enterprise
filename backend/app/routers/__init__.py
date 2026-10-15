"""API routers package."""

from fastapi import APIRouter

from app.routers import (
    admin_plugins,
    analytics,
    auth,
    bookmarks,
    catalog,
    classification,
    composite,
    detection,
    gis,
    health,
    ml,
    plugins,
    projects,
    raster,
    reports,
    satellites,
    subscriptions,
    terrain,
    tool_tree,
    tools_runtime,
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
    api.include_router(satellites.router)
    api.include_router(gis.router)
    api.include_router(analytics.router)
    api.include_router(classification.router)
    api.include_router(composite.router)
    api.include_router(terrain.router)
    api.include_router(detection.router)
    api.include_router(ml.router)
    api.include_router(raster.router)
    api.include_router(subscriptions.router)
    api.include_router(reports.router)
    api.include_router(tools_runtime.router)
    api.include_router(tool_tree.router)
    api.include_router(plugins.router)
    api.include_router(admin_plugins.router)
    return api
