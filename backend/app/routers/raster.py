"""Raster tile and file import/export routes."""

import json
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user, get_current_user_tile_compatible
from app.database.session import get_db
from app.models.user import User
from app.services.raster_service import RasterService
from app.services.scene_service import SceneService

router = APIRouter(prefix="/raster", tags=["Raster Engine"])


def _resolve_raster_path(file_path: str, user_id: int) -> Path:
    settings = get_settings()
    full_path = Path(file_path)
    if not full_path.is_absolute():
        full_path = settings.scene_cache_dir / str(user_id) / file_path
    return full_path


@router.get("/info/{file_path:path}")
async def get_raster_info(
    file_path: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    full_path = _resolve_raster_path(file_path, current_user.id)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    service = RasterService()
    return service.get_tile_info(str(full_path))


@router.get("/tiles/{z}/{x}/{y}.png")
async def get_raster_tile(
    z: int,
    x: int,
    y: int,
    file_path: str,
    current_user: Annotated[User, Depends(get_current_user_tile_compatible)],
):
    """Return an image/png XYZ tile rendered from the given raster file_path.

    Cesium cannot send Bearer headers — append ``?token=${access_token}`` to the URL.
    """
    full_path = _resolve_raster_path(file_path, current_user.id)
    if not full_path.exists():
        # Also allow absolute paths under cache dirs
        settings = get_settings()
        candidate = Path(file_path)
        if candidate.exists():
            full_path = candidate
        else:
            raise HTTPException(status_code=404, detail="Raster file not found")

    try:
        service = RasterService()
        png_bytes = service.render_tile(str(full_path), z, x, y)
        return Response(content=png_bytes, media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Raster file not found")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Tile generation failed: {exc}")


@router.get("/tiles/scene/{scene_id}/{z}/{x}/{y}.png")
async def get_scene_tile(
    scene_id: str,
    z: int,
    x: int,
    y: int,
    current_user: Annotated[User, Depends(get_current_user_tile_compatible)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Scene XYZ tiles for Cesium — append ``?token=${access_token}`` to the URL."""
    scene_service = SceneService(db)
    cached = await scene_service.get_cached_scene(current_user.id, scene_id)
    if not cached or not cached.file_path or not Path(cached.file_path).exists():
        raise HTTPException(status_code=404, detail="Cached scene not found")

    try:
        service = RasterService()
        png_bytes = service.render_tile(cached.file_path, z, x, y)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Tile generation failed: {exc}")


@router.post("/upload")
async def upload_raster(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    upload_dir = settings.upload_dir / str(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest = upload_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    service = RasterService()
    info = service.get_tile_info(str(dest))
    return {"file_path": str(dest), "info": info}


@router.post("/convert-cog")
async def convert_to_cog(
    file_path: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    full_path = _resolve_raster_path(file_path, current_user.id)
    if not full_path.exists():
        full_path = Path(file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    service = RasterService()
    cog_path = service.convert_to_cog(str(full_path))
    return {"cog_path": cog_path}


@router.post("/import/geojson")
async def import_geojson(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON file")

    return {"geojson": data, "feature_count": len(data.get("features", [data]))}


@router.post("/import/shapefile")
async def import_shapefile(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    temp_dir = settings.upload_dir / str(current_user.id) / "shapefiles"
    temp_dir.mkdir(parents=True, exist_ok=True)

    zip_path = temp_dir / file.filename
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        import geopandas as gpd

        gdf = gpd.read_file(str(zip_path))
        geojson = json.loads(gdf.to_json())
        return {"geojson": geojson, "feature_count": len(gdf)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Shapefile import failed: {exc}")


@router.post("/export/geojson")
async def export_geojson(
    geojson: dict,
    filename: str = "export.geojson",
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    export_dir = settings.upload_dir / str(current_user.id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / filename

    with open(export_path, "w") as f:
        json.dump(geojson, f)

    return FileResponse(str(export_path), filename=filename, media_type="application/geo+json")


@router.post("/export/shapefile")
async def export_shapefile(
    geojson: dict,
    filename: str = "export.zip",
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Export GeoJSON features as a zipped shapefile."""
    settings = get_settings()
    export_dir = settings.upload_dir / str(current_user.id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    try:
        import geopandas as gpd
        from shapely.geometry import shape

        features = geojson.get("features", [geojson] if geojson.get("type") == "Feature" else [])
        if not features:
            raise HTTPException(status_code=400, detail="No features to export")

        rows = []
        for feat in features:
            geom = feat.get("geometry")
            if not geom:
                continue
            props = dict(feat.get("properties") or {})
            props["geometry"] = shape(geom)
            rows.append(props)

        if not rows:
            raise HTTPException(status_code=400, detail="No valid geometries")

        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        stem = Path(filename).stem or "export"
        shp_dir = export_dir / f"{stem}_shp"
        if shp_dir.exists():
            shutil.rmtree(shp_dir)
        shp_dir.mkdir(parents=True, exist_ok=True)
        shp_path = shp_dir / f"{stem}.shp"
        gdf.to_file(str(shp_path))

        zip_base = export_dir / stem
        zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=str(shp_dir)))
        shutil.rmtree(shp_dir, ignore_errors=True)

        return FileResponse(
            str(zip_path),
            filename=f"{stem}.zip",
            media_type="application/zip",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Shapefile export failed: {exc}")

