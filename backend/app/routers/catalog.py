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
    """Prepare Sentinel-2 / Landsat / S1 tiles and return map layer metadata.

    Keep this response fast for Serveo (~5s proxy limit): STAC match only, then
    warm tiles/preview in the background. S1 uses the STAC thumbnail for an
    immediate ImageOverlay while XYZ tiles fill in.
    """
    from functools import partial

    from starlette.concurrency import run_in_threadpool

    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    layer = await run_in_threadpool(
        partial(
            imagery.prepare_scene_layer,
            data.scene_id,
            bbox=data.bbox,
            footprint=data.footprint,
            sensing_time=data.sensing_time,
            cloud_cover=data.cloud_cover,
            collection=data.collection,
        )
    )

    preview_url = None
    # S1: cache remote thumbnail quickly (<1s) so eye-on shows something immediately
    if layer.get("source") == "sentinel1_grd" and layer.get("thumbnail_url"):
        preview_url = await run_in_threadpool(
            imagery.cache_remote_preview, data.scene_id, layer.get("thumbnail_url"), 256
        )
    elif imagery._preview_cache_path(data.scene_id, 384).exists():
        preview_url = f"/api/v1/catalog/scenes/{data.scene_id}/overlay.png"

    # Background: tile prewarm + optical preview (must not block Serveo response)
    try:
        import asyncio

        async def _warm() -> None:
            try:
                await run_in_threadpool(imagery.prewarm_center_tiles, data.scene_id, 9, 1)
            except Exception:  # noqa: BLE001
                pass
            if layer.get("source") != "sentinel1_grd":
                try:
                    await run_in_threadpool(imagery.ensure_preview, data.scene_id, 384)
                except Exception:  # noqa: BLE001
                    pass

        asyncio.create_task(_warm())
    except Exception:  # noqa: BLE001
        pass

    download_url = f"/api/v1/catalog/scenes/{data.scene_id}/overlay.png"
    return {
        "scene_id": data.scene_id,
        "bounds": layer["bounds"],
        "tile_url": layer["tile_url_template"],
        "preview_url": preview_url,
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
        "download_url": download_url,
    }


@router.get("/scenes/{scene_id}/tiles/{z}/{x}/{y}.png")
async def scene_tile_png(scene_id: str, z: int, x: int, y: int) -> Response:
    """XYZ tile from the scene COG (no auth — used by Leaflet). Runs in a thread pool
    so concurrent tile bursts (Landsat especially) do not serialize on the event loop.
    """
    from starlette.concurrency import run_in_threadpool

    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    png = await run_in_threadpool(imagery.render_tile, scene_id, z, x, y)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/scenes/{scene_id}/overlay.png")
async def scene_overlay_png(scene_id: str) -> Response:
    """Full-scene preview PNG for Leaflet ImageOverlay (no auth — same as XYZ tiles)."""
    from starlette.concurrency import run_in_threadpool

    from app.services.scene_imagery_service import SceneImageryService

    imagery = SceneImageryService()
    # Prefer already-cached sizes (including tiny S1 thumbnails)
    for size in (256, 160, 384, 512):
        path = imagery._preview_cache_path(scene_id, size)
        if path.exists() and path.stat().st_size > 0:
            return Response(
                content=path.read_bytes(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    layer = imagery.get_layer(scene_id)
    if layer and layer.get("source") == "sentinel1_grd" and layer.get("thumbnail_url"):
        url = await run_in_threadpool(
            imagery.cache_remote_preview, scene_id, layer.get("thumbnail_url"), 256
        )
        if url:
            png = imagery._preview_cache_path(scene_id, 256).read_bytes()
            return Response(
                content=png,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    png = await run_in_threadpool(imagery.ensure_preview, scene_id, 384)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
