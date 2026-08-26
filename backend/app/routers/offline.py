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
    acquisition_date: str  # required
    acquisition_time: str | None = None
    label: str | None = None
    cloud_cover: float | None = None
    sensor: str | None = None
    platform: str | None = None
    resolution_m: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    footprint_geojson: str | None = None
    working_path: str | None = None


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


@router.get("/formats/vector")
async def list_vector_formats():
    from app.services.vector_ingest_service import VectorIngestService

    return VectorIngestService.supported_formats()


@router.post("/layers/upload-vector")
async def upload_vector(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
):
    """Upload vector data (point / line / polygon): GeoJSON, Shapefile ZIP, KML, GPX, GML."""
    from app.services.vector_ingest_service import VectorIngestService

    _ = current_user
    ingest = VectorIngestService()
    filename = file.filename or "layer.geojson"
    if not ingest.is_supported(filename):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported vector format. Accepted: "
                f"{', '.join(ingest.supported_formats()['extensions'])}"
            ),
        )

    layers = OfflineLayersService()
    dest_dir = layers.vector_dir
    staging = dest_dir / f"_staging_{Path(filename).name}"
    with staging.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    result: dict[str, Any] | None = None
    try:
        result = ingest.ingest(staging, dest_dir, original_filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if staging.exists():
            keep = Path(result["original_path"]).resolve() if result else None
            if keep is None or staging.resolve() != keep:
                staging.unlink(missing_ok=True)

    assert result is not None
    return {
        "ok": True,
        "path": result["original_path"],
        "geojson_path": result["geojson_path"],
        "original_format": result["original_format"],
        "feature_count": result["feature_count"],
        "geometry_counts": result["geometry_counts"],
        "bbox": result["bbox"],
        "geojson": result["geojson"],
        "layers": layers.list_layers(),
    }


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


@router.get("/formats")
async def list_supported_formats():
    from app.services.image_ingest_service import ImageIngestService

    return ImageIngestService.supported_formats()


@router.post("/stacks/{stack_id}/images")
async def add_image_to_stack(
    stack_id: str,
    body: StackAddImageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    _ = current_user
    meta = dict(body.metadata or {})
    if body.sensor:
        meta["sensor"] = body.sensor
    if body.platform:
        meta["platform"] = body.platform
    if body.resolution_m is not None:
        meta["resolution_m"] = body.resolution_m
    if body.notes:
        meta["notes"] = body.notes
    try:
        stack = ImageryStackService().add_image(
            stack_id,
            file_path=body.file_path,
            acquisition_date=body.acquisition_date,
            acquisition_time=body.acquisition_time,
            label=body.label,
            cloud_cover=body.cloud_cover,
            metadata=meta,
            footprint_geojson=body.footprint_geojson,
            working_path=body.working_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")
    return stack


@router.post("/stacks/upload")
async def upload_to_stack(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    place_name: str = Form(...),
    acquisition_date: str = Form(..., description="Required acquisition date YYYY-MM-DD"),
    acquisition_time: Optional[str] = Form(default=None),
    longitude: Optional[float] = Form(default=None),
    latitude: Optional[float] = Form(default=None),
    altitude_m: Optional[float] = Form(default=None),
    cloud_cover: Optional[float] = Form(default=None),
    sensor: Optional[str] = Form(default=None),
    platform: Optional[str] = Form(default=None),
    resolution_m: Optional[float] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    label: Optional[str] = Form(default=None),
):
    """Upload a satellite/optical image with required date + optional metadata.

    Accepts many formats; normalizes to a working GeoTIFF for GIS tools.
    """
    from app.services.image_ingest_service import ImageIngestService

    _ = db
    ingest = ImageIngestService()
    filename = file.filename or "scene.tif"
    if not ingest.is_supported(filename):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported image format. Accepted extensions: "
                f"{', '.join(ingest.supported_formats()['extensions'])}"
            ),
        )

    try:
        date = ingest.parse_required_date(acquisition_date)
        time_val = ingest.parse_optional_time(acquisition_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()
    user_id = current_user.id
    dest_dir = settings.upload_dir / "offline" / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Stage upload then normalize
    staging = dest_dir / f"_staging_{Path(filename).name}"
    with staging.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    result: dict[str, Any] | None = None
    try:
        result = ingest.ingest(staging, dest_dir, original_filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        # Remove staging copy if it is not the kept original
        if staging.exists():
            keep = Path(result["original_path"]).resolve() if result else None
            if keep is None or staging.resolve() != keep:
                staging.unlink(missing_ok=True)

    assert result is not None

    if longitude is None:
        longitude = result.get("longitude")
    if latitude is None:
        latitude = result.get("latitude")

    meta: dict[str, Any] = {
        "original_filename": Path(filename).name,
        "original_format": result.get("original_format"),
        "normalized": result.get("normalized"),
        "convert_note": result.get("convert_note"),
        "raster_info": result.get("info"),
        "working_path": result.get("working_path"),
    }
    if time_val:
        meta["acquisition_time"] = time_val
    if sensor:
        meta["sensor"] = sensor
    if platform:
        meta["platform"] = platform
    if resolution_m is not None:
        meta["resolution_m"] = resolution_m
    if altitude_m is not None:
        meta["altitude_m"] = altitude_m
    if notes:
        meta["notes"] = notes
    if longitude is not None:
        meta["longitude"] = longitude
    if latitude is not None:
        meta["latitude"] = latitude

    stacks = ImageryStackService()
    stack = stacks.find_or_create_for_place(
        place_name, longitude=longitude, latitude=latitude
    )
    try:
        stack = stacks.add_image(
            stack["id"],
            file_path=result["original_path"],
            working_path=result["working_path"],
            acquisition_date=date,
            acquisition_time=time_val,
            label=label or Path(filename).name,
            cloud_cover=cloud_cover,
            metadata=meta,
            original_format=result.get("original_format"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "stack": stack,
        "file_path": result["original_path"],
        "working_path": result["working_path"],
        "info": result.get("info"),
        "acquisition_date": date,
        "acquisition_time": time_val,
        "format": result.get("original_format"),
        "normalized": result.get("normalized"),
        "slider_max_index": stack.get("slider_max_index") if stack else 0,
        "image_count": stack.get("image_count") if stack else 0,
    }


@router.post("/stacks/seed-demo")
async def seed_demo_stack():
    return ImageryStackService().seed_demo_stack()
