"""Terrain / DEM analysis routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.terrain import TerrainComputeRequest, TerrainComputeResponse
from app.services.terrain_service import TerrainService

router = APIRouter(prefix="/terrain", tags=["Terrain"])


@router.get("/products")
async def list_products(user: CurrentUser) -> list[dict]:
    return [
        {"id": "dem", "name": "DEM Visualization", "group": "surface"},
        {"id": "slope", "name": "Slope", "group": "surface", "legend": True},
        {"id": "aspect", "name": "Aspect", "group": "surface", "legend": True},
        {"id": "hillshade", "name": "Hillshade", "group": "surface", "legend": True},
        {"id": "contour", "name": "Contour generation", "group": "surface"},
        {"id": "watershed", "name": "Watershed / drainage", "group": "hydro"},
        {"id": "viewshed", "name": "Viewshed analysis", "group": "visibility"},
        {"id": "profile", "name": "3D elevation profile", "group": "visibility"},
        {"id": "line_of_sight", "name": "Line of sight", "group": "visibility"},
    ]


@router.post("/compute", response_model=TerrainComputeResponse)
async def compute_terrain(
    data: TerrainComputeRequest, user: CurrentUser
) -> TerrainComputeResponse:
    return TerrainService().compute(data)
