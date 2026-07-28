"""Band composite and histogram-stretch routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.core.deps import CurrentUser
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.composite import (
    CompositeRequest,
    CompositeResponse,
    StretchRequest,
    StretchResponse,
)
from app.services.composite_service import COMPOSITE_PRESETS, CompositeService
from app.services.job_store import create_job, get_job, set_job_done, set_job_error
from app.services.overlay_cache import read_overlay_png

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/composites")
async def list_composites(user: CurrentUser) -> list[dict]:
    return CompositeService().list_presets()


@router.get("/index-thematic")
async def list_index_thematic(user: CurrentUser) -> list[dict]:
    """Band combinations + formulas for thematic index maps."""
    return CompositeService().list_index_thematic()


@router.post("/composite")
async def render_composite(data: CompositeRequest, user: CurrentUser) -> dict[str, Any]:
    """Start composite render as a background job (avoids Serveo ~5s proxy timeout)."""
    job_id = create_job("composite")

    async def _run() -> None:
        try:
            result = await run_in_threadpool(CompositeService().render_composite, data)
            set_job_done(job_id, result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            set_job_error(job_id, str(exc))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "pending", "kind": "composite"}


@router.post("/stretch")
async def histogram_stretch(data: StretchRequest, user: CurrentUser) -> dict[str, Any]:
    job_id = create_job("stretch")

    async def _run() -> None:
        try:
            result = await run_in_threadpool(CompositeService().stretch_scene, data)
            set_job_done(job_id, result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            set_job_error(job_id, str(exc))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "pending", "kind": "stretch"}


@router.get("/jobs/{job_id}")
async def analytics_job_status(job_id: str, user: CurrentUser) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise NotFoundError("Job not found or expired")
    if job["status"] == "done":
        return {"job_id": job_id, "status": "done", "result": job["result"]}
    if job["status"] == "error":
        return {"job_id": job_id, "status": "error", "error": job.get("error") or "failed"}
    return {"job_id": job_id, "status": "pending", "kind": job.get("kind")}


@router.get("/overlays/{overlay_id}.png")
async def get_cached_overlay_png(overlay_id: str) -> Response:
    """Serve a cached analysis overlay image (no auth — used by Leaflet ImageOverlay)."""
    data = read_overlay_png(overlay_id)
    if not data:
        raise NotFoundError("Overlay image not found or expired")
    # Composites may be JPEG; indices remain PNG. Sniff magic bytes.
    if data[:3] == b"\xff\xd8\xff":
        media_type = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    else:
        media_type = "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


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
    result = await run_in_threadpool(
        CompositeService().render_composite,
        CompositeRequest(
            preset=preset,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
            size=768,
        ),
    )
    png = None
    if result.overlay_url:
        oid = result.overlay_url.rsplit("/", 1)[-1].removesuffix(".png")
        png = read_overlay_png(oid)
    if not png:
        raise NotFoundError("Composite image missing")
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{preset}_{scene_id or "aoi"}.png"'
        },
    )


@router.get("/export/stretch.png")
async def export_stretch_png(
    user: CurrentUser,
    scene_id: str | None = None,
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    p_low: float = 2.0,
    p_high: float = 98.0,
) -> Response:
    result = await run_in_threadpool(
        CompositeService().stretch_scene,
        StretchRequest(
            scene_id=scene_id,
            bbox=[west, south, east, north],
            p_low=p_low,
            p_high=p_high,
            size=768,
        ),
    )
    png = None
    if result.overlay_url:
        oid = result.overlay_url.rsplit("/", 1)[-1].removesuffix(".png")
        png = read_overlay_png(oid)
    if not png:
        raise NotFoundError("Stretch image missing")
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="stretch_{scene_id or "aoi"}.png"'
        },
    )
