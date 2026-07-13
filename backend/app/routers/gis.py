"""GIS utility routes."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.schemas.gis import (
    ExportRequest,
    GeocodeRequest,
    GeocodeResponse,
    MeasurementRequest,
    MeasurementResponse,
    ReverseGeocodeRequest,
)
from app.services.gis_service import GISService

router = APIRouter(prefix="/gis", tags=["GIS"])


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(data: GeocodeRequest, user: CurrentUser) -> GeocodeResponse:
    service = GISService()
    results = await service.geocode(data)
    return GeocodeResponse(results=results)


@router.post("/reverse-geocode")
async def reverse_geocode(data: ReverseGeocodeRequest, user: CurrentUser) -> dict:
    service = GISService()
    result = await service.reverse_geocode(data.longitude, data.latitude)
    return result.model_dump()


@router.post("/measure", response_model=MeasurementResponse)
async def measure(data: MeasurementRequest, user: CurrentUser) -> MeasurementResponse:
    service = GISService()
    return service.measure(data)


@router.post("/export")
async def export_features(data: ExportRequest, user: CurrentUser) -> Response:
    service = GISService()
    if data.format == "kml":
        content = service.geojson_to_kml(data.features)
        return Response(
            content=content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f'attachment; filename="{data.filename}.kml"'},
        )
    if data.format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["name", "type", "longitude", "latitude"])
        for feat in data.features.get("features", []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates", [None, None])
            if geom.get("type") == "Point":
                writer.writerow([props.get("name", ""), "Point", coords[0], coords[1]])
            else:
                writer.writerow([props.get("name", ""), geom.get("type"), "", ""])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{data.filename}.csv"'},
        )
    import json

    content = json.dumps(data.features, indent=2)
    return Response(
        content=content,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{data.filename}.geojson"'},
    )


@router.post("/export/shapefile")
async def export_shapefile(data: ExportRequest, user: CurrentUser) -> Response:
    service = GISService()
    content = service.geojson_to_shapefile_zip(data.features)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{data.filename}.zip"'},
    )


@router.post("/import/shapefile")
async def import_shapefile(
    user: CurrentUser, file: UploadFile = File(...)
) -> dict:
    service = GISService()
    content = await file.read()
    return service.shapefile_zip_to_geojson(content)
