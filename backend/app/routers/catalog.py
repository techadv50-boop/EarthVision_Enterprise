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
    sensing_time: str | None = None
    cloud_cover: float | None = None


@router.post("/scenes/overlay")
async def scene_map_overlay(data: SceneOverlayBody, user: CurrentUser) -> dict:
    """Prepare Sentinel-2 true-color (TCI) tiles for a scene and return map layer metadata.

    Uses real Sentinel-2 L2A visual COGs (B04/B03/B02) served as XYZ tiles so
    features stay sharp when zooming — not a low-res basemap PNG.
    """
    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    layer = imagery.prepare_scene_layer(
        data.scene_id,
        bbox=data.bbox,
        footprint=data.footprint,
        sensing_time=data.sensing_time,
        cloud_cover=data.cloud_cover,
        collection=data.collection,
    )
    return {
        "scene_id": data.scene_id,
        "bounds": layer["bounds"],
        "tile_url": layer["tile_url_template"],
        "source": layer["source"],
        "composite": layer["composite"],
        "render_mode": layer.get("render_mode"),
        "bands": layer["bands"],
        "label": layer.get("label"),
        "collection": layer.get("collection"),
        "stac_id": layer.get("stac_id"),
        "acquisition_date": layer.get("acquisition_date"),
        "cloud_cover": layer.get("cloud_cover"),
        "footprint": layer.get("footprint"),
        "thumbnail_url": layer.get("thumbnail_url"),
        "content_type": "image/png",
        "overlay_base64": "",
        "download_url": f"/api/v1/catalog/scenes/{data.scene_id}/overlay.png",
    }


@router.get("/scenes/{scene_id}/tiles/{z}/{x}/{y}.png")
async def scene_tile_png(scene_id: str, z: int, x: int, y: int) -> Response:
    """XYZ tile from the scene's Sentinel-2 true-color COG (no auth — used by Leaflet)."""
    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    png = imagery.render_tile(scene_id, z, x, y)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/scenes/{scene_id}/overlay.png")
async def scene_overlay_png(
    scene_id: str,
    user: CurrentUser,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    size: int = 768,
    collection: str | None = None,
) -> Response:
    """Download a full-scene imagery PNG (true-color / SAR grayscale)."""
    from starlette.concurrency import run_in_threadpool

    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    bbox = None
    if None not in (west, south, east, north):
        bbox = [west, south, east, north]  # type: ignore[list-item]

    def _build() -> tuple[bytes, str]:
        layer = imagery.get_layer(scene_id)
        if not layer:
            layer = imagery.prepare_scene_layer(
                scene_id,
                bbox=bbox,
                collection=collection,
            )
        png = imagery.render_preview(scene_id, size=size)
        coll = (layer.get("collection") or "scene").replace(" ", "_")
        stac = (layer.get("stac_id") or scene_id)[:80]
        mode = layer.get("render_mode") or "rgb"
        suffix = "sar_gray" if mode == "grayscale" else "true_color"
        filename = f"{coll}_{stac}_{suffix}.png".replace("/", "_")
        return png, filename

    png, filename = await run_in_threadpool(_build)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )
