"""Satellite catalog search and scene routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import CurrentUser, DbSession
from app.schemas.catalog import (
    CatalogSearchRequest,
    CatalogSearchResponse,
    SceneDownloadRequest,
    SceneDownloadResponse,
)
from app.services.copernicus_service import CopernicusCatalogService
from app.services.scene_service import SceneService
from app.services.analytics_service import AnalyticsService
from pydantic import BaseModel, Field
from typing import Any

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.post("/search", response_model=CatalogSearchResponse)
async def search_catalog(
    data: CatalogSearchRequest,
    db: DbSession,
    user: CurrentUser,
) -> CatalogSearchResponse:
    catalog = CopernicusCatalogService()
    scenes, total = await catalog.search(data)
    scene_service = SceneService(db)
    for scene in scenes:
        await scene_service.upsert_from_summary(scene)
    return CatalogSearchResponse(
        total=total,
        items=scenes,
        query=data.model_dump(mode="json"),
    )


@router.get("/auth-status")
async def catalog_auth_status(user: CurrentUser) -> dict:
    catalog = CopernicusCatalogService()
    return await catalog.auth_status()


@router.post("/download", response_model=SceneDownloadResponse)
async def download_scene(
    data: SceneDownloadRequest, db: DbSession, user: CurrentUser
) -> SceneDownloadResponse:
    service = SceneService(db)
    result = await service.request_download(data.scene_id, data.collection)
    return SceneDownloadResponse(**result)


@router.get("/scenes")
async def list_scenes(
    db: DbSession,
    user: CurrentUser,
    collection: str | None = None,
    limit: int = 50,
) -> list[dict]:
    service = SceneService(db)
    scenes = await service.list_cached(collection=collection, limit=limit)
    return [
        {
            "id": s.id,
            "external_id": s.external_id,
            "collection": s.collection,
            "title": s.title,
            "sensing_time": s.sensing_time.isoformat() if s.sensing_time else None,
            "cloud_cover": s.cloud_cover,
            "footprint": s.footprint,
            "center": [s.center_lon, s.center_lat] if s.center_lon else None,
            "status": s.status,
            "local_path": s.local_path,
        }
        for s in scenes
    ]


@router.get("/scenes/{scene_id}/preview")
async def scene_preview(scene_id: str, db: DbSession, user: CurrentUser) -> Response:
    service = SceneService(db)
    # Ensure scene exists or still generate preview
    try:
        await service.get(scene_id)
    except Exception:
        pass
    png = service.get_preview_placeholder(scene_id)
    return Response(content=png, media_type="image/png")



class SceneOverlayBody(BaseModel):
    scene_id: str
    collection: str | None = None
    bbox: list[float] | None = None
    footprint: dict[str, Any] | None = None


@router.post("/scenes/overlay")
async def scene_map_overlay(data: SceneOverlayBody, user: CurrentUser) -> dict:
    """Return a georeferenced true-color PNG for Leaflet ImageOverlay."""
    service = AnalyticsService()
    return service.truecolor_overlay(
        data.scene_id,
        bbox=data.bbox,
        footprint=data.footprint,
    )


@router.get("/scenes/{scene_id}/overlay.png")
async def scene_overlay_png(
    scene_id: str,
    user: CurrentUser,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
) -> Response:
    service = AnalyticsService()
    bbox = None
    if None not in (west, south, east, north):
        bbox = [west, south, east, north]  # type: ignore[list-item]
    result = service.truecolor_overlay(scene_id, bbox=bbox)
    import base64

    return Response(
        content=base64.b64decode(result["overlay_base64"]),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="scene_{scene_id}.png"'},
    )
