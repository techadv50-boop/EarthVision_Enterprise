"""Satellite catalog search schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CollectionName = Literal[
    "SENTINEL-1",
    "SENTINEL-2",
    "LANDSAT-8",
    "LANDSAT-9",
    "MODIS",
]


class AOIFilter(BaseModel):
    type: Literal["Polygon", "MultiPolygon", "Point"] = "Polygon"
    coordinates: list[Any]


class CatalogSearchRequest(BaseModel):
    collections: list[CollectionName] = Field(default_factory=lambda: ["SENTINEL-2"])
    start_date: datetime | None = None
    end_date: datetime | None = None
    cloud_cover_max: float | None = Field(default=30.0, ge=0, le=100)
    aoi: AOIFilter | None = None
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north]"
    )
    max_results: int = Field(default=50, ge=1, le=500)
    product_type: str | None = None


class SceneSummary(BaseModel):
    id: str
    name: str
    collection: str
    platform: str
    sensing_time: datetime | None = None
    cloud_cover: float | None = None
    footprint: dict[str, Any] | None = None
    center: list[float] | None = None
    thumbnail_url: str | None = None
    size_bytes: int | None = None
    content_date: str | None = None
    product_type: str | None = None
    metadata: dict[str, Any] | None = None


class CatalogSearchResponse(BaseModel):
    total: int
    items: list[SceneSummary]
    query: dict[str, Any]


class SceneDownloadRequest(BaseModel):
    scene_id: str
    collection: str


class SceneDownloadResponse(BaseModel):
    scene_id: str
    status: str
    local_path: str | None = None
    download_url: str | None = None
    message: str
