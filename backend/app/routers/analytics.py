"""Analytics and remote sensing index routes."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_user_tile_compatible
from app.database.session import get_db
from app.models.analysis import AnalysisJob
from app.models.user import User
from app.schemas.analytics import (
    AnalysisJobResponse,
    ChangeDetectionRequest,
    HistogramResponse,
    IndexComputeRequest,
    IndexComputeResponse,
    MLClassificationRequest,
    ReportRequest,
    ThematicDetectionRequest,
    TimeSeriesRequest,
    TimeSeriesResponse,
)
from app.services.analytics_service import AnalyticsService
from app.services.ml_service import MLService
from app.services.quota_service import enforce_analysis_quota
from app.services.report_service import ReportService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _job_response(job: AnalysisJob) -> AnalysisJobResponse:
    tile_url = None
    if job.status == "completed" and job.result_path:
        tile_url = f"/api/v1/analytics/tiles/{job.id}/{{z}}/{{x}}/{{y}}.png"
    return AnalysisJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        result_path=job.result_path,
        result_json=job.result_json,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        tile_url=tile_url,
    )


@router.post("/index", response_model=IndexComputeResponse)
async def compute_index(
    request: IndexComputeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = AnalyticsService(db)
    return await service.compute_index(current_user.id, request)


@router.post("/time-series", response_model=TimeSeriesResponse)
async def compute_time_series(
    request: TimeSeriesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = AnalyticsService(db)
    return await service.compute_time_series(current_user.id, request)


@router.get("/histogram/{job_id}", response_model=HistogramResponse)
async def get_histogram(
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = AnalyticsService(db)
    return await service.get_histogram(job_id, current_user.id)


@router.post("/classify", response_model=AnalysisJobResponse)
async def classify(
    request: MLClassificationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.classify(current_user.id, request)
    return _job_response(job)


@router.post("/change-detection", response_model=AnalysisJobResponse)
async def change_detection(
    request: ChangeDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = MLService(db)
    job = await service.change_detection(current_user.id, request)
    return _job_response(job)


@router.post("/detect/water", response_model=AnalysisJobResponse)
async def detect_water(
    request: ThematicDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.run_thematic_detection(current_user.id, "water", request)
    return _job_response(job)


@router.post("/detect/flood", response_model=AnalysisJobResponse)
async def detect_flood(
    request: ThematicDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.run_thematic_detection(current_user.id, "flood", request)
    return _job_response(job)


@router.post("/detect/building", response_model=AnalysisJobResponse)
async def detect_building(
    request: ThematicDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.run_thematic_detection(current_user.id, "building", request)
    return _job_response(job)


@router.post("/detect/road", response_model=AnalysisJobResponse)
async def detect_road(
    request: ThematicDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.run_thematic_detection(current_user.id, "road", request)
    return _job_response(job)


@router.post("/detect/urban", response_model=AnalysisJobResponse)
async def detect_urban(
    request: ThematicDetectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(enforce_analysis_quota)],
):
    service = MLService(db)
    job = await service.run_thematic_detection(current_user.id, "urban", request)
    return _job_response(job)


@router.get("/jobs", response_model=list[AnalysisJobResponse])
async def list_jobs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.user_id == current_user.id)
        .order_by(AnalysisJob.created_at.desc())
        .limit(50)
    )
    return [_job_response(job) for job in result.scalars().all()]


@router.get("/jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_job(
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(job)


@router.post("/report")
async def generate_report(
    request: ReportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    service = ReportService()
    if request.report_type == "pdf":
        path = service.generate_pdf(request.title, request.content)
    elif request.report_type == "excel":
        path = service.generate_excel(request.title, request.content)
    elif request.report_type == "csv":
        path = service.generate_csv(request.title, request.content)
    else:
        raise HTTPException(status_code=400, detail="Invalid report type")

    return {
        "file_path": path,
        "report_type": request.report_type,
        "download_url": f"/api/v1/analytics/report/download?file_path={path}",
    }


@router.get("/report/download")
async def download_report(
    file_path: Annotated[str, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Download a previously generated report file."""
    path = Path(file_path)
    settings = ReportService().settings
    reports_dir = settings.upload_dir / "reports"
    try:
        resolved = path.resolve()
        reports_resolved = reports_dir.resolve()
        if not str(resolved).startswith(str(reports_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    media_types = {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
    }
    media_type = media_types.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), filename=path.name, media_type=media_type)


@router.get("/tiles/{job_id}/{z}/{x}/{y}.png")
async def get_analysis_tile(
    job_id: int,
    z: int,
    x: int,
    y: int,
    current_user: Annotated[User, Depends(get_current_user_tile_compatible)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """XYZ tile for analysis results.

    Cesium cannot send Bearer headers — append ``?token=${access_token}`` to the URL.
    """
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if not job or not job.result_path:
        raise HTTPException(status_code=404, detail="Tile not found")

    try:
        from app.services.raster_service import RasterService

        png_bytes = RasterService().render_tile(job.result_path, z, x, y)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Tile generation failed: {exc}")
