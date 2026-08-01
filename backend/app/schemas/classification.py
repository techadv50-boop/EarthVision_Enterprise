"""Unsupervised land-cover classification schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.analytics import LegendInfo


LandCoverClass = Literal[
    "snow", "bare_soil", "built_up", "vegetation", "water", "roads"
]


class ClassStyle(BaseModel):
    """User-assigned label/color for one semantic class."""

    name: str = Field(..., description="snow|bare_soil|built_up|vegetation|water|roads")
    label: str | None = None
    color: str | None = Field(
        default=None, description="Hex color #RRGGBB (user choice)"
    )

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
        int(s[1:], 16)  # validate hex
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
    size: int = Field(default=1536, ge=128, le=2048)
    # 3–6 semantic classes (collapsed from the full 6-class taxonomy)
    n_classes: int = Field(default=6, ge=3, le=6)
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
    legend: LegendInfo
    formula: str
    message: str
    agreement_percent: float | None = None
    metadata: dict[str, Any] | None = None
