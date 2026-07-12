"""Satellite imagery search and download routes."""

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.imagery import (
    CopernicusAuthURL,
    CopernicusCallback,
    CopernicusTokenStatus,
    SceneDownloadRequest,
    SceneDownloadResponse,
    SceneSearchRequest,
    SceneSearchResponse,
)
from app.services.copernicus_service import CopernicusService
from app.services.quota_service import QuotaService
from app.services.scene_service import SceneService

router = APIRouter(prefix="/imagery", tags=["Satellite Imagery"])


@router.post("/search", response_model=SceneSearchResponse)
async def search_scenes(
    request: SceneSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = CopernicusService(db)
    return await service.search_scenes(current_user.id, request)


@router.post("/download", response_model=SceneDownloadResponse)
async def download_scene(
    request: SceneDownloadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SceneService(db)
    # Cache hits do not consume quota
    cached = await service.get_cached_scene(current_user.id, request.scene_id)
    if not (cached and cached.file_path and Path(cached.file_path).exists()):
        await QuotaService(db).check_scene_download(current_user.id)

    meta = dict(request.metadata or {})
    if request.product_id:
        meta.setdefault("id", request.product_id)
    return await service.download_scene(
        current_user.id,
        request.scene_id,
        request.collection,
        footprint_geojson=request.footprint_geojson,
        product_id=request.product_id or meta.get("id"),
        metadata=meta,
        acquisition_date=request.acquisition_date,
        cloud_cover=request.cloud_cover,
    )


@router.get("/cached")
async def list_cached_scenes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SceneService(db)
    scenes = await service.get_cached_scenes(current_user.id)
    return [
        {
            "id": s.id,
            "scene_id": s.scene_id,
            "collection": s.collection,
            "platform": s.platform,
            "acquisition_date": s.acquisition_date.isoformat(),
            "cloud_cover": s.cloud_cover,
            "file_path": s.file_path,
            "preview_path": s.preview_path,
            "footprint_geojson": s.footprint_geojson,
            "cached_at": s.cached_at.isoformat(),
        }
        for s in scenes
    ]


@router.get("/footprints")
async def get_footprints(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SceneService(db)
    return await service.get_scene_footprints(current_user.id)


@router.get("/preview/{scene_id}")
async def get_scene_preview(
    scene_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from fastapi.responses import FileResponse

    service = SceneService(db)
    cached = await service.get_cached_scene(current_user.id, scene_id)
    if not cached or not cached.file_path:
        raise HTTPException(status_code=404, detail="Scene not found")

    preview = cached.preview_path or service.get_preview_path(cached.file_path)
    if not preview or not Path(preview).exists():
        raise HTTPException(status_code=404, detail="Preview not available")
    return FileResponse(preview, media_type="image/png")


@router.get("/copernicus/auth-url", response_model=CopernicusAuthURL)
async def get_copernicus_auth_url(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = CopernicusService(db)
    state = secrets.token_urlsafe(16)
    await service.persist_oauth_state(current_user.id, state)
    return CopernicusAuthURL(authorization_url=service.get_authorization_url(state))


@router.post("/copernicus/callback")
async def copernicus_callback(
    callback: CopernicusCallback,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = CopernicusService(db)
    try:
        token = await service.exchange_code(current_user.id, callback.code, callback.state)
        return {"message": "Copernicus connected", "expires_at": token.expires_at.isoformat()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {exc}")


@router.get("/copernicus/status", response_model=CopernicusTokenStatus)
async def copernicus_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = CopernicusService(db)
    token = await service.get_token(current_user.id)
    return CopernicusTokenStatus(
        connected=token is not None and not token.is_expired,
        expires_at=token.expires_at if token else None,
    )
