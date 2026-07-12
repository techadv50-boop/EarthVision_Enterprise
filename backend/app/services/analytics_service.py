"""Analytics and remote sensing index computation service."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisJob
from app.models.scene import CachedScene
from app.schemas.analytics import (
    HistogramResponse,
    IndexComputeRequest,
    IndexComputeResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
    TimeSeriesPoint,
)
from app.services.raster_service import RasterService
from app.services.scene_service import SceneService


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.raster = RasterService()
        self.scene = SceneService(db)

    async def compute_index(
        self, user_id: int, request: IndexComputeRequest
    ) -> IndexComputeResponse:
        job = AnalysisJob(
            user_id=user_id,
            job_type=f"index_{request.index_type.upper()}",
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
            job.progress = 0.5

            index_data, stats = self.raster.compute_index(
                download.file_path,
                request.index_type,
                aoi_geojson=request.aoi_geojson,
            )
            output_path = self.raster.save_index_raster(
                index_data, download.file_path, request.index_type.upper(), job.id
            )

            job.status = "completed"
            job.progress = 1.0
            job.result_path = output_path
            job.result_json = json.dumps({"statistics": stats})
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()

            return IndexComputeResponse(
                job_id=job.id,
                index_type=request.index_type.upper(),
                status="completed",
                tile_url=f"/api/v1/analytics/tiles/{job.id}/{{z}}/{{x}}/{{y}}.png",
                statistics=stats,
            )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise

    async def _acquisition_date(self, user_id: int, scene_id: str) -> datetime:
        result = await self.db.execute(
            select(CachedScene).where(
                CachedScene.user_id == user_id,
                CachedScene.scene_id == scene_id,
            )
        )
        cached = result.scalar_one_or_none()
        if cached and cached.acquisition_date:
            return cached.acquisition_date
        return datetime.now(timezone.utc)

    async def compute_time_series(
        self, user_id: int, request: TimeSeriesRequest
    ) -> TimeSeriesResponse:
        points: list[TimeSeriesPoint] = []
        values: list[float] = []

        for scene_id in request.scene_ids:
            download = await self.scene.download_scene(user_id, scene_id, request.collection)
            _, stats = self.raster.compute_index(
                download.file_path,
                request.index_type,
                aoi_geojson=request.aoi_geojson,
            )
            mean_val = stats["mean"]
            values.append(mean_val)
            acq_date = await self._acquisition_date(user_id, scene_id)
            points.append(
                TimeSeriesPoint(
                    date=acq_date,
                    value=mean_val,
                    scene_id=scene_id,
                )
            )

        # Sort chronologically
        points.sort(key=lambda p: p.date)
        values = [p.value for p in points]

        import numpy as np

        return TimeSeriesResponse(
            index_type=request.index_type.upper(),
            points=points,
            statistics={
                "min": float(np.min(values)) if values else 0.0,
                "max": float(np.max(values)) if values else 0.0,
                "mean": float(np.mean(values)) if values else 0.0,
                "std": float(np.std(values)) if values else 0.0,
                "trend": float(values[-1] - values[0]) if len(values) >= 2 else 0.0,
            },
        )

    async def get_histogram(self, job_id: int, user_id: int) -> HistogramResponse:
        result = await self.db.execute(
            select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.user_id == user_id)
        )
        job = result.scalar_one_or_none()
        if not job or not job.result_path:
            raise ValueError("Analysis job not found or has no results")

        import rasterio

        with rasterio.open(job.result_path) as src:
            data = src.read(1)

        hist = self.raster.compute_histogram(data)
        return HistogramResponse(**hist)
