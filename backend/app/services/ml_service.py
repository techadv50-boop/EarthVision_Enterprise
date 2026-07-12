"""Machine learning classification and change detection service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.analysis import AnalysisJob
from app.schemas.analytics import (
    ChangeDetectionRequest,
    MLClassificationRequest,
    ThematicDetectionRequest,
)
from app.services.raster_service import RasterService
from app.services.scene_service import SceneService


class MLService:
    # Class labels used by thematic helpers
    CLASS_BACKGROUND = 0
    CLASS_WATER = 1
    CLASS_VEGETATION = 2
    CLASS_URBAN = 3
    CLASS_BARE = 4
    CLASS_FLOOD = 5

    def __init__(self, db: AsyncSession):
        self.db = db
        self.raster = RasterService()
        self.scene = SceneService(db)
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def _extract_features(self, bands: np.ndarray) -> tuple[np.ndarray, int, int]:
        """
        Build per-pixel feature vectors from multi-band imagery.

        Features: raw bands + NDVI, NDWI, NDBI, BSI + local texture (3x3 std of NDVI).
        """
        n_bands, height, width = bands.shape
        eps = 1e-10

        if n_bands >= 6:
            blue, green, red, nir, swir1, swir2 = [bands[i].astype(float) for i in range(6)]
        elif n_bands >= 4:
            blue, green, red, nir = [bands[i].astype(float) for i in range(4)]
            swir1, swir2 = red.copy(), blue.copy()
        else:
            red = bands[0].astype(float)
            green = bands[min(1, n_bands - 1)].astype(float)
            blue = bands[min(2, n_bands - 1)].astype(float)
            nir = red
            swir1, swir2 = green, blue

        ndvi = (nir - red) / (nir + red + eps)
        ndwi = (green - nir) / (green + nir + eps)
        ndbi = (swir1 - nir) / (swir1 + nir + eps)
        bsi = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue) + eps)

        # Local texture: 3x3 rolling std of NDVI via convolution-style pad
        padded = np.pad(ndvi, 1, mode="edge")
        texture = np.zeros_like(ndvi)
        for i in range(3):
            for j in range(3):
                texture += padded[i : i + height, j : j + width]
        mean_local = texture / 9.0
        var = np.zeros_like(ndvi)
        for i in range(3):
            for j in range(3):
                diff = padded[i : i + height, j : j + width] - mean_local
                var += diff * diff
        texture_std = np.sqrt(var / 9.0)

        feature_stack = [
            blue, green, red, nir, swir1, swir2,
            ndvi, ndwi, ndbi, bsi, texture_std,
        ]
        # Keep only finite
        stacked = np.stack(feature_stack, axis=0)
        features = stacked.reshape(stacked.shape[0], -1).T
        features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        return features, height, width

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    async def classify(
        self, user_id: int, request: MLClassificationRequest
    ) -> AnalysisJob:
        job = AnalysisJob(
            user_id=user_id,
            job_type=f"ml_{request.model_type}",
            status="processing",
            parameters=json.dumps(request.model_dump()),
            progress=0.1,
        )
        self.db.add(job)
        await self.db.flush()

        try:
            download = await self.scene.download_scene(
                user_id, request.scene_id, request.collection
            )
            job.progress = 0.3

            import rasterio

            with rasterio.open(download.file_path) as src:
                if request.aoi_geojson:
                    bands_dict, profile = self.raster._read_bands(src, request.aoi_geojson)
                    band_list = [
                        bands_dict["blue"],
                        bands_dict["green"],
                        bands_dict["red"],
                        bands_dict["nir"],
                        bands_dict["swir1"],
                        bands_dict["swir2"],
                    ]
                    bands = np.stack(band_list, axis=0)
                else:
                    bands = src.read().astype(float)

            features, height, width = self._extract_features(bands)
            job.progress = 0.5

            if request.model_type == "random_forest":
                result = self._random_forest_classify(features, request.num_classes)
            elif request.model_type == "svm":
                result = self._svm_classify(features, request.num_classes)
            elif request.model_type == "deep_learning":
                result = self._deep_learning_classify(features, request.num_classes)
            else:
                raise ValueError(f"Unknown model type: {request.model_type}")

            classification = result.reshape(height, width)
            output_path = self._save_classification(classification, download.file_path, job.id)

            class_counts = {
                f"class_{cls}": int(np.sum(classification == cls))
                for cls in range(request.num_classes)
            }

            job.status = "completed"
            job.progress = 1.0
            job.result_path = output_path
            job.result_json = json.dumps(
                {"class_counts": class_counts, "num_classes": request.num_classes}
            )
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return job

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise

    # ------------------------------------------------------------------
    # Change detection
    # ------------------------------------------------------------------

    async def change_detection(
        self, user_id: int, request: ChangeDetectionRequest
    ) -> AnalysisJob:
        job = AnalysisJob(
            user_id=user_id,
            job_type=f"change_{request.method}",
            status="processing",
            parameters=json.dumps(request.model_dump()),
            progress=0.1,
        )
        self.db.add(job)
        await self.db.flush()

        try:
            before = await self.scene.download_scene(
                user_id, request.scene_id_before, request.collection
            )
            after = await self.scene.download_scene(
                user_id, request.scene_id_after, request.collection
            )
            job.progress = 0.4

            ndvi_before, _ = self.raster.compute_index(
                before.file_path, "NDVI", aoi_geojson=request.aoi_geojson
            )
            ndvi_after, _ = self.raster.compute_index(
                after.file_path, "NDVI", aoi_geojson=request.aoi_geojson
            )

            # Align shapes if AOI / raster sizes differ slightly
            h = min(ndvi_before.shape[0], ndvi_after.shape[0])
            w = min(ndvi_before.shape[1], ndvi_after.shape[1])
            ndvi_before = ndvi_before[:h, :w]
            ndvi_after = ndvi_after[:h, :w]

            if request.method == "difference":
                change_mask = self._ndvi_difference_change(ndvi_before, ndvi_after)
            else:
                change_mask = self._cnn_change_detection(ndvi_before, ndvi_after)
                change_mask = self._morphological_cleanup(change_mask)

            output_path = self._save_classification(change_mask, before.file_path, job.id)

            changed_pixels = int(np.sum(change_mask > 0))
            total_pixels = int(change_mask.size)

            job.status = "completed"
            job.progress = 1.0
            job.result_path = output_path
            job.result_json = json.dumps(
                {
                    "changed_pixels": changed_pixels,
                    "total_pixels": total_pixels,
                    "change_percentage": round(changed_pixels / max(total_pixels, 1) * 100, 2),
                    "mean_ndvi_before": float(np.nanmean(ndvi_before)),
                    "mean_ndvi_after": float(np.nanmean(ndvi_after)),
                }
            )
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return job

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise

    def _ndvi_difference_change(
        self, before: np.ndarray, after: np.ndarray, threshold: Optional[float] = None
    ) -> np.ndarray:
        """Absolute NDVI differencing with adaptive threshold and morphological cleanup."""
        diff = np.abs(after.astype(float) - before.astype(float))
        valid = diff[np.isfinite(diff)]
        if threshold is None:
            if valid.size:
                threshold = float(np.mean(valid) + 1.5 * np.std(valid))
                threshold = max(threshold, 0.08)
            else:
                threshold = 0.1
        mask = (diff > threshold).astype(np.uint8)
        return self._morphological_cleanup(mask)

    def _morphological_cleanup(self, mask: np.ndarray, iterations: int = 1) -> np.ndarray:
        """Binary open then close using a 3x3 structuring element (no scipy required)."""
        binary = (mask > 0).astype(np.uint8)

        def erode(m: np.ndarray) -> np.ndarray:
            padded = np.pad(m, 1, mode="constant", constant_values=0)
            out = np.ones_like(m, dtype=np.uint8)
            for i in range(3):
                for j in range(3):
                    out = out & padded[i : i + m.shape[0], j : j + m.shape[1]]
            return out

        def dilate(m: np.ndarray) -> np.ndarray:
            padded = np.pad(m, 1, mode="constant", constant_values=0)
            out = np.zeros_like(m, dtype=np.uint8)
            for i in range(3):
                for j in range(3):
                    out = out | padded[i : i + m.shape[0], j : j + m.shape[1]]
            return out

        result = binary
        for _ in range(iterations):
            result = dilate(erode(result))  # open
            result = erode(dilate(result))  # close
        return result.astype(np.uint8)

    # ------------------------------------------------------------------
    # Thematic detection helpers
    # ------------------------------------------------------------------

    def detect_water(self, file_path: str, aoi_geojson: Optional[str] = None) -> np.ndarray:
        """Return binary water map using NDWI threshold."""
        ndwi, _ = self.raster.compute_index(file_path, "NDWI", aoi_geojson=aoi_geojson)
        water = (ndwi > 0.15).astype(np.uint8)
        return self._morphological_cleanup(water)

    def detect_urban(self, file_path: str, aoi_geojson: Optional[str] = None) -> np.ndarray:
        """Return binary urban/built-up map using NDBI threshold."""
        ndbi, _ = self.raster.compute_index(file_path, "NDBI", aoi_geojson=aoi_geojson)
        ndvi, _ = self.raster.compute_index(file_path, "NDVI", aoi_geojson=aoi_geojson)
        urban = ((ndbi > 0.05) & (ndvi < 0.3)).astype(np.uint8)
        return self._morphological_cleanup(urban)

    def detect_building(self, file_path: str, aoi_geojson: Optional[str] = None) -> np.ndarray:
        """Binary building footprint proxy from NDBI + low NDVI + local texture."""
        ndbi, _ = self.raster.compute_index(file_path, "NDBI", aoi_geojson=aoi_geojson)
        ndvi, _ = self.raster.compute_index(file_path, "NDVI", aoi_geojson=aoi_geojson)
        # High NDBI, low vegetation, elevated local contrast on NDBI
        padded = np.pad(ndbi, 1, mode="edge")
        texture = np.zeros_like(ndbi)
        for i in range(3):
            for j in range(3):
                texture += padded[i : i + ndbi.shape[0], j : j + ndbi.shape[1]]
        mean_local = texture / 9.0
        var = np.zeros_like(ndbi)
        for i in range(3):
            for j in range(3):
                diff = padded[i : i + ndbi.shape[0], j : j + ndbi.shape[1]] - mean_local
                var += diff * diff
        texture_std = np.sqrt(var / 9.0)
        buildings = (
            (ndbi > 0.08) & (ndvi < 0.25) & (texture_std > float(np.nanpercentile(texture_std, 55)))
        ).astype(np.uint8)
        return self._morphological_cleanup(buildings)

    def detect_road(self, file_path: str, aoi_geojson: Optional[str] = None) -> np.ndarray:
        """Binary road proxy: bare/impervious corridors with elongated morphology."""
        ndvi, _ = self.raster.compute_index(file_path, "NDVI", aoi_geojson=aoi_geojson)
        ndbi, _ = self.raster.compute_index(file_path, "NDBI", aoi_geojson=aoi_geojson)
        ndwi, _ = self.raster.compute_index(file_path, "NDWI", aoi_geojson=aoi_geojson)
        # Impervious, non-vegetated, non-water
        candidate = ((ndvi < 0.2) & (ndbi > -0.05) & (ndwi < 0.1)).astype(np.uint8)
        # Prefer thin linear features via open then subtract thick blobs
        opened = self._morphological_cleanup(candidate, iterations=1)
        # Keep moderately textured corridors
        padded = np.pad(ndvi.astype(float), 1, mode="edge")
        local_std = np.zeros_like(ndvi, dtype=float)
        mean = np.zeros_like(ndvi, dtype=float)
        for i in range(3):
            for j in range(3):
                mean += padded[i : i + ndvi.shape[0], j : j + ndvi.shape[1]]
        mean /= 9.0
        for i in range(3):
            for j in range(3):
                diff = padded[i : i + ndvi.shape[0], j : j + ndvi.shape[1]] - mean
                local_std += diff * diff
        local_std = np.sqrt(local_std / 9.0)
        roads = ((opened > 0) & (local_std > float(np.nanpercentile(local_std, 40)))).astype(np.uint8)
        return self._morphological_cleanup(roads)

    def detect_flood(
        self,
        before_path: str,
        after_path: str,
        aoi_geojson: Optional[str] = None,
    ) -> np.ndarray:
        """
        Flood detection: water present after but not before (NDWI increase).

        Returns a class map: 0=background, 1=permanent water, 5=flood.
        """
        ndwi_b, _ = self.raster.compute_index(before_path, "NDWI", aoi_geojson=aoi_geojson)
        ndwi_a, _ = self.raster.compute_index(after_path, "NDWI", aoi_geojson=aoi_geojson)
        h = min(ndwi_b.shape[0], ndwi_a.shape[0])
        w = min(ndwi_b.shape[1], ndwi_a.shape[1])
        ndwi_b = ndwi_b[:h, :w]
        ndwi_a = ndwi_a[:h, :w]

        water_before = ndwi_b > 0.15
        water_after = ndwi_a > 0.15
        permanent = water_before & water_after
        flood = (~water_before) & water_after & ((ndwi_a - ndwi_b) > 0.12)

        # Restore class values after binary cleanup on flood only
        cleaned_flood = self._morphological_cleanup(flood.astype(np.uint8))
        cleaned_perm = self._morphological_cleanup(permanent.astype(np.uint8))
        class_map = np.zeros((h, w), dtype=np.uint8)
        class_map[cleaned_perm > 0] = self.CLASS_WATER
        class_map[cleaned_flood > 0] = self.CLASS_FLOOD
        return class_map

    def detect_flood_single(
        self, file_path: str, aoi_geojson: Optional[str] = None
    ) -> np.ndarray:
        """Single-scene inundation proxy: strong NDWI water mask labeled as flood."""
        water = self.detect_water(file_path, aoi_geojson=aoi_geojson)
        class_map = np.zeros_like(water, dtype=np.uint8)
        class_map[water > 0] = self.CLASS_FLOOD
        return class_map

    async def run_thematic_detection(
        self,
        user_id: int,
        detection_type: str,
        request: ThematicDetectionRequest,
    ) -> AnalysisJob:
        """Download scene(s), run thematic detector, write result raster."""
        job = AnalysisJob(
            user_id=user_id,
            job_type=f"detect_{detection_type}",
            status="processing",
            parameters=json.dumps(
                {"detection_type": detection_type, **request.model_dump()}
            ),
            progress=0.1,
        )
        self.db.add(job)
        await self.db.flush()

        try:
            download = await self.scene.download_scene(
                user_id, request.scene_id, request.collection
            )
            job.progress = 0.4
            aoi = request.aoi_geojson

            if detection_type == "water":
                result = self.detect_water(download.file_path, aoi)
            elif detection_type == "urban":
                result = self.detect_urban(download.file_path, aoi)
            elif detection_type == "building":
                result = self.detect_building(download.file_path, aoi)
            elif detection_type == "road":
                result = self.detect_road(download.file_path, aoi)
            elif detection_type == "flood":
                if request.scene_id_before:
                    before = await self.scene.download_scene(
                        user_id, request.scene_id_before, request.collection
                    )
                    result = self.detect_flood(
                        before.file_path, download.file_path, aoi
                    )
                    ref_path = before.file_path
                else:
                    result = self.detect_flood_single(download.file_path, aoi)
                    ref_path = download.file_path
                output_path = self._save_classification(result, ref_path, job.id)
                detected = int(np.sum(result > 0))
                job.status = "completed"
                job.progress = 1.0
                job.result_path = output_path
                job.result_json = json.dumps(
                    {
                        "detection_type": detection_type,
                        "detected_pixels": detected,
                        "total_pixels": int(result.size),
                        "coverage_pct": round(detected / max(result.size, 1) * 100, 2),
                    }
                )
                job.completed_at = datetime.now(timezone.utc)
                await self.db.flush()
                return job
            else:
                raise ValueError(f"Unknown detection type: {detection_type}")

            job.progress = 0.8
            output_path = self._save_classification(result, download.file_path, job.id)
            detected = int(np.sum(result > 0))

            job.status = "completed"
            job.progress = 1.0
            job.result_path = output_path
            job.result_json = json.dumps(
                {
                    "detection_type": detection_type,
                    "detected_pixels": detected,
                    "total_pixels": int(result.size),
                    "coverage_pct": round(detected / max(result.size, 1) * 100, 2),
                }
            )
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return job

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise

    def land_cover_map(self, file_path: str, aoi_geojson: Optional[str] = None) -> np.ndarray:
        """Rule-based land cover class map from spectral indices."""
        ndvi, _ = self.raster.compute_index(file_path, "NDVI", aoi_geojson=aoi_geojson)
        ndwi, _ = self.raster.compute_index(file_path, "NDWI", aoi_geojson=aoi_geojson)
        ndbi, _ = self.raster.compute_index(file_path, "NDBI", aoi_geojson=aoi_geojson)

        class_map = np.full(ndvi.shape, self.CLASS_BARE, dtype=np.uint8)
        class_map[ndvi > 0.35] = self.CLASS_VEGETATION
        class_map[(ndbi > 0.05) & (ndvi < 0.3)] = self.CLASS_URBAN
        class_map[ndwi > 0.15] = self.CLASS_WATER
        return class_map

    # ------------------------------------------------------------------
    # Model backends
    # ------------------------------------------------------------------

    def _random_forest_classify(self, features: np.ndarray, num_classes: int) -> np.ndarray:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.cluster import KMeans

        sample_size = min(8000, len(features))
        indices = np.random.choice(len(features), sample_size, replace=False)
        sample = features[indices]

        kmeans = KMeans(n_clusters=num_classes, random_state=42, n_init=10)
        labels = kmeans.fit_predict(sample)

        rf = RandomForestClassifier(
            n_estimators=50,
            max_depth=12,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(sample, labels)

        batch_size = 20000
        results = np.zeros(len(features), dtype=int)
        for i in range(0, len(features), batch_size):
            results[i : i + batch_size] = rf.predict(features[i : i + batch_size])
        return results

    def _svm_classify(self, features: np.ndarray, num_classes: int) -> np.ndarray:
        from sklearn.cluster import KMeans
        from sklearn.svm import SVC
        from sklearn.preprocessing import StandardScaler

        sample_size = min(5000, len(features))
        indices = np.random.choice(len(features), sample_size, replace=False)
        sample = features[indices]

        scaler = StandardScaler()
        sample_scaled = scaler.fit_transform(sample)

        kmeans = KMeans(n_clusters=num_classes, random_state=42, n_init=10)
        labels = kmeans.fit_predict(sample_scaled)

        svc = SVC(kernel="rbf", gamma="scale")
        svc.fit(sample_scaled, labels)

        batch_size = 10000
        results = np.zeros(len(features), dtype=int)
        for i in range(0, len(features), batch_size):
            batch = scaler.transform(features[i : i + batch_size])
            results[i : i + batch_size] = svc.predict(batch)
        return results

    def _deep_learning_classify(self, features: np.ndarray, num_classes: int) -> np.ndarray:
        import torch
        import torch.nn as nn
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        class SimpleClassifier(nn.Module):
            def __init__(self, input_dim: int, num_classes: int):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(input_dim, 64),
                    nn.ReLU(),
                    nn.Dropout(0.1),
                    nn.Linear(64, 32),
                    nn.ReLU(),
                    nn.Linear(32, num_classes),
                )

            def forward(self, x):
                return self.net(x)

        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)

        sample_size = min(10000, len(features_scaled))
        indices = np.random.choice(len(features_scaled), sample_size, replace=False)
        sample = torch.FloatTensor(features_scaled[indices])

        kmeans = KMeans(n_clusters=num_classes, random_state=42, n_init=10)
        labels = kmeans.fit_predict(features_scaled[indices])

        model = SimpleClassifier(features.shape[1], num_classes)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
        criterion = nn.CrossEntropyLoss()

        target = torch.LongTensor(labels)
        model.train()
        for _ in range(50):
            optimizer.zero_grad()
            output = model(sample)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

        model.eval()
        results = np.zeros(len(features), dtype=int)
        batch_size = 10000
        with torch.no_grad():
            for i in range(0, len(features_scaled), batch_size):
                batch = torch.FloatTensor(features_scaled[i : i + batch_size])
                preds = model(batch).argmax(dim=1).numpy()
                results[i : i + batch_size] = preds
        return results

    def _cnn_change_detection(self, before: np.ndarray, after: np.ndarray) -> np.ndarray:
        """Lightweight CNN-style change: local patch statistics + threshold."""
        diff = np.abs(after.astype(float) - before.astype(float))
        # Local mean of absolute difference (3x3)
        padded = np.pad(diff, 1, mode="edge")
        local = np.zeros_like(diff)
        for i in range(3):
            for j in range(3):
                local += padded[i : i + diff.shape[0], j : j + diff.shape[1]]
        local /= 9.0
        threshold = float(np.percentile(local[np.isfinite(local)], 92)) if np.isfinite(local).any() else 0.15
        return (local > threshold).astype(np.uint8)

    def _save_classification(self, data: np.ndarray, source_path: str, job_id: int) -> str:
        import rasterio

        output_dir = self.settings.imagery_cache_dir / "ml"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"classification_{job_id}.tif"

        with rasterio.open(source_path) as src:
            profile = src.profile.copy()
            profile.update(
                dtype=rasterio.uint8,
                count=1,
                compress="deflate",
                height=data.shape[0],
                width=data.shape[1],
            )

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(data.astype(np.uint8), 1)

        return str(output_path)
