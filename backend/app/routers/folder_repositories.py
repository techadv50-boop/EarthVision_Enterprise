"""Folder repository routes — admin CRUD + Bearer-proxied relay browse/download."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import Response as FastAPIResponse

from app.core.deps import CurrentUser, DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.folder_repository import (
    FolderDatesResponse,
    FolderFilesResponse,
    FolderRepositoryAdmin,
    FolderRepositoryAdminListResponse,
    FolderRepositoryCreate,
    FolderRepositoryListResponse,
    FolderRepositoryPublic,
    FolderRepositoryUpdate,
)
from app.services.folder_repository_service import FolderRepositoryService, to_admin

router = APIRouter(prefix="/folder-repos", tags=["FolderRepositories"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=FolderRepositoryListResponse)
async def list_enabled_folder_repos(
    db: DbSession,
    user: CurrentUser,
) -> FolderRepositoryListResponse:
    """Enabled folder repositories (no secrets) for authenticated users."""
    _ = user
    service = FolderRepositoryService(db)
    items = await service.list_enabled()
    return FolderRepositoryListResponse(
        total=len(items),
        items=[FolderRepositoryPublic.model_validate(row) for row in items],
    )


@router.get("/admin", response_model=FolderRepositoryAdminListResponse)
async def list_folder_repos_admin(
    db: DbSession,
    admin: AdminUser,
) -> FolderRepositoryAdminListResponse:
    _ = admin
    service = FolderRepositoryService(db)
    items = await service.list_all()
    return FolderRepositoryAdminListResponse(
        total=len(items), items=[to_admin(row) for row in items]
    )


@router.post("/admin", response_model=FolderRepositoryAdmin, status_code=201)
async def create_folder_repo(
    data: FolderRepositoryCreate,
    db: DbSession,
    admin: AdminUser,
) -> FolderRepositoryAdmin:
    """Register a relay folder repository. API key is stored server-side only."""
    _ = admin
    service = FolderRepositoryService(db)
    row = await service.create(data)
    return to_admin(row)


@router.patch("/admin/{repo_id}", response_model=FolderRepositoryAdmin)
async def update_folder_repo(
    repo_id: str,
    data: FolderRepositoryUpdate,
    db: DbSession,
    admin: AdminUser,
) -> FolderRepositoryAdmin:
    _ = admin
    service = FolderRepositoryService(db)
    row = await service.update(repo_id, data)
    return to_admin(row)


@router.delete("/admin/{repo_id}", status_code=204, response_class=Response)
async def delete_folder_repo(
    repo_id: str,
    db: DbSession,
    admin: AdminUser,
) -> Response:
    _ = admin
    service = FolderRepositoryService(db)
    await service.delete(repo_id)
    return Response(status_code=204)


@router.get("/{repo_id}/dates", response_model=FolderDatesResponse)
async def folder_dates(
    repo_id: str,
    db: DbSession,
    user: CurrentUser,
) -> FolderDatesResponse:
    """GET repository address with Bearer API key → list of dates."""
    _ = user
    service = FolderRepositoryService(db)
    dates, raw = await service.list_dates(repo_id)
    return FolderDatesResponse(dates=dates, raw=raw)


@router.get("/{repo_id}/files", response_model=FolderFilesResponse)
async def folder_files(
    repo_id: str,
    db: DbSession,
    user: CurrentUser,
    date: str = Query(..., description="YYYY-MM-DD"),
) -> FolderFilesResponse:
    """GET {repo}/files?date=… with Bearer API key."""
    _ = user
    service = FolderRepositoryService(db)
    files, raw = await service.list_files(repo_id, date)
    return FolderFilesResponse(date=date[:10], files=files, raw=raw)


@router.get("/{repo_id}/file")
async def folder_file_download(
    repo_id: str,
    db: DbSession,
    user: CurrentUser,
    date: str = Query(..., description="YYYY-MM-DD"),
    path: str = Query(..., description="path / relative_path / name from files list"),
) -> FastAPIResponse:
    """GET {repo}/file?date=&path= with Bearer API key → file bytes."""
    _ = user
    service = FolderRepositoryService(db)
    content, filename, content_type = await service.download_file(
        repo_id, date=date, path=path
    )
    safe_name = filename.replace('"', "").replace("\n", " ").strip() or "download.bin"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
    }
    return FastAPIResponse(
        content=content,
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )
