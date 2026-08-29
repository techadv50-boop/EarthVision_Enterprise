"""Administration and commercial feature routes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.dependencies import get_current_user, require_permission
from app.database.session import get_db
from app.models.analysis import AnalysisJob
from app.models.project import Project
from app.models.scene import CachedScene
from app.models.subscription import APIKey, Subscription
from app.models.user import Role, User
from app.schemas.admin import (
    AdminStats,
    APIKeyCreate,
    APIKeyCreated,
    APIKeyResponse,
    ProjectCreate,
    ProjectResponse,
    RoleResponse,
    SubscriptionResponse,
    UserAdminUpdate,
)
from app.schemas.auth import UserResponse as AuthUserResponse

router = APIRouter(prefix="/admin", tags=["Administration"])


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def compute_storage_used_gb() -> float:
    settings = get_settings()
    total = 0
    for d in (settings.scene_cache_dir, settings.imagery_cache_dir, settings.upload_dir):
        total += _dir_size_bytes(Path(d))
    return round(total / (1024**3), 4)


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _admin: Annotated[User, Depends(require_permission("admin", "all"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    total_users = await db.scalar(select(func.count(User.id)))
    active_users = await db.scalar(select(func.count(User.id)).where(User.is_active == True))  # noqa: E712
    total_projects = await db.scalar(select(func.count(Project.id)))
    total_scenes = await db.scalar(select(func.count(CachedScene.id)))
    total_jobs = await db.scalar(select(func.count(AnalysisJob.id)))

    return AdminStats(
        total_users=total_users or 0,
        active_users=active_users or 0,
        total_projects=total_projects or 0,
        total_scenes_cached=total_scenes or 0,
        total_analysis_jobs=total_jobs or 0,
        storage_used_gb=compute_storage_used_gb(),
    )


@router.get("/users", response_model=list[AuthUserResponse])
async def list_users(
    _admin: Annotated[User, Depends(require_permission("admin", "all"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(User).options(selectinload(User.roles)).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        AuthUserResponse(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            organization=u.organization,
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            roles=[r.name for r in u.roles],
            created_at=u.created_at,
        )
        for u in users
    ]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserAdminUpdate,
    admin: Annotated[User, Depends(require_permission("admin", "all"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.email is not None:
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.role is not None:
        name = data.role.strip().lower()
        if name not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="Role must be admin or user")
        if user.id == admin.id and name != "admin":
            raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
        role_row = await db.execute(select(Role).where(Role.name == name))
        assigned = role_row.scalar_one_or_none()
        if assigned is None:
            raise HTTPException(status_code=400, detail="Role not found")
        user.roles = [assigned]
        user.is_superuser = name == "admin"
    elif data.role_ids is not None:
        roles_result = await db.execute(select(Role).where(Role.id.in_(data.role_ids)))
        user.roles = list(roles_result.scalars().all())

    await db.flush()
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    updated = result.scalar_one()
    return {
        "message": "User updated",
        "id": updated.id,
        "roles": [r.name for r in updated.roles],
        "is_superuser": updated.is_superuser,
    }


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    _admin: Annotated[User, Depends(require_permission("admin", "all"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Role).options(selectinload(Role.permissions)))
    roles = result.scalars().all()
    return [
        RoleResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            permissions=[p.name for p in r.permissions],
        )
        for r in roles
    ]


@router.get("/projects", response_model=list[ProjectResponse])
async def list_all_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == current_user.id)
        .order_by(Project.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    project = Project(owner_id=current_user.id, **data.model_dump())
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found")
    return sub


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user.id)
        .order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/api-keys", response_model=APIKeyCreated, status_code=201)
async def create_api_key(
    data: APIKeyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raw_key, prefix, _ = APIKey.generate_key()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at = None
    if data.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)

    api_key = APIKey(
        user_id=current_user.id,
        name=data.name,
        key_hash=key_hash,
        prefix=prefix,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    return APIKeyCreated(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        key=raw_key,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.is_active = False
    await db.flush()
