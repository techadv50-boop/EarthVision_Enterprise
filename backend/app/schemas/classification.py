"""Unsupervised land-cover classification schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import LegendInfo


LandCoverClass = Literal["snow", "soil", "vegetation", "water"]


class ClassAreaStat(BaseModel):
    class_id: int
    name: str
    label: str
    color: str
    pixels: int
    percent: float
    area_km2: float


class ClassificationRequest(BaseModel):
    scene_id: str
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north]"
    )
    size: int = Field(default=1024, ge=128, le=2048)
    # Fixed 4-class product; kept for API clarity
    n_classes: int = Field(default=4, ge=4, le=4)


class ClassificationResponse(BaseModel):
    scene_id: str
    algorithm: str
    classes: list[ClassAreaStat]
    total_area_km2: float
    valid_pixels: int
    bounds: list[float]
    overlay_base64: str
    legend: LegendInfo
    formula: str
    message: str
    agreement_percent: float | None = None
    metadata: dict[str, Any] | None = None
