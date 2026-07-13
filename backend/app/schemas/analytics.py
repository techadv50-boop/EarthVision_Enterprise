"""Remote sensing analytics schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


IndexName = Literal["NDVI", "NDWI", "NDBI", "SAVI", "BSI", "LST"]


class IndexComputeRequest(BaseModel):
    index: IndexName
    red_band_path: str | None = None
    nir_band_path: str | None = None
    green_band_path: str | None = None
    swir_band_path: str | None = None
    thermal_band_path: str | None = None
    scene_id: str | None = None
    aoi: dict[str, Any] | None = None
    L: float = Field(default=0.5, description="SAVI soil brightness factor")


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
    output_path: str | None = None


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
