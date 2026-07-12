"""Pydantic schemas for geospatial operations."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class GeoJSONGeometry(BaseModel):
    type: str
    coordinates: Any


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJSONGeometry
    properties: dict[str, Any] = {}


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]


class BookmarkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    altitude: float = 10000.0
    heading: float = 0.0
    pitch: float = -45.0
    roll: float = 0.0


class BookmarkResponse(BookmarkCreate):
    id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AOICreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    geometry_type: str
    geojson: str


class AOIResponse(AOICreate):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LocationSearchResult(BaseModel):
    name: str
    display_name: str
    longitude: float
    latitude: float
    bounding_box: Optional[list[float]] = None
    place_type: Optional[str] = None


class CoordinateSearch(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class MeasurementResult(BaseModel):
    type: str
    value: float
    unit: str


class MeasureRequest(BaseModel):
    """Accept GeoJSON as a string or as an inline geometry/feature object."""

    geojson: Any = Field(description="GeoJSON geometry, Feature, or JSON string")


class FlyToRequest(BaseModel):
    longitude: float
    latitude: float
    altitude: float = 10000.0
    heading: float = 0.0
    pitch: float = -45.0
    duration: float = 3.0
