"""Unsupervised land-cover classification routes."""

from __future__ import annotations

import base64

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.schemas.classification import (
    ClassificationRequest,
    ClassificationResponse,
    RecolorRequest,
    RecolorResponse,
)
from app.services.classification_service import ClassificationService

router = APIRouter(prefix="/analytics", tags=["Classification"])


@router.post("/classify", response_model=ClassificationResponse)
async def classify_unsupervised(
    data: ClassificationRequest, user: CurrentUser
) -> ClassificationResponse:
    """Ensemble unsupervised classification (3–8 classes, user colors)."""
    from app.core.concurrency import run_sync_timeout

    return await run_sync_timeout(
        ClassificationService().classify,
        data,
        timeout_s=55.0,
        label="Classification",
    )


@router.post("/classify/recolor", response_model=RecolorResponse)
async def recolor_classification(
    data: RecolorRequest, user: CurrentUser
) -> RecolorResponse:
    """Apply new colors to an existing class map without re-running classification."""
    from app.core.concurrency import run_sync_timeout

    return await run_sync_timeout(
        ClassificationService().recolor,
        data,
        timeout_s=30.0,
        label="Classification recolor",
    )


@router.post("/export/classify.png")
async def export_classify_png(
    data: ClassificationRequest, user: CurrentUser
) -> Response:
    result = ClassificationService().classify(data)
    return Response(
        content=base64.b64decode(result.overlay_base64),
        media_type="image/png",
        headers={
            "Content-Disposition": (
                f'attachment; filename="lulc{data.n_classes}_{data.scene_id}.png"'
            )
        },
    )


@router.post("/export/classify.csv")
async def export_classify_csv(
    data: ClassificationRequest, user: CurrentUser
) -> Response:
    service = ClassificationService()
    result = service.classify(data)
    csv_text = service.results_csv(result)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="lulc{data.n_classes}_{data.scene_id}_areas.csv"'
            )
        },
    )


@router.post("/export/classify.tif")
async def export_classify_geotiff(
    data: ClassificationRequest, user: CurrentUser
) -> Response:
    from app.services.geotiff_export import png_bytes_to_geotiff
    from app.services.map_cartography import decorate_classification_map

    result = ClassificationService().classify(data)
    legend = [
        {
            "label": c.label,
            "name": c.name,
            "color": c.color,
            "area_km2": c.area_km2,
        }
        for c in result.classes
    ]
    png, bounds = decorate_classification_map(
        base64.b64decode(result.overlay_base64),
        list(result.bounds),
        legend,
        title=f"Land Cover Classification ({data.n_classes}-class)",
        total_area_km2=float(result.total_area_km2),
    )
    tif, filename = png_bytes_to_geotiff(
        png,
        bounds,
        filename=f"lulc{data.n_classes}_{data.scene_id}.tif",
    )
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
