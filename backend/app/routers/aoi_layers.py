"""SatPass district/city shapefile layers. Admin writes; all users read and select."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_citation_admin
from app.database.session import get_db
from app.models.aoi_layer import AoiLayer
from app.models.user import User
from app.services import aoi_layers as store

router = APIRouter(prefix="/aoi-layers", tags=["SatPass AOI layers"])


class LayerSummary(BaseModel):
    id: int
    name: str
    original_filename: str
    name_field: Optional[str] = None
    feature_count: int
    created_at: Optional[str] = None


class FeatureIndexItem(BaseModel):
    id: str
    name: str


class LayerDetail(LayerSummary):
    features: list[FeatureIndexItem] = Field(default_factory=list)


class ExportAoiRequest(BaseModel):
    feature_ids: list[str] = Field(min_length=1)


def _summary(row: AoiLayer) -> LayerSummary:
    return LayerSummary(
        id=row.id,
        name=row.name,
        original_filename=row.original_filename,
        name_field=row.name_field,
        feature_count=row.feature_count,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get("", response_model=list[LayerSummary])
async def list_layers(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await db.execute(select(AoiLayer).order_by(AoiLayer.name, AoiLayer.id))
    return [_summary(r) for r in rows.scalars().all()]


@router.get("/{layer_id}", response_model=LayerDetail)
async def get_layer(
    layer_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(AoiLayer, layer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Layer not found.")
    try:
        index = store.read_index(layer_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LayerDetail(**_summary(row).model_dump(), features=index)


@router.get("/{layer_id}/geojson")
async def get_layer_geojson(
    layer_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(AoiLayer, layer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Layer not found.")
    try:
        return JSONResponse(store.read_geojson(layer_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{layer_id}/download")
async def download_layer_zip(
    layer_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(AoiLayer, layer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Layer not found.")
    path = store.zip_path(layer_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original shapefile zip is missing.")
    filename = row.original_filename if row.original_filename.endswith(".zip") else f"{row.name}.zip"
    return FileResponse(path, filename=filename, media_type="application/zip")


@router.post("", response_model=LayerSummary, status_code=201)
async def create_layer(
    admin: Annotated[User, Depends(require_citation_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    name: str = Form(""),
):
    filename = (file.filename or "layer.zip").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a zipped shapefile (.zip).")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")
    try:
        parsed = store.parse_shapefile_zip(raw)
        geojson, name_field, index = store.annotate_features(parsed)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read shapefile: {exc}") from exc

    label = (name or "").strip() or Path(filename).stem.replace("_", " ")
    row = AoiLayer(
        name=label[:255],
        original_filename=filename[:255],
        name_field=name_field,
        feature_count=len(index),
        created_by_id=admin.id,
    )
    db.add(row)
    await db.flush()
    store.write_layer_files(row.id, raw, geojson, index)
    await db.refresh(row)
    return _summary(row)


@router.delete("/{layer_id}", status_code=204)
async def delete_layer(
    layer_id: int,
    _admin: Annotated[User, Depends(require_citation_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(AoiLayer, layer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Layer not found.")
    await db.delete(row)
    store.delete_layer_files(layer_id)
    return Response(status_code=204)


@router.post("/{layer_id}/export-aoi")
async def export_selected_aoi(
    layer_id: int,
    payload: ExportAoiRequest,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(AoiLayer, layer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Layer not found.")
    try:
        feats = store.features_by_ids(layer_id, payload.feature_ids)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not feats:
        raise HTTPException(status_code=400, detail="None of those features were found on this layer.")
    try:
        data = store.export_features_zip(feats, "aoi")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not export shapefile: {exc}") from exc
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in row.name)[:60] or "aoi"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}-aoi.zip"'},
    )
