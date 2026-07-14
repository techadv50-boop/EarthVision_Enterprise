"""Raster and tile engine routes."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.services.raster_service import RasterService

router = APIRouter(prefix="/raster", tags=["Raster"])


@router.get("/layers")
async def list_layers(user: CurrentUser) -> list[dict]:
    service = RasterService()
    return service.list_rasters()


@router.get("/tiles/{layer_id}/{z}/{x}/{y}.png")
async def get_tile(layer_id: str, z: int, x: int, y: int) -> Response:
    service = RasterService()
    png = service.get_tile(layer_id, z, x, y)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/preview/{layer_id}")
async def preview(layer_id: str, user: CurrentUser) -> Response:
    service = RasterService()
    png = service.create_preview(layer_id)
    return Response(content=png, media_type="image/png")


@router.post("/upload")
async def upload_raster(user: CurrentUser, file: UploadFile = File(...)) -> dict:
    service = RasterService()
    content = await file.read()
    return service.ingest_upload(file.filename or "upload.tif", content)
