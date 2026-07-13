"""Remote sensing analytics schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


IndexName = Literal["NDVI", "NDWI", "NDBI", "SAVI", "BSI", "LST", "EVI", "NDMI", "NBR"]


class ColormapStop(BaseModel):
    value: float
    color: str  # #RRGGBB


class LegendInfo(BaseModel):
    min: float
    max: float
    unit: str
    label: str
    formula: str
    stops: list[ColormapStop]


class IndexComputeRequest(BaseModel):
    index: IndexName
    red_band_path: str | None = None
    nir_band_path: str | None = None
    green_band_path: str | None = None
    swir_band_path: str | None = None
    thermal_band_path: str | None = None
    scene_id: str | None = None
    aoi: dict[str, Any] | None = None
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north] for map overlay"
    )
    L: float = Field(default=0.5, description="SAVI soil-brightness factor (Huete 1988)")


class IndexComputeResponse(BaseModel):
    index: IndexName
    mean: float
    std: float
    min: float
    max: float
    median: float
    percentile_25: float
    percentile_75: float
    valid_pixels: int
    histogram: dict[str, list[float]]
    preview_base64: str | None = None
    overlay_base64: str | None = None
    bounds: list[float] | None = None  # [west, south, east, north]
    legend: LegendInfo | None = None
    formula: str | None = None
    output_path: str | None = None


class IndexChangeRequest(BaseModel):
    before_scene_id: str
    after_scene_id: str
    index: IndexName = "NDVI"
    bbox: list[float] | None = None
    threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    L: float = 0.5


class IndexChangeResponse(BaseModel):
    index: IndexName
    before_scene_id: str
    after_scene_id: str
    mean_before: float
    mean_after: float
    mean_difference: float
    change_ratio: float
    significant_pixels: int
    overlay_base64: str
    bounds: list[float]
    legend: LegendInfo
    formula: str


class TimeSeriesRequest(BaseModel):
    index: IndexName
    scene_ids: list[str] = Field(min_length=2)
    aoi: dict[str, Any] | None = None
    point: list[float] | None = Field(default=None, description="[lon, lat]")


class TimeSeriesPoint(BaseModel):
    date: str
    value: float
    scene_id: str


class TimeSeriesResponse(BaseModel):
    index: IndexName
    points: list[TimeSeriesPoint]
    trend_slope: float
    trend_intercept: float


class PixelInspectRequest(BaseModel):
    longitude: float
    latitude: float
    scene_id: str | None = None
    raster_path: str | None = None


class PixelInspectResponse(BaseModel):
    longitude: float
    latitude: float
    values: dict[str, float]
    indices: dict[str, float] | None = None


class SceneOverlayRequest(BaseModel):
    scene_id: str
    collection: str | None = None
    bbox: list[float] | None = None
    footprint: dict[str, Any] | None = None
