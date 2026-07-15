"""Bookmark schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BookmarkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    height: float = 1_000_000.0
    heading: float = 0.0
    pitch: float = -90.0
    roll: float = 0.0


class BookmarkUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    height: float | None = None
    heading: float | None = None
    pitch: float | None = None
    roll: float | None = None


class BookmarkResponse(BaseModel):
    id: str
    name: str
    description: str | None
    longitude: float
    latitude: float
    height: float
    heading: float
    pitch: float
    roll: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
