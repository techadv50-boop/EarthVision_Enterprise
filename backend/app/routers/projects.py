"""Project management routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.schemas.common import MessageResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ProjectListResponse:
    service = ProjectService(db)
    items, total = await service.list_for_user(user, page=page, page_size=page_size)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate, db: DbSession, user: CurrentUser
) -> ProjectResponse:
    service = ProjectService(db)
    project = await service.create(user, data)
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str, db: DbSession, user: CurrentUser
) -> ProjectResponse:
    service = ProjectService(db)
    project = await service.get(project_id, user)
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, data: ProjectUpdate, db: DbSession, user: CurrentUser
) -> ProjectResponse:
    service = ProjectService(db)
    project = await service.update(project_id, user, data)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: str, db: DbSession, user: CurrentUser
) -> MessageResponse:
    service = ProjectService(db)
    await service.delete(project_id, user)
    return MessageResponse(message="Project deleted")
