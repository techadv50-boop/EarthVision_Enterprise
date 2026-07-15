"""Object / domain detection schemas for Light Explorer toolbox tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import LegendInfo


# AI Detection · Maritime · Air Domain (snake_case ids matching UI labels)
DetectionTask = Literal[
    # AI Detection
    "building_detection",
    "road_extraction",
    "vehicle_detection",
    "change_detection",
    "flood_detection",
    "land_cover_classification",
    "object_detection",
    "deforestation_detection",
    "fire_detection",
    "crop_classification",
    # Maritime
    "ship_detection",
    "vessel_tracking",
    "oil_spill_detection",
    "wake_detection",
    "port_activity_monitoring",
    "dark_vessel_detection",
    "maritime_domain_awareness",
    # Air Domain
    "aircraft_detection",
    "airport_detection",
    "runway_extraction",
    "airfield_monitoring",
    "helicopter_detection",
    "uav_detection",
]


class DetectionRunRequest(BaseModel):
    task: str = Field(description="Detection task id (snake_case)")
    bbox: list[float] = Field(description="[west, south, east, north]")
    scene_id: str | None = None
    aoi: dict[str, Any] | None = None
    confidence_min: float = Field(default=0.5, ge=0.0, le=1.0)


class DetectionRunResponse(BaseModel):
    task: str
    bounds: list[float]
    overlay_base64: str | None = None
    geojson: dict[str, Any]
    count: int
    legend: LegendInfo | None = None
    message: str
    formula: str = "task-specific EO detector (OpenCV CV + scikit-learn ML)"
