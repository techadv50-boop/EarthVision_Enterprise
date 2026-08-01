"""RGB band-combination / false-color composite schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import LegendInfo


CompositePreset = Literal[
    "true_color",
    "false_color_infrared",
    "false_color_agriculture",
    "false_color_urban",
    "swir_composite",
    "geology",
    "atmospheric_penetration",
    "land_water",
    "vegetation_health",
    "burn_severity",
]


class CompositeRequest(BaseModel):
    scene_id: str | None = None
    bbox: list[float] | None = Field(default=None, description="[west,south,east,north]")
    preset: CompositePreset = "false_color_infrared"
    # Optional custom band mapping (overrides preset)
    red_band: str | None = None
    green_band: str | None = None
    blue_band: str | None = None
    size: int = Field(default=1024, ge=64, le=2048)
    stretch: Literal["percentile", "minmax", "none"] = "percentile"
    p_low: float = Field(default=1.0, ge=0, le=49)
    p_high: float = Field(default=99.0, ge=51, le=100)
    gamma: float = Field(default=1.05, gt=0.1, le=3.0)
    brightness: float = Field(default=1.0, gt=0.1, le=2.5)
    contrast: float = Field(default=1.1, gt=0.1, le=2.5)


class CompositeResponse(BaseModel):
    preset: str
    label: str
    bands: dict[str, str]  # display {R,G,B} names
    band_keys: dict[str, str]  # {R,G,B} → internal keys
    formula: str
    bounds: list[float]
    overlay_base64: str
    histogram: dict[str, Any] | None = None
    legend: LegendInfo | None = None
    message: str | None = None
    stretch: str | None = None


class StretchRequest(BaseModel):
    scene_id: str | None = None
    bbox: list[float] | None = None
    size: int = Field(default=1024, ge=64, le=2048)
    p_low: float = Field(default=1.0, ge=0, le=49)
    p_high: float = Field(default=99.0, ge=51, le=100)
    gamma: float = Field(default=1.05, gt=0.1, le=3.0)
    brightness: float = Field(default=1.0, gt=0.1, le=2.5)
    contrast: float = Field(default=1.1, gt=0.1, le=2.5)
    source: Literal["true_color", "current"] = "true_color"


class StretchResponse(BaseModel):
    bounds: list[float]
    overlay_base64: str
    histogram: dict[str, Any]
    p_low: float
    p_high: float
    gamma: float
    brightness: float
    contrast: float
    message: str
