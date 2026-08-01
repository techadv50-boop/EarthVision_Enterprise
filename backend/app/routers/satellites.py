"""Satellite provider routes — admin CRUD + enabled list for all clients."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.deps import CurrentUser, DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.satellite_provider import (
    SatelliteProviderAdmin,
    SatelliteProviderAdminListResponse,
    SatelliteProviderCreate,
    SatelliteProviderListResponse,
    SatelliteProviderPublic,
    SatelliteProviderUpdate,
)
from app.services.satellite_provider_service import SatelliteProviderService, to_admin

router = APIRouter(prefix="/satellites", tags=["Satellites"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=SatelliteProviderListResponse)
async def list_enabled_satellites(
    db: DbSession,
    user: CurrentUser,
) -> SatelliteProviderListResponse:
    """List enabled satellites for all authenticated clients."""
    service = SatelliteProviderService(db)
    await service.ensure_builtins()
    items = await service.list_enabled()
    return SatelliteProviderListResponse(
        total=len(items),
        items=[SatelliteProviderPublic.model_validate(row) for row in items],
    )


@router.get("/admin", response_model=SatelliteProviderAdminListResponse)
async def list_satellites_admin(
    db: DbSession,
    admin: AdminUser,
) -> SatelliteProviderAdminListResponse:
    """Admin list including API configuration metadata."""
    service = SatelliteProviderService(db)
    await service.ensure_builtins()
    items = await service.list_all()
    return SatelliteProviderAdminListResponse(
        total=len(items),
        items=[to_admin(row) for row in items],
    )


@router.post("/admin", response_model=SatelliteProviderAdmin, status_code=201)
async def create_satellite(
    data: SatelliteProviderCreate,
    db: DbSession,
    admin: AdminUser,
) -> SatelliteProviderAdmin:
    """Admin-only: register a new satellite / catalog API for all clients."""
    service = SatelliteProviderService(db)
    row = await service.create(data)
    return to_admin(row)


@router.patch("/admin/{provider_id}", response_model=SatelliteProviderAdmin)
async def update_satellite(
    provider_id: str,
    data: SatelliteProviderUpdate,
    db: DbSession,
    admin: AdminUser,
) -> SatelliteProviderAdmin:
    service = SatelliteProviderService(db)
    row = await service.update(provider_id, data)
    return to_admin(row)


@router.delete("/admin/{provider_id}", status_code=204, response_class=Response)
async def delete_satellite(
    provider_id: str,
    db: DbSession,
    admin: AdminUser,
) -> Response:
    service = SatelliteProviderService(db)
    await service.delete(provider_id)
    return Response(status_code=204)
