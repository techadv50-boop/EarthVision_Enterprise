"""SAT EYE offline APIs — layers, GIS tools, multi-date stacks, local session."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.services.gis_tools_service import GisToolsService
from app.services.imagery_stack_service import ImageryStackService
from app.services.offline_layers_service import OfflineLayersService

router = APIRouter(prefix="/offline", tags=["SAT EYE Offline"])


class ToolRunRequest(BaseModel):
    tool_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class StackCreateRequest(BaseModel):
    name: str
    place_key: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    description: str = ""


class StackAddImageRequest(BaseModel):
    file_path: str
    acquisition_date: str | None = None
    label: str | None = None
    cloud_cover: float | None = None
    metadata: dict[str, Any] | None = None
    footprint_geojson: str | None = None


@router.get("/status")
async def offline_status():
    settings = get_settings()
    layers = OfflineLayersService()
    tools = GisToolsService()
    stacks = ImageryStackService()
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "offline_mode": settings.offline_mode,
        "internet_required": False,
        "gis_tools_count": len(tools.list_tools()),
        "layers_count": len(layers.list_layers()),
        "stacks_count": len(stacks.list_stacks()),
        "data_dir": str(settings.offline_data_dir),
    }


@router.post("/seed")
async def seed_offline_data():
    layers = OfflineLayersService()
    stacks = ImageryStackService()
    result = layers.ensure_seed_data()
    demo = stacks.seed_demo_stack()
    return {"layers": result, "demo_stack": demo}


# ── Layers ──────────────────────────────────────────────────────────


@router.get("/layers")
async def list_layers():
    service = OfflineLayersService()
    service.ensure_seed_data()
    return {"layers": service.list_layers()}


@router.get("/layers/{layer_id}/geojson")
async def get_layer_geojson(layer_id: str):
    service = OfflineLayersService()
    service.ensure_seed_data()
    data = service.get_vector_geojson(layer_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Vector layer not found")
    return data


@router.get("/basemap/{z}/{x}/{y}.png")
async def basemap_tile(
    z: int,
    x: int,
    y: int,
    style: str = Query(default="satellite"),
):
    if z < 0 or z > 12:
        raise HTTPException(status_code=400, detail="Zoom out of range")
    service = OfflineLayersService()
    png = service.get_cached_or_render_tile(z, x, y, style=style)
    return Response(content=png, media_type="image/png")


@router.post("/layers/upload-elevation")
async def upload_elevation(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
    subtype: str = Form(default="DEM"),
):
    """Upload DEM / DTM / DSM GeoTIFF for offline use."""
    _ = current_user
    service = OfflineLayersService()
    subtype = subtype.upper()
    if subtype not in {"DEM", "DTM", "DSM", "USER"}:
        subtype = "USER"
    safe = Path(file.filename or "elevation.tif").name
    dest = service.dem_dir / f"user_{subtype.lower()}_{safe}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"ok": True, "path": str(dest), "subtype": subtype, "layers": service.list_layers()}


@router.post("/layers/upload-vector")
async def upload_vector(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
):
    _ = current_user
    service = OfflineLayersService()
    safe = Path(file.filename or "layer.geojson").name
    dest = service.vector_dir / f"user_{safe}"
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "path": str(dest), "layers": service.list_layers()}


# ── GIS Tools (148) ─────────────────────────────────────────────────


@router.get("/tools")
async def list_tools(
    category: Optional[str] = None,
    q: Optional[str] = None,
):
    service = GisToolsService()
    tools = service.list_tools(category=category, q=q)
    return {
        "count": len(tools),
        "total": 148,
        "categories": service.categories(),
        "tools": tools,
    }


@router.get("/tools/categories")
async def tool_categories():
    return {"categories": GisToolsService().categories()}


@router.post("/tools/run")
async def run_tool(
    body: ToolRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    _ = current_user
    result = GisToolsService().run_tool(body.tool_id, body.params)
    if not result.get("ok") and str(result.get("error", "")).startswith("Unknown"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Multi-date imagery stacks / slider ───────────────────────────────


@router.get("/stacks")
async def list_stacks():
    return {"stacks": ImageryStackService().list_stacks()}


@router.post("/stacks")
async def create_stack(
    body: StackCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    _ = current_user
    stack = ImageryStackService().create_stack(
        name=body.name,
        place_key=body.place_key,
        longitude=body.longitude,
        latitude=body.latitude,
        description=body.description,
    )
    return stack


@router.get("/stacks/{stack_id}")
async def get_stack(stack_id: str):
    stack = ImageryStackService().get_stack(stack_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")
    return stack


@router.post("/stacks/{stack_id}/images")
async def add_image_to_stack(
    stack_id: str,
    body: StackAddImageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    _ = current_user
    stack = ImageryStackService().add_image(
        stack_id,
        file_path=body.file_path,
        acquisition_date=body.acquisition_date,
        label=body.label,
        cloud_cover=body.cloud_cover,
        metadata=body.metadata,
        footprint_geojson=body.footprint_geojson,
    )
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")
    return stack


@router.post("/stacks/upload")
async def upload_to_stack(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    place_name: str = Form(...),
    acquisition_date: Optional[str] = Form(default=None),
    longitude: Optional[float] = Form(default=None),
    latitude: Optional[float] = Form(default=None),
    cloud_cover: Optional[float] = Form(default=None),
):
    """Upload a satellite image and attach it to a place stack (creates stack if needed)."""
    _ = db
    settings = get_settings()
    user_id = current_user.id
    dest_dir = settings.upload_dir / "offline" / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "scene.tif").name
    dest = dest_dir / safe
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    info = None
    try:
        from app.services.raster_service import RasterService

        info = RasterService().get_tile_info(str(dest))
        if longitude is None and latitude is None and info and "bounds" in info:
            b = info["bounds"]
            if isinstance(b, (list, tuple)) and len(b) >= 4:
                longitude = (float(b[0]) + float(b[2])) / 2
                latitude = (float(b[1]) + float(b[3])) / 2
            elif isinstance(b, dict):
                longitude = (float(b["left"]) + float(b["right"])) / 2
                latitude = (float(b["bottom"]) + float(b["top"])) / 2
    except Exception:  # noqa: BLE001
        info = None

    stacks = ImageryStackService()
    stack = stacks.find_or_create_for_place(
        place_name, longitude=longitude, latitude=latitude
    )
    stack = stacks.add_image(
        stack["id"],
        file_path=str(dest),
        acquisition_date=acquisition_date,
        label=safe,
        cloud_cover=cloud_cover,
        metadata={"original_filename": safe, "raster_info": info},
    )
    return {"stack": stack, "file_path": str(dest), "info": info}


@router.post("/stacks/seed-demo")
async def seed_demo_stack():
    return ImageryStackService().seed_demo_stack()
