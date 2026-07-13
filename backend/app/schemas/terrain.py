"""Terrain / DEM analysis schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import LegendInfo


TerrainProduct = Literal[
    "dem",
    "slope",
    "aspect",
    "hillshade",
    "contour",
    "watershed",
    "viewshed",
    "profile",
    "line_of_sight",
    "flow_direction",
    "flow_accumulation",
    "ruggedness",
    "cut_fill",
]


class TerrainComputeRequest(BaseModel):
    product: TerrainProduct
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north]"
    )
    aoi: dict[str, Any] | None = None
    size: int = Field(default=256, ge=64, le=512)
    # Contour
    contour_interval: float = Field(default=25.0, gt=0)
    # Viewshed / LOS
    observer: list[float] | None = Field(
        default=None, description="[lon, lat] observer for viewshed/LOS"
    )
    target: list[float] | None = Field(
        default=None, description="[lon, lat] target for line-of-sight"
    )
    observer_height_m: float = Field(default=1.7, ge=0)
    target_height_m: float = Field(default=1.7, ge=0)
    # Profile
    profile_line: dict[str, Any] | None = Field(
        default=None, description="GeoJSON LineString for elevation profile"
    )
    # Hillshade
    azimuth_deg: float = Field(default=315.0)
    altitude_deg: float = Field(default=45.0)


class TerrainComputeResponse(BaseModel):
    product: TerrainProduct
    bounds: list[float]
    overlay_base64: str | None = None
    legend: LegendInfo | None = None
    # Contours / drainage as GeoJSON
    geojson: dict[str, Any] | None = None
    # 3D DEM grid (row-major elevations, north→south)
    dem_grid: list[list[float]] | None = None
    dem_stats: dict[str, float] | None = None
    # Profile / LOS
    profile: list[dict[str, float]] | None = None
    line_of_sight: dict[str, Any] | None = None
    formula: str | None = None
    message: str | None = None


class BufferRequest(BaseModel):
    geometry: dict[str, Any]
    distance_meters: float = Field(gt=0, le=500_000)
    segments: int = Field(default=32, ge=8, le=128)


class BufferResponse(BaseModel):
    geometry: dict[str, Any]
    distance_meters: float
    area_sq_meters: float | None = None
    bounds: list[float]
