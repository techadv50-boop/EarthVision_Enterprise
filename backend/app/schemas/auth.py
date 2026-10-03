"""Pydantic schemas for authentication."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ServicePrivileges(BaseModel):
    services: list[str] = Field(default_factory=list)
    review_branches: list[str] = Field(default_factory=list)
    author_wings: list[str] = Field(default_factory=list)
    all_journals: bool = False


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None
    organization: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    organization: Optional[str] = None
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    desks: list[str] = []
    privileges: ServicePrivileges = Field(default_factory=ServicePrivileges)
    can_manage_users: bool = False
    access_status: str = "approved"
    assigned_journal_ids: list[int] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class PasswordReset(BaseModel):
    email: str
    master_password: str
    new_password: str = Field(min_length=6, max_length=128)
