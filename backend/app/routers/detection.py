"""Detection routes for AI / maritime / air-domain toolbox tools."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.detection import DetectionRunRequest, DetectionRunResponse
from app.services.detection_service import DetectionService, TASK_META

router = APIRouter(prefix="/detection", tags=["Detection"])


@router.get("/tasks")
async def list_detection_tasks(user: CurrentUser) -> list[dict]:
    return DetectionService().list_tasks()


@router.post("/run", response_model=DetectionRunResponse)
async def run_detection(
    data: DetectionRunRequest, user: CurrentUser
) -> DetectionRunResponse:
    from app.core.concurrency import run_sync

    return await run_sync(DetectionService().run, data)


@router.get("/meta")
async def detection_meta(user: CurrentUser) -> dict:
    return {
        "tasks": list(TASK_META.keys()),
        "algorithms": {
            key: meta.get("algorithm", "") for key, meta in TASK_META.items()
        },
        "formula": (
            "Spectral-index–guided classical EO detectors "
            "(NDVI/NDWI/NDBI/NBR/BSI, Sobel edges, LoG/CFAR blobs) "
            "with deterministic seeded fallback when scene bands are unavailable"
        ),
        "map_chrome": ["legend", "scale_bar", "north_arrow", "grid"],
    }
