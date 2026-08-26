"""Pydantic schemas for authentication."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetMaster(BaseModel):
    """Reset any client password using the SAT EYE master code (NTZHSS)."""

    username: str = Field(min_length=1, max_length=100)
    master_code: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=128)
