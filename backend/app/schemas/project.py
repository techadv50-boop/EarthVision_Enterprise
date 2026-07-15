"""Project schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    aoi_geojson: dict[str, Any] | None = None
    center_lon: float | None = None
    center_lat: float | None = None
    zoom: float | None = None
    settings: dict[str, Any] | None = None
    tags: list[str] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    aoi_geojson: dict[str, Any] | None = None
    center_lon: float | None = None
    center_lat: float | None = None
    zoom: float | None = None
    settings: dict[str, Any] | None = None
    tags: list[str] | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    status: ProjectStatus
    owner_id: str
    aoi_geojson: dict[str, Any] | None
    center_lon: float | None
    center_lat: float | None
    zoom: float | None
    settings: dict[str, Any] | None
    tags: list[str] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int
