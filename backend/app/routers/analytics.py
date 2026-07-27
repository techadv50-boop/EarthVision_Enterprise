"""Analytics routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.core.deps import CurrentUser
from app.core.exceptions import NotFoundError
from app.schemas.analytics import (
    IndexChangeRequest,
    IndexComputeRequest,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
)
from app.services.analytics_service import INDEX_META, AnalyticsService
from app.services.job_store import create_job, set_job_done, set_job_error
from app.services.overlay_cache import read_overlay_png

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post("/index")
async def compute_index(data: IndexComputeRequest, user: CurrentUser) -> dict:
    job_id = create_job("index")

    async def _run() -> None:
        try:
            result = await run_in_threadpool(AnalyticsService().compute_index, data)
            set_job_done(job_id, result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            set_job_error(job_id, str(exc))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "pending", "kind": "index"}


@router.post("/change")
async def index_change_detection(data: IndexChangeRequest, user: CurrentUser) -> dict:
    job_id = create_job("change")

    async def _run() -> None:
        try:
            result = await run_in_threadpool(AnalyticsService().change_detection, data)
            set_job_done(job_id, result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            set_job_error(job_id, str(exc))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "pending", "kind": "change"}


@router.post("/timeseries", response_model=TimeSeriesResponse)
async def time_series(
    data: TimeSeriesRequest, user: CurrentUser
) -> TimeSeriesResponse:
    service = AnalyticsService()
    return service.time_series(data)


@router.post("/pixel", response_model=PixelInspectResponse)
async def inspect_pixel(
    data: PixelInspectRequest, user: CurrentUser
) -> PixelInspectResponse:
    service = AnalyticsService()
    return service.inspect_pixel(data)


@router.get("/indices")
async def list_indices(user: CurrentUser) -> list[dict]:
    return [
        {
            "id": key,
            "name": meta["label"],
            "formula": meta["formula"],
            "reference": meta["ref"],
            "unit": meta["unit"],
            "default_colormap": meta.get("cmap"),
        }
        for key, meta in INDEX_META.items()
    ]


@router.get("/colormaps")
async def list_colormaps(user: CurrentUser) -> list[dict]:
    """Available color ramps for spectral index overlays."""
    return AnalyticsService().list_colormaps()


@router.get("/export/index.png")
async def export_index_png(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    colormap: str | None = None,
) -> Response:
    result = await run_in_threadpool(
        AnalyticsService().compute_index,
        IndexComputeRequest(
            index=index,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
            colormap=colormap,  # type: ignore[arg-type]
        ),
    )
    png = None
    if result.overlay_url:
        oid = result.overlay_url.rsplit("/", 1)[-1].removesuffix(".png")
        png = read_overlay_png(oid)
    if not png and result.overlay_base64:
        import base64

        png = base64.b64decode(result.overlay_base64)
    if not png:
        raise NotFoundError("Index overlay missing")

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{index}_{scene_id}.png"'
        },
    )


@router.get("/export/index.csv")
async def export_index_csv(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
) -> Response:
    result = await run_in_threadpool(
        AnalyticsService().compute_index,
        IndexComputeRequest(index=index, scene_id=scene_id),  # type: ignore[arg-type]
    )
    rows = [
        "metric,value",
        f"index,{result.index}",
        f"formula,\"{result.formula}\"",
        f"mean,{result.mean}",
        f"std,{result.std}",
        f"min,{result.min}",
        f"max,{result.max}",
        f"median,{result.median}",
        f"p25,{result.percentile_25}",
        f"p75,{result.percentile_75}",
        f"valid_pixels,{result.valid_pixels}",
    ]
    return Response(
        content="\n".join(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{index}_{scene_id}_stats.csv"'
        },
    )
