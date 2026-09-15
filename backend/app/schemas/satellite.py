"""Pydantic schemas for SatPass satellite / TLE endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.services.tle import canonicalize_tle_line


def _clean_tle_line(value: str) -> str:
    line = canonicalize_tle_line(value or "")
    if len(line) < 60:
        raise ValueError("TLE line looks too short (expected ~69 characters)")
    return line


class TleResult(BaseModel):
    """A single TLE set (name + two lines) returned from a lookup."""

    name: str
    norad_id: Optional[int] = None
    line1: str
    line2: str


class SatelliteCreate(BaseModel):
    name: str
    line1: str
    line2: str
    norad_id: Optional[int] = None
    color: Optional[str] = None

    @field_validator("line1", "line2")
    @classmethod
    def _validate_lines(cls, v: str) -> str:
        return _clean_tle_line(v)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        name = (v or "").strip()
        if not name:
            raise ValueError("Satellite name is required")
        return name[:255]


class SatelliteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    norad_id: Optional[int] = None
    tle_line1: str
    tle_line2: str
    color: Optional[str] = None
    created_at: datetime
