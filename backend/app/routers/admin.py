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
from app.core.dependencies import get_current_user, require_desk, require_permission
from app.core.privileges import empty_privileges, full_privileges, normalize_privileges, privileges_from_desks
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
    UserAdminCreate,
    UserAdminUpdate,
)
from app.schemas.auth import UserCreate, UserResponse as AuthUserResponse
from app.services.auth_service import public_user
from app.services.journal_access import set_user_journals

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


def _user_payload(user: User) -> AuthUserResponse:
    return public_user(user)


def _want_full_admin(role: str | None) -> bool:
    return (role or "").strip().lower() == "admin"


def _create_privileges(data: UserAdminCreate) -> dict:
    if data.privileges is not None:
        priv = normalize_privileges(data.privileges.model_dump())
    elif data.desks:
        priv = privileges_from_desks(data.desks)
    else:
        priv = empty_privileges()
    if data.assigned_journal_ids and "citation" not in priv["services"]:
        priv["services"] = [*priv["services"], "citation"]
    return priv


async def _reload_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.allowed_journals))
        .where(User.id == user_id)
    )
    return result.scalar_one()


@router.get("/users", response_model=list[AuthUserResponse])
async def list_users(
    _admin: Annotated[User, Depends(require_desk("users"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.allowed_journals))
        .order_by(User.created_at.desc())
    )
    return [_user_payload(u) for u in result.scalars().all()]


@router.post("/users", response_model=AuthUserResponse, status_code=201)
async def create_user(
    data: UserAdminCreate,
    actor: Annotated[User, Depends(require_desk("users"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.services.auth_service import AuthService

    service = AuthService(db)
    if await service.get_user_by_username(data.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    if await service.get_user_by_email(str(data.email).lower()):
        raise HTTPException(status_code=400, detail="Email already registered")
    role = (data.role or "user").strip().lower()
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be admin or user")
    if role == "admin" and not actor.is_full_admin():
        raise HTTPException(
            status_code=403,
            detail="Only the operator can grant operator access",
        )
    status_name = (data.access_status or "approved").strip().lower()
    if status_name not in ("pending", "approved", "restricted"):
        raise HTTPException(status_code=400, detail="Status must be pending, approved, or restricted")
    user = await service.create_user(
        UserCreate(
            email=data.email,
            username=data.username,
            password=data.password,
            full_name=data.full_name,
        ),
        role_name="user",
        approved=status_name == "approved",
    )
    if status_name != "approved":
        user.access_status = status_name
        user.is_active = False
    await service.apply_privileges(
        user,
        full_privileges() if role == "admin" else _create_privileges(data),
        full_admin=role == "admin",
        manage_users="users" in (data.desks or []),
    )
    journal_ids = [] if role == "admin" or (
        data.privileges is not None and data.privileges.all_journals
    ) else data.assigned_journal_ids
    await set_user_journals(db, user, journal_ids)
    return _user_payload(await _reload_user(db, user.id))


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserAdminUpdate,
    admin: Annotated[User, Depends(require_desk("users"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.allowed_journals))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.email is not None:
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name

    approval = (data.approval or "").strip().lower() or None
    if approval and approval not in ("full", "partial", "restrict"):
        raise HTTPException(status_code=400, detail="Approval must be full, partial, or restrict")
    if approval == "restrict":
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="You cannot restrict your own account")
        user.access_status = "restricted"
        user.is_active = False
    elif data.access_status is not None:
        status_name = data.access_status.strip().lower()
        if status_name not in ("pending", "approved", "restricted"):
            raise HTTPException(status_code=400, detail="Status must be pending, approved, or restricted")
        if user.id == admin.id and status_name != "approved":
            raise HTTPException(status_code=400, detail="You cannot restrict your own account")
        user.access_status = status_name
        user.is_active = status_name == "approved"
    elif data.is_active is not None:
        if user.id == admin.id and not data.is_active:
            raise HTTPException(status_code=400, detail="You cannot restrict your own account")
        user.is_active = data.is_active
        user.access_status = "approved" if data.is_active else "restricted"

    from app.core.desks import normalize_desks
    from app.services.auth_service import AuthService

    service = AuthService(db)
    privileges_changed = (
        data.privileges is not None
        or data.desks is not None
        or data.role is not None
        or approval in ("full", "partial")
    )
    if privileges_changed:
        full = user.is_full_admin()
        manage_users = user.has_role("admin_users")
        priv = user.resolved_privileges()
        if approval == "full":
            full = False
            priv = full_privileges()
            user.access_status = "approved"
            user.is_active = True
        elif data.privileges is not None:
            full = False
            priv = normalize_privileges(data.privileges.model_dump())
        elif data.desks is not None:
            full = False
            priv = privileges_from_desks(data.desks)
            manage_users = "users" in normalize_desks(data.desks)
        if data.role is not None:
            name = data.role.strip().lower()
            if name not in ("admin", "user"):
                raise HTTPException(status_code=400, detail="Role must be admin or user")
            full = name == "admin"
            if full:
                priv = full_privileges()
            elif data.privileges is None and data.desks is None and approval != "full":
                priv = empty_privileges()
                manage_users = False
        if full and not admin.is_full_admin():
            raise HTTPException(
                status_code=403,
                detail="Only the operator can grant operator access",
            )
        if user.id == admin.id and admin.is_full_admin() and not full:
            raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
        await service.apply_privileges(
            user,
            priv,
            full_admin=full,
            manage_users=manage_users and not full,
        )
    elif data.role_ids is not None:
        roles_result = await db.execute(select(Role).where(Role.id.in_(data.role_ids)))
        user.roles = list(roles_result.scalars().all())

    if data.assigned_journal_ids is not None:
        await set_user_journals(db, user, data.assigned_journal_ids)

    await db.flush()
    updated = await _reload_user(db, user.id)
    payload = _user_payload(updated)
    return {
        "message": "User updated",
        "id": payload.id,
        "roles": payload.roles,
        "desks": payload.desks,
        "privileges": payload.privileges.model_dump(),
        "can_manage_users": payload.can_manage_users,
        "is_superuser": payload.is_superuser,
        "is_active": payload.is_active,
        "access_status": payload.access_status,
        "assigned_journal_ids": payload.assigned_journal_ids,
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
