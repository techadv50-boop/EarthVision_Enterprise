"""Geospatial API routes: search, bookmarks, AOI, measurements."""

import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.aoi import AreaOfInterest
from app.models.bookmark import Bookmark
from app.models.user import User
from app.schemas.geo import (
    AOICreate,
    AOIResponse,
    BookmarkCreate,
    BookmarkResponse,
    CoordinateSearch,
    LocationSearchResult,
    MeasureRequest,
)
from app.services.geocoding_service import GeocodingService

router = APIRouter(prefix="/geo", tags=["Geospatial"])


@router.get("/search", response_model=list[LocationSearchResult])
async def search_location(
    q: str = Query(min_length=1, description="Location search query"),
    limit: int = Query(default=10, ge=1, le=50),
    _user: Annotated[User, Depends(get_current_user)] = None,
):
    service = GeocodingService()
    return await service.search_location(q, limit)


@router.get("/reverse", response_model=LocationSearchResult)
async def reverse_geocode(
    longitude: float = Query(ge=-180, le=180),
    latitude: float = Query(ge=-90, le=90),
    _user: Annotated[User, Depends(get_current_user)] = None,
):
    service = GeocodingService()
    result = await service.reverse_geocode(longitude, latitude)
    if result is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return result


@router.get("/bookmarks", response_model=list[BookmarkResponse])
async def list_bookmarks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Bookmark)
        .where(Bookmark.user_id == current_user.id)
        .order_by(Bookmark.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/bookmarks", response_model=BookmarkResponse, status_code=201)
async def create_bookmark(
    data: BookmarkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    bookmark = Bookmark(user_id=current_user.id, **data.model_dump())
    db.add(bookmark)
    await db.flush()
    await db.refresh(bookmark)
    return bookmark


@router.delete("/bookmarks/{bookmark_id}", status_code=204)
async def delete_bookmark(
    bookmark_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    await db.delete(bookmark)


@router.get("/aoi", response_model=list[AOIResponse])
async def list_aois(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(AreaOfInterest)
        .where(AreaOfInterest.user_id == current_user.id)
        .order_by(AreaOfInterest.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/aoi", response_model=AOIResponse, status_code=201)
async def create_aoi(
    data: AOICreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        json.loads(data.geojson)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON")

    aoi = AreaOfInterest(user_id=current_user.id, **data.model_dump())
    db.add(aoi)
    await db.flush()
    await db.refresh(aoi)
    return aoi


@router.delete("/aoi/{aoi_id}", status_code=204)
async def delete_aoi(
    aoi_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(AreaOfInterest).where(
            AreaOfInterest.id == aoi_id, AreaOfInterest.user_id == current_user.id
        )
    )
    aoi = result.scalar_one_or_none()
    if not aoi:
        raise HTTPException(status_code=404, detail="AOI not found")
    await db.delete(aoi)


@router.post("/measure")
async def measure_geometry(
    body: Optional[MeasureRequest] = None,
    geojson: Optional[str] = Query(default=None, description="GeoJSON string (query param)"),
    _user: Annotated[User, Depends(get_current_user)] = None,
):
    """Measure area/length/perimeter. Accepts JSON body `{geojson: ...}` or `?geojson=` query."""
    from shapely.geometry import shape
    import pyproj
    from shapely.ops import transform

    raw = None
    if body is not None and body.geojson is not None:
        raw = body.geojson
    elif geojson is not None:
        raw = geojson

    if raw is None:
        raise HTTPException(status_code=400, detail="geojson is required in body or query")

    try:
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw

        if isinstance(data, dict) and data.get("type") == "Feature":
            geom = shape(data["geometry"])
        elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
            if not data.get("features"):
                raise ValueError("Empty FeatureCollection")
            geom = shape(data["features"][0]["geometry"])
        else:
            geom = shape(data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON geometry")

    # Geodesic measurements via equal-area / geodesic projection around centroid
    centroid = geom.centroid
    proj_wgs84 = pyproj.CRS("EPSG:4326")
    # Azimuthal equidistant centered on geometry for metric length/area
    aeqd = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m"
    )
    project = pyproj.Transformer.from_crs(proj_wgs84, aeqd, always_xy=True).transform
    geom_m = transform(project, geom)

    geom_type = geom.geom_type
    results = []

    if geom_type in ("Polygon", "MultiPolygon"):
        results.append({"type": "area", "value": round(geom_m.area, 2), "unit": "m²"})
        results.append({"type": "perimeter", "value": round(geom_m.length, 2), "unit": "m"})
    elif geom_type in ("LineString", "MultiLineString"):
        results.append({"type": "length", "value": round(geom_m.length, 2), "unit": "m"})
    elif geom_type == "Point":
        results.append(
            {
                "type": "point",
                "value": 0,
                "unit": "N/A",
                "coordinates": [geom.x, geom.y],
            }
        )
    else:
        results.append({"type": "length", "value": round(geom_m.length, 2), "unit": "m"})

    return {"measurements": results, "geometry_type": geom_type}
