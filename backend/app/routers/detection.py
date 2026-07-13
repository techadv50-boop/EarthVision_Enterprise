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
    return DetectionService().run(data)


@router.get("/meta")
async def detection_meta(user: CurrentUser) -> dict:
    return {
        "tasks": list(TASK_META.keys()),
        "formula": "heuristic/demo detector on AOI",
    }
