"""User management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    role: UserRole = UserRole.VIEWER
    organization: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    organization: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserDetail(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    organization: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserDetail]
    total: int
    page: int
    page_size: int
