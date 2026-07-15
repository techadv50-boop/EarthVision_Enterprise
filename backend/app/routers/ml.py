"""Machine learning routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.ml import (
    ChangeDetectionRequest,
    ChangeDetectionResponse,
    MLPredictRequest,
    MLPredictResponse,
    MLTrainRequest,
    MLTrainResponse,
)
from app.services.ml_service import MLService

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


@router.post("/train", response_model=MLTrainResponse)
async def train_model(data: MLTrainRequest, user: CurrentUser) -> MLTrainResponse:
    service = MLService()
    return service.train(data)


@router.post("/predict", response_model=MLPredictResponse)
async def predict(data: MLPredictRequest, user: CurrentUser) -> MLPredictResponse:
    service = MLService()
    return service.predict(data)


@router.post("/change-detection", response_model=ChangeDetectionResponse)
async def change_detection(
    data: ChangeDetectionRequest, user: CurrentUser
) -> ChangeDetectionResponse:
    service = MLService()
    return service.change_detection(data)


@router.get("/demo-dataset")
async def demo_dataset(
    user: CurrentUser, n_samples: int = 500, n_features: int = 6, n_classes: int = 5
) -> dict:
    service = MLService()
    features, labels = service.generate_demo_training_data(n_samples, n_features, n_classes)
    return {"features": features, "labels": labels, "n_classes": n_classes}
