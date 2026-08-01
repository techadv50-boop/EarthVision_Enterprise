"""Unsupervised land-cover classification routes."""

from __future__ import annotations

import base64

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import CurrentUser
from app.schemas.classification import ClassificationRequest, ClassificationResponse
from app.services.classification_service import ClassificationService

router = APIRouter(prefix="/analytics", tags=["Classification"])


@router.post("/classify", response_model=ClassificationResponse)
async def classify_unsupervised(
    data: ClassificationRequest, user: CurrentUser
) -> ClassificationResponse:
    """Ensemble unsupervised classification into Snow / Soil / Vegetation / Water."""
    return ClassificationService().classify(data)


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
                f'attachment; filename="lulc4_{data.scene_id}.png"'
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
                f'attachment; filename="lulc4_{data.scene_id}_areas.csv"'
            )
        },
    )


@router.post("/export/classify.tif")
async def export_classify_geotiff(
    data: ClassificationRequest, user: CurrentUser
) -> Response:
    from app.services.geotiff_export import png_bytes_to_geotiff

    result = ClassificationService().classify(data)
    tif, filename = png_bytes_to_geotiff(
        base64.b64decode(result.overlay_base64),
        list(result.bounds),
        filename=f"lulc4_{data.scene_id}.tif",
    )
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
