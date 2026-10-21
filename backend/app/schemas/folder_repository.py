"""Schemas for relay folder repositories (separate from satellite catalogs)."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

ALLOWED_RELAY_HOST = "relay.xdgen.com"


def validate_relay_repository_url(value: str) -> str:
    cleaned = (value or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        raise ValueError("Repository address must use https")
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_RELAY_HOST:
        raise ValueError(f"Repository address must be on {ALLOWED_RELAY_HOST}")
    path = parsed.path or ""
    if "/api/v1/archives/" not in path:
        raise ValueError(
            "Repository address must look like "
            "https://relay.xdgen.com/api/v1/archives/<folder>"
        )
    return cleaned


class FolderRepositoryCreate(BaseModel):
    label: str = Field(min_length=2, max_length=128)
    repository_url: str = Field(min_length=12, max_length=512)
    api_key: str = Field(min_length=4, max_length=512)
    notes: str | None = None
    enabled: bool = True
    sort_order: int = 100

    @field_validator("repository_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_relay_repository_url(value)

    @field_validator("api_key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("API key is required")
        return cleaned


class FolderRepositoryUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=128)
    repository_url: str | None = Field(default=None, min_length=12, max_length=512)
    api_key: str | None = Field(default=None, min_length=4, max_length=512)
    notes: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None

    @field_validator("repository_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_relay_repository_url(value)

    @field_validator("api_key")
    @classmethod
    def _validate_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class FolderRepositoryPublic(BaseModel):
    """Safe payload for authenticated clients (no API key)."""

    id: str
    label: str
    repository_url: str
    enabled: bool
    sort_order: int

    model_config = {"from_attributes": True}


class FolderRepositoryAdmin(FolderRepositoryPublic):
    has_api_key: bool = False
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FolderRepositoryListResponse(BaseModel):
    total: int
    items: list[FolderRepositoryPublic]


class FolderRepositoryAdminListResponse(BaseModel):
    total: int
    items: list[FolderRepositoryAdmin]


class FolderDatesResponse(BaseModel):
    ok: bool = True
    dates: list[str]
    raw: object | None = None


class FolderFileEntry(BaseModel):
    path: str
    name: str | None = None
    size: int | None = None
    raw: object | None = None


class FolderFilesResponse(BaseModel):
    ok: bool = True
    date: str
    files: list[FolderFileEntry]
    raw: object | None = None
