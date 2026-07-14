"""Machine learning service for land cover and change detection."""

from __future__ import annotations

import pickle
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.ml import (
    ChangeDetectionRequest,
    ChangeDetectionResponse,
    MLPredictRequest,
    MLPredictResponse,
    MLTrainRequest,
    MLTrainResponse,
)


class MLService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.model_dir = self.settings.imagery_dir / "models"
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def _build_model(self, request: MLTrainRequest) -> Any:
        if request.algorithm == "random_forest":
            return RandomForestClassifier(
                n_estimators=request.n_estimators,
                max_depth=request.max_depth,
                random_state=request.random_state,
                n_jobs=-1,
            )
        if request.algorithm == "svm":
            return Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "svc",
                        SVC(
                            C=request.C,
                            kernel="rbf",
                            probability=True,
                            random_state=request.random_state,
                        ),
                    ),
                ]
            )
        if request.algorithm == "deep_learning":
            return self._build_torch_mlp(request)
        raise ValidationError(f"Unknown algorithm: {request.algorithm}")

    def _build_torch_mlp(self, request: MLTrainRequest) -> Any:
        """Lightweight PyTorch MLP wrapped for sklearn-like interface.

        Falls back to scikit-learn MLPClassifier when PyTorch is unavailable.
        """
        try:
            import torch
            import torch.nn as nn
        except ImportError:
            from sklearn.neural_network import MLPClassifier

            logger.warning("PyTorch unavailable — using sklearn MLPClassifier")
            return Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "mlp",
                        MLPClassifier(
                            hidden_layer_sizes=(64, 32),
                            max_iter=300,
                            random_state=request.random_state,
                        ),
                    ),
                ]
            )

        n_features = len(request.features[0])
        n_classes = len(set(request.labels))

        class MLP(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(n_features, 64),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(64, 32),
                    nn.ReLU(),
                    nn.Linear(32, n_classes),
                )

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return self.net(x)

        class TorchWrapper:
            def __init__(self) -> None:
                self.model = MLP()
                self.classes_ = np.array(sorted(set(request.labels)))

            def fit(self, X: np.ndarray, y: np.ndarray) -> TorchWrapper:
                device = torch.device("cpu")
                self.model.to(device)
                opt = torch.optim.Adam(self.model.parameters(), lr=1e-3)
                loss_fn = nn.CrossEntropyLoss()
                # Map labels to contiguous indices
                label_map = {c: i for i, c in enumerate(self.classes_)}
                y_idx = np.array([label_map[v] for v in y])
                Xt = torch.tensor(X, dtype=torch.float32, device=device)
                yt = torch.tensor(y_idx, dtype=torch.long, device=device)
                self.model.train()
                for _ in range(80):
                    opt.zero_grad()
                    logits = self.model(Xt)
                    loss = loss_fn(logits, yt)
                    loss.backward()
                    opt.step()
                return self

            def predict(self, X: np.ndarray) -> np.ndarray:
                import torch

                self.model.eval()
                with torch.no_grad():
                    logits = self.model(torch.tensor(X, dtype=torch.float32))
                    pred_idx = logits.argmax(dim=1).numpy()
                return self.classes_[pred_idx]

            def predict_proba(self, X: np.ndarray) -> np.ndarray:
                import torch
                import torch.nn.functional as F

                self.model.eval()
                with torch.no_grad():
                    logits = self.model(torch.tensor(X, dtype=torch.float32))
                    return F.softmax(logits, dim=1).numpy()

        return TorchWrapper()

    def train(self, request: MLTrainRequest) -> MLTrainResponse:
        if len(request.features) != len(request.labels):
            raise ValidationError("features and labels length mismatch")
        X = np.array(request.features, dtype=float)
        y = np.array(request.labels, dtype=int)
        if X.ndim != 2:
            raise ValidationError("features must be a 2D array")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=request.test_size, random_state=request.random_state, stratify=y
            if len(set(y)) > 1 and min(np.bincount(y - y.min())) >= 2
            else None,
        )

        model = self._build_model(request)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        accuracy = float(accuracy_score(y_test, y_pred))
        precision = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        recall = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm = confusion_matrix(y_test, y_pred).tolist()
        report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)

        feature_importance = None
        if hasattr(model, "feature_importances_"):
            feature_importance = model.feature_importances_.astype(float).tolist()
        elif isinstance(model, Pipeline) and hasattr(model.named_steps.get("svc", None), "coef_"):
            pass

        model_id = str(uuid.uuid4())
        model_path = self.model_dir / f"{model_id}.pkl"
        with open(model_path, "wb") as fh:
            pickle.dump(
                {
                    "model": model,
                    "algorithm": request.algorithm,
                    "task": request.task,
                    "n_features": X.shape[1],
                },
                fh,
            )
        logger.info("Trained {} model {} accuracy={:.3f}", request.algorithm, model_id, accuracy)

        return MLTrainResponse(
            model_id=model_id,
            algorithm=request.algorithm,
            task=request.task,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            confusion_matrix=cm,
            class_report=report,
            feature_importance=feature_importance,
        )

    def _load_model(self, model_id: str) -> dict[str, Any]:
        path = self.model_dir / f"{model_id}.pkl"
        if not path.exists():
            raise NotFoundError("Model not found")
        with open(path, "rb") as fh:
            return pickle.load(fh)

    def predict(self, request: MLPredictRequest) -> MLPredictResponse:
        bundle = self._load_model(request.model_id)
        model = bundle["model"]
        X = np.array(request.features, dtype=float)
        if X.ndim != 2 or X.shape[1] != bundle["n_features"]:
            raise ValidationError(
                f"Expected feature dimension {bundle['n_features']}, got {X.shape}"
            )
        predictions = model.predict(X).astype(int).tolist()
        probabilities = None
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(X).astype(float).tolist()
        return MLPredictResponse(
            model_id=request.model_id,
            predictions=predictions,
            probabilities=probabilities,
        )

    def change_detection(self, request: ChangeDetectionRequest) -> ChangeDetectionResponse:
        before = np.array(request.before_values, dtype=float)
        after = np.array(request.after_values, dtype=float)
        if before.shape != after.shape:
            raise ValidationError("before_values and after_values must have same length")

        if request.method == "difference":
            delta = after - before
            mask = np.abs(delta) > request.threshold
        elif request.method == "ratio":
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = after / (before + 1e-9)
            mask = np.abs(ratio - 1.0) > request.threshold
            delta = ratio - 1.0
        else:  # normalized
            denom = np.abs(before) + np.abs(after) + 1e-9
            delta = (after - before) / denom
            mask = np.abs(delta) > request.threshold

        return ChangeDetectionResponse(
            change_mask=mask.astype(bool).tolist(),
            change_ratio=float(np.mean(mask)),
            mean_before=float(np.mean(before)),
            mean_after=float(np.mean(after)),
            mean_difference=float(np.mean(delta)),
            significant_change_pixels=int(np.sum(mask)),
        )

    def generate_demo_training_data(
        self, n_samples: int = 500, n_features: int = 6, n_classes: int = 5
    ) -> tuple[list[list[float]], list[int]]:
        """Generate synthetic spectral training samples for land cover classes."""
        rng = np.random.default_rng(42)
        # Class centroids approximating water, vegetation, urban, soil, cloud
        centroids = rng.normal(0.3, 0.2, size=(n_classes, n_features))
        centroids = np.clip(centroids, 0.05, 0.95)
        features: list[list[float]] = []
        labels: list[int] = []
        for i in range(n_samples):
            cls = i % n_classes
            sample = centroids[cls] + rng.normal(0, 0.05, n_features)
            features.append(np.clip(sample, 0, 1).tolist())
            labels.append(cls)
        return features, labels
