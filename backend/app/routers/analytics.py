"""Analytics routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.schemas.analytics import (
    IndexChangeRequest,
    IndexChangeResponse,
    IndexComputeRequest,
    IndexComputeResponse,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
)
from app.services.analytics_service import INDEX_META, AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post("/index", response_model=IndexComputeResponse)
async def compute_index(
    data: IndexComputeRequest, user: CurrentUser
) -> IndexComputeResponse:
    service = AnalyticsService()
    return service.compute_index(data)


@router.post("/change", response_model=IndexChangeResponse)
async def index_change_detection(
    data: IndexChangeRequest, user: CurrentUser
) -> IndexChangeResponse:
    service = AnalyticsService()
    return service.change_detection(data)


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
        }
        for key, meta in INDEX_META.items()
    ]


@router.get("/export/index.png")
async def export_index_png(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
) -> Response:
    service = AnalyticsService()
    result = service.compute_index(
        IndexComputeRequest(
            index=index,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
        )
    )
    assert result.overlay_base64
    import base64

    return Response(
        content=base64.b64decode(result.overlay_base64),
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
    service = AnalyticsService()
    result = service.compute_index(
        IndexComputeRequest(index=index, scene_id=scene_id)  # type: ignore[arg-type]
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
