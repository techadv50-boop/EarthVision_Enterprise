"""Pydantic schemas for satellite imagery search."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SceneSearchRequest(BaseModel):
    collection: str = Field(description="SENTINEL-1, SENTINEL-2, LANDSAT, MODIS")
    start_date: datetime
    end_date: datetime
    cloud_cover_max: Optional[float] = Field(default=100.0, ge=0, le=100)
    aoi_geojson: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class SceneMetadata(BaseModel):
    scene_id: str
    collection: str
    platform: str
    acquisition_date: datetime
    cloud_cover: Optional[float] = None
    footprint_geojson: Optional[str] = None
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    metadata: dict[str, Any] = {}


class SceneSearchResponse(BaseModel):
    total: int
    scenes: list[SceneMetadata]
    offset: int
    limit: int


class SceneDownloadRequest(BaseModel):
    scene_id: str
    collection: str
    footprint_geojson: Optional[str] = None
    product_id: Optional[str] = None
    cloud_cover: Optional[float] = None
    acquisition_date: Optional[datetime] = None
    metadata: dict[str, Any] = {}


class SceneDownloadResponse(BaseModel):
    scene_id: str
    file_path: str
    file_size_bytes: int
    cached: bool


class CopernicusAuthURL(BaseModel):
    authorization_url: str


class CopernicusCallback(BaseModel):
    code: str
    state: str


class CopernicusTokenStatus(BaseModel):
    connected: bool
    expires_at: Optional[datetime] = None
