"""Machine learning schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AlgorithmName = Literal[
    "random_forest",
    "svm",
    "deep_learning",
]

TaskName = Literal[
    "land_cover",
    "change_detection",
    "flood_detection",
    "road_detection",
    "building_detection",
    "water_detection",
    "urban_growth",
]


class MLTrainRequest(BaseModel):
    algorithm: AlgorithmName
    task: TaskName
    features: list[list[float]] = Field(min_length=10)
    labels: list[int] = Field(min_length=10)
    n_estimators: int = Field(default=100, ge=10, le=1000)
    max_depth: int | None = 20
    C: float = Field(default=1.0, ge=0.01, le=100.0)
    test_size: float = Field(default=0.2, ge=0.1, le=0.5)
    random_state: int = 42


class MLTrainResponse(BaseModel):
    model_id: str
    algorithm: AlgorithmName
    task: TaskName
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: list[list[int]]
    class_report: dict[str, Any]
    feature_importance: list[float] | None = None


class MLPredictRequest(BaseModel):
    model_id: str
    features: list[list[float]]


class MLPredictResponse(BaseModel):
    model_id: str
    predictions: list[int]
    probabilities: list[list[float]] | None = None


class ChangeDetectionRequest(BaseModel):
    before_values: list[float] = Field(min_length=10)
    after_values: list[float] = Field(min_length=10)
    threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    method: Literal["difference", "ratio", "normalized"] = "normalized"


class ChangeDetectionResponse(BaseModel):
    change_mask: list[bool]
    change_ratio: float
    mean_before: float
    mean_after: float
    mean_difference: float
    significant_change_pixels: int
