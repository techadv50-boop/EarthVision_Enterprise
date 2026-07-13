"""Analytics routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.analytics import (
    IndexComputeRequest,
    IndexComputeResponse,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post("/index", response_model=IndexComputeResponse)
async def compute_index(
    data: IndexComputeRequest, user: CurrentUser
) -> IndexComputeResponse:
    service = AnalyticsService()
    return service.compute_index(data)


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
        {"id": "NDVI", "name": "Normalized Difference Vegetation Index", "formula": "(NIR-RED)/(NIR+RED)"},
        {"id": "NDWI", "name": "Normalized Difference Water Index", "formula": "(GREEN-NIR)/(GREEN+NIR)"},
        {"id": "NDBI", "name": "Normalized Difference Built-up Index", "formula": "(SWIR-NIR)/(SWIR+NIR)"},
        {"id": "SAVI", "name": "Soil Adjusted Vegetation Index", "formula": "((NIR-RED)*(1+L))/(NIR+RED+L)"},
        {"id": "BSI", "name": "Bare Soil Index", "formula": "((SWIR+RED)-(NIR+GREEN))/((SWIR+RED)+(NIR+GREEN))"},
        {"id": "LST", "name": "Land Surface Temperature", "formula": "Planck inversion of thermal band"},
    ]
