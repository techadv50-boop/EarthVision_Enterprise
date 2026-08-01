"""Schemas for admin-managed satellite providers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SatelliteProviderCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, description="Stable key, e.g. SENTINEL-3")
    label: str = Field(min_length=2, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)
    api_base_url: str | None = Field(default=None, max_length=512)
    token_url: str | None = Field(default=None, max_length=512)
    client_id: str | None = Field(default=None, max_length=255)
    auth_username: str | None = Field(default=None, max_length=255)
    auth_password: str | None = Field(default=None, max_length=512)
    notes: str | None = None
    enabled: bool = True
    is_high_resolution: bool = False
    sort_order: int = 100


class SatelliteProviderUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=128)
    collection_id: str | None = Field(default=None, min_length=1, max_length=128)
    api_base_url: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    auth_username: str | None = None
    auth_password: str | None = None
    notes: str | None = None
    enabled: bool | None = None
    is_high_resolution: bool | None = None
    sort_order: int | None = None


class SatelliteProviderPublic(BaseModel):
    """Safe payload for all authenticated clients (no secrets)."""

    id: str
    name: str
    label: str
    collection_id: str
    enabled: bool
    is_builtin: bool
    is_high_resolution: bool = False
    sort_order: int

    model_config = {"from_attributes": True}


class SatelliteProviderAdmin(SatelliteProviderPublic):
    """Admin payload including API configuration (password redacted unless set)."""

    api_base_url: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    auth_username: str | None = None
    has_password: bool = False
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SatelliteProviderListResponse(BaseModel):
    total: int
    items: list[SatelliteProviderPublic]


class SatelliteProviderAdminListResponse(BaseModel):
    total: int
    items: list[SatelliteProviderAdmin]
