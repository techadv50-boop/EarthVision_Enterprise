"""Pydantic schemas for administration and commercial features."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import ServicePrivileges


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class ProjectResponse(ProjectCreate):
    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = None
    permission_ids: list[int] = []


class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    permissions: list[str] = []

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    id: int
    plan: str
    status: str
    max_scenes_per_month: int
    max_storage_gb: int
    max_api_calls_per_day: int
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None

    model_config = {"from_attributes": True}


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(default=365, ge=1, le=3650)


class APIKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class APIKeyCreated(APIKeyResponse):
    key: str


class UserAdminCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None
    role: str = Field(default="user", description="admin = operator; user = staff with optional services")
    desks: list[str] = Field(default_factory=list)
    privileges: Optional[ServicePrivileges] = None
    assigned_journal_ids: list[int] = Field(default_factory=list)
    access_status: Optional[str] = Field(default="approved")


class UserAdminUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[list[int]] = None
    role: Optional[str] = Field(default=None, description="admin = every desk; user = staff plus optional desks")
    desks: Optional[list[str]] = None
    privileges: Optional[ServicePrivileges] = None
    access_status: Optional[str] = Field(
        default=None, description="pending, approved, or restricted"
    )
    assigned_journal_ids: Optional[list[int]] = None
    approval: Optional[str] = Field(
        default=None, description="full, partial, or restrict"
    )


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    total_projects: int
    total_scenes_cached: int
    total_analysis_jobs: int
    storage_used_gb: float
