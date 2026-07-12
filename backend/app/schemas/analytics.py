"""Pydantic schemas for analytics and ML."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class IndexComputeRequest(BaseModel):
    index_type: str = Field(description="NDVI, NDWI, NDBI, SAVI, BSI, LST")
    scene_id: str
    collection: str
    aoi_geojson: Optional[str] = None


class IndexComputeResponse(BaseModel):
    job_id: int
    index_type: str
    status: str
    tile_url: Optional[str] = None
    statistics: Optional[dict[str, float]] = None


class TimeSeriesRequest(BaseModel):
    index_type: str
    scene_ids: list[str]
    collection: str
    aoi_geojson: Optional[str] = None


class TimeSeriesPoint(BaseModel):
    date: datetime
    value: float
    scene_id: str


class TimeSeriesResponse(BaseModel):
    index_type: str
    points: list[TimeSeriesPoint]
    statistics: dict[str, float]


class HistogramResponse(BaseModel):
    bins: list[float]
    counts: list[int]
    min_value: float
    max_value: float
    mean: float
    std: float


class MLClassificationRequest(BaseModel):
    model_type: str = Field(description="random_forest, svm, deep_learning")
    scene_id: str
    collection: str
    num_classes: int = Field(default=5, ge=2, le=20)
    aoi_geojson: Optional[str] = None
    training_samples: Optional[list[dict[str, Any]]] = None


class ChangeDetectionRequest(BaseModel):
    scene_id_before: str
    scene_id_after: str
    collection: str
    method: str = Field(default="difference", description="difference, cnn")
    aoi_geojson: Optional[str] = None


class ThematicDetectionRequest(BaseModel):
    scene_id: str
    collection: str = "SENTINEL-2"
    aoi_geojson: Optional[str] = None
    scene_id_before: Optional[str] = Field(
        default=None,
        description="Optional earlier scene for flood change detection",
    )


class AnalysisJobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    progress: float
    result_path: Optional[str] = None
    result_json: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    tile_url: Optional[str] = None

    model_config = {"from_attributes": True}


class ReportRequest(BaseModel):
    report_type: str = Field(description="pdf, excel, csv")
    title: str
    content: dict[str, Any]
