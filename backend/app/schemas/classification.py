"""Unsupervised land-cover classification schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.analytics import LegendInfo


LandCoverClass = Literal[
    "snow",
    "bare_soil",
    "built_up",
    "vegetation",
    "water",
    "roads",
    "cropland",
    "wetland",
]


class ClassStyle(BaseModel):
    """User-assigned label/color for one semantic class."""

    name: str = Field(
        ...,
        description="snow|bare_soil|built_up|vegetation|water|roads|cropland|wetland",
    )
    label: str | None = None
    color: str | None = Field(
        default=None, description="Hex color #RRGGBB (user choice)"
    )
    class_id: int | None = None

    @field_validator("color")
    @classmethod
    def _valid_hex(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        s = v.strip()
        if not s.startswith("#"):
            s = f"#{s}"
        if len(s) != 7:
            raise ValueError("color must be #RRGGBB")
        int(s[1:], 16)
        return s.upper()

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: str) -> str:
        return v.strip().lower().replace(" ", "_").replace("-", "_")


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
    size: int = Field(default=512, ge=64, le=640)
    # 3–8 semantic classes (collapsed from the full 8-class taxonomy)
    n_classes: int = Field(default=6, ge=3, le=8)
    # Optional user color/label overrides keyed by class name
    class_styles: list[ClassStyle] | None = None


class ClassificationResponse(BaseModel):
    scene_id: str
    algorithm: str
    classes: list[ClassAreaStat]
    total_area_km2: float
    valid_pixels: int
    bounds: list[float]
    overlay_base64: str
    # Single-band PNG (mode L): pixel value = class_id, 255 = nodata.
    # Used to recolor the map after classification without re-running.
    class_map_base64: str | None = None
    legend: LegendInfo
    formula: str
    message: str
    agreement_percent: float | None = None
    metadata: dict[str, Any] | None = None


class RecolorRequest(BaseModel):
    """Apply new colors to an existing class map (no reclassification)."""

    class_map_base64: str
    classes: list[ClassStyle] = Field(
        ..., description="class_id + color (+ optional label/name)"
    )


class RecolorResponse(BaseModel):
    overlay_base64: str
    classes: list[ClassStyle]
    legend: LegendInfo
    message: str
