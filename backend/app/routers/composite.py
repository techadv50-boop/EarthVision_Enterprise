"""Band composite and histogram-stretch routes."""

from __future__ import annotations

import base64

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.schemas.composite import (
    CompositeRequest,
    CompositeResponse,
    StretchRequest,
    StretchResponse,
)
from app.services.composite_service import COMPOSITE_PRESETS, CompositeService, INDEX_THEMATIC

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/composites")
async def list_composites(
    user: CurrentUser,
    collection: str | None = None,
) -> list[dict]:
    """List RGB composites; pass ``collection`` to enable/disable per satellite."""
    return CompositeService().list_presets(collection=collection)


@router.get("/index-thematic")
async def list_index_thematic(
    user: CurrentUser,
    collection: str | None = None,
) -> list[dict]:
    """Band combinations + formulas for thematic index maps (satellite-aware)."""
    return CompositeService().list_index_thematic(collection=collection)


@router.post("/composite", response_model=CompositeResponse)
async def render_composite(
    data: CompositeRequest, user: CurrentUser
) -> CompositeResponse:
    from app.core.concurrency import run_sync

    return await run_sync(CompositeService().render_composite, data)


@router.post("/stretch", response_model=StretchResponse)
async def histogram_stretch(
    data: StretchRequest, user: CurrentUser
) -> StretchResponse:
    from app.core.concurrency import run_sync

    return await run_sync(CompositeService().stretch_scene, data)


@router.get("/export/composite.png")
async def export_composite_png(
    user: CurrentUser,
    preset: str = "false_color_infrared",
    scene_id: str | None = None,
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
) -> Response:
    if preset not in COMPOSITE_PRESETS:
        preset = "false_color_infrared"
    result = CompositeService().render_composite(
        CompositeRequest(
            preset=preset,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
        )
    )
    return Response(
        content=base64.b64decode(result.overlay_base64),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{preset}_{scene_id or "aoi"}.png"'
        },
    )


@router.get("/export/composite.tif")
async def export_composite_geotiff(
    user: CurrentUser,
    preset: str = "true_color",
    scene_id: str | None = None,
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
) -> Response:
    """Download a band composite (e.g. True Color) as georeferenced GeoTIFF."""
    from app.services.geotiff_export import png_bytes_to_geotiff

    if preset not in COMPOSITE_PRESETS:
        preset = "true_color"
    result = CompositeService().render_composite(
        CompositeRequest(
            preset=preset,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
        )
    )
    tif, filename = png_bytes_to_geotiff(
        base64.b64decode(result.overlay_base64),
        list(result.bounds),
        filename=f"{preset}_{scene_id or 'aoi'}.tif",
    )
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/stretch.png")
async def export_stretch_png(
    user: CurrentUser,
    scene_id: str | None = None,
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    p_low: float = 1.0,
    p_high: float = 99.0,
) -> Response:
    result = CompositeService().stretch_scene(
        StretchRequest(
            scene_id=scene_id,
            bbox=[west, south, east, north],
            p_low=p_low,
            p_high=p_high,
            size=1024,
            gamma=1.05,
            contrast=1.1,
        )
    )
    return Response(
        content=base64.b64decode(result.overlay_base64),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="stretch_{scene_id or "aoi"}.png"'
        },
    )


@router.get("/export/stretch.tif")
async def export_stretch_geotiff(
    user: CurrentUser,
    scene_id: str | None = None,
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    p_low: float = 1.0,
    p_high: float = 99.0,
) -> Response:
    from app.services.geotiff_export import png_bytes_to_geotiff

    result = CompositeService().stretch_scene(
        StretchRequest(
            scene_id=scene_id,
            bbox=[west, south, east, north],
            p_low=p_low,
            p_high=p_high,
            size=1024,
            gamma=1.05,
            contrast=1.1,
        )
    )
    tif, filename = png_bytes_to_geotiff(
        base64.b64decode(result.overlay_base64),
        list(result.bounds),
        filename=f"stretch_{scene_id or 'aoi'}.tif",
    )
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
