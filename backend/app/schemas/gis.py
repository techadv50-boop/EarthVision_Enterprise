"""GIS utility schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GeocodeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=5, ge=1, le=20)


class GeocodeResult(BaseModel):
    display_name: str
    longitude: float
    latitude: float
    bounding_box: list[float] | None = None
    place_type: str | None = None
    importance: float | None = None


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]


class ReverseGeocodeRequest(BaseModel):
    longitude: float
    latitude: float


class MeasurementRequest(BaseModel):
    geometry: dict[str, Any]
    unit: Literal["meters", "kilometers", "miles", "hectares", "acres"] = "meters"


class MeasurementResponse(BaseModel):
    length_meters: float | None = None
    area_sq_meters: float | None = None
    perimeter_meters: float | None = None
    display_value: str
    unit: str


class GeoJSONConvertRequest(BaseModel):
    geojson: dict[str, Any]
    target_crs: str = "EPSG:4326"


class ExportRequest(BaseModel):
    format: Literal["geojson", "kml", "csv"] = "geojson"
    features: dict[str, Any]
    filename: str = "export"
