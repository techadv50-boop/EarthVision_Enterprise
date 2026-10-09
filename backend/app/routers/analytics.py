"""Analytics routes."""

from __future__ import annotations

import base64
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser
from app.schemas.analytics import (
    IndexChangeRequest,
    IndexChangeResponse,
    IndexComputeRequest,
    IndexComputeResponse,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
)
from app.services.analytics_service import INDEX_META, AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class LegendItemExport(BaseModel):
    """Legend row for cartographic GeoTIFF decoration."""

    label: str
    color: str
    area_km2: float | None = None
    name: str | None = None


class GeoTiffExportRequest(BaseModel):
    """Convert any procedure overlay (or regenerate) into a GeoTIFF download."""

    bounds: list[float] = Field(..., description="[west,south,east,north]")
    filename: str = "sateye_overlay.tif"
    overlay_base64: str | None = None
    # Optional regenerate shortcuts (used when overlay_base64 omitted)
    procedure: Literal[
        "overlay",
        "composite",
        "index",
        "stretch",
        "change",
        "classify",
    ] = "overlay"
    scene_id: str | None = None
    before_scene_id: str | None = None
    after_scene_id: str | None = None
    preset: str | None = "true_color"
    index: str | None = "NDVI"
    colormap: str | None = None
    p_low: float = 2.0
    p_high: float = 98.0
    dem_grid: list[list[float]] | None = None
    # Cartography (classification map sheets)
    decorate: bool = False
    title: str | None = None
    legend_items: list[LegendItemExport] | None = None
    total_area_km2: float | None = None
    # When true, return the (optionally decorated) PNG instead of GeoTIFF
    as_png: bool = False



@router.post("/index", response_model=IndexComputeResponse)
async def compute_index(
    data: IndexComputeRequest, user: CurrentUser
) -> IndexComputeResponse:
    from app.core.concurrency import run_sync_timeout

    service = AnalyticsService()
    return await run_sync_timeout(
        service.compute_index, data, timeout_s=55.0, label="Spectral index"
    )


@router.post("/change", response_model=IndexChangeResponse)
async def index_change_detection(
    data: IndexChangeRequest, user: CurrentUser
) -> IndexChangeResponse:
    from app.core.concurrency import run_sync_timeout

    service = AnalyticsService()
    return await run_sync_timeout(
        service.change_detection, data, timeout_s=55.0, label="Change detection"
    )


@router.post("/timeseries", response_model=TimeSeriesResponse)
async def time_series(
    data: TimeSeriesRequest, user: CurrentUser
) -> TimeSeriesResponse:
    from app.core.concurrency import run_sync_timeout

    service = AnalyticsService()
    return await run_sync_timeout(
        service.time_series, data, timeout_s=55.0, label="Time series"
    )


@router.post("/pixel", response_model=PixelInspectResponse)
async def inspect_pixel(
    data: PixelInspectRequest, user: CurrentUser
) -> PixelInspectResponse:
    from app.core.concurrency import run_sync_timeout

    service = AnalyticsService()
    return await run_sync_timeout(
        service.inspect_pixel, data, timeout_s=30.0, label="Pixel inspect"
    )


@router.get("/indices")
async def list_indices(user: CurrentUser) -> list[dict]:
    return [
        {
            "id": key,
            "name": meta["label"],
            "formula": meta["formula"],
            "reference": meta["ref"],
            "unit": meta["unit"],
            "default_colormap": meta.get("cmap"),
        }
        for key, meta in INDEX_META.items()
    ]


@router.get("/colormaps")
async def list_colormaps(user: CurrentUser) -> list[dict]:
    """Available color ramps for spectral index overlays."""
    return AnalyticsService().list_colormaps()


@router.get("/export/index.png")
async def export_index_png(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    colormap: str | None = None,
) -> Response:
    service = AnalyticsService()
    result = service.compute_index(
        IndexComputeRequest(
            index=index,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
            colormap=colormap,  # type: ignore[arg-type]
        )
    )
    assert result.overlay_base64
    import base64

    return Response(
        content=base64.b64decode(result.overlay_base64),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{index}_{scene_id}.png"'
        },
    )


@router.get("/export/index.csv")
async def export_index_csv(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
) -> Response:
    service = AnalyticsService()
    result = service.compute_index(
        IndexComputeRequest(index=index, scene_id=scene_id)  # type: ignore[arg-type]
    )
    rows = [
        "metric,value",
        f"index,{result.index}",
        f"formula,\"{result.formula}\"",
        f"mean,{result.mean}",
        f"std,{result.std}",
        f"min,{result.min}",
        f"max,{result.max}",
        f"median,{result.median}",
        f"p25,{result.percentile_25}",
        f"p75,{result.percentile_75}",
        f"valid_pixels,{result.valid_pixels}",
    ]
    return Response(
        content="\n".join(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{index}_{scene_id}_stats.csv"'
        },
    )


@router.get("/export/index.tif")
async def export_index_geotiff(
    user: CurrentUser,
    index: str = "NDVI",
    scene_id: str = "export",
    west: float = 74.15,
    south: float = 31.35,
    east: float = 74.55,
    north: float = 31.7,
    colormap: str | None = None,
) -> Response:
    from app.services.geotiff_export import png_bytes_to_geotiff

    service = AnalyticsService()
    result = service.compute_index(
        IndexComputeRequest(
            index=index,  # type: ignore[arg-type]
            scene_id=scene_id,
            bbox=[west, south, east, north],
            colormap=colormap,  # type: ignore[arg-type]
        )
    )
    assert result.overlay_base64
    tif, filename = png_bytes_to_geotiff(
        base64.b64decode(result.overlay_base64),
        list(result.bounds or [west, south, east, north]),
        filename=f"{index}_{scene_id}.tif",
    )
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/geotiff")
async def export_geotiff(data: GeoTiffExportRequest, user: CurrentUser) -> Response:
    """Universal GeoTIFF download for any procedure overlay.

    Prefer sending the already-rendered ``overlay_base64`` + ``bounds`` so the
    exact map result is exported. Otherwise set ``procedure`` to regenerate.
    """
    from app.schemas.composite import CompositeRequest, StretchRequest
    from app.services.composite_service import COMPOSITE_PRESETS, CompositeService
    from app.services.geotiff_export import (
        decode_overlay_png,
        dem_grid_to_geotiff,
        png_bytes_to_geotiff,
    )

    bounds = [float(x) for x in data.bounds]

    if data.dem_grid:
        tif, filename = dem_grid_to_geotiff(
            data.dem_grid, bounds, filename=data.filename or "dem.tif"
        )
        return Response(
            content=tif,
            media_type="image/tiff",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    png: bytes | None = None
    if data.overlay_base64:
        png = decode_overlay_png(overlay_base64=data.overlay_base64)
    elif data.procedure == "composite":
        preset = data.preset if data.preset in COMPOSITE_PRESETS else "true_color"
        result = CompositeService().render_composite(
            CompositeRequest(
                preset=preset,  # type: ignore[arg-type]
                scene_id=data.scene_id,
                bbox=bounds,
            )
        )
        png = base64.b64decode(result.overlay_base64)
        bounds = list(result.bounds)
    elif data.procedure == "stretch":
        result = CompositeService().stretch_scene(
            StretchRequest(
                scene_id=data.scene_id,
                bbox=bounds,
                p_low=data.p_low,
                p_high=data.p_high,
            )
        )
        png = base64.b64decode(result.overlay_base64)
        bounds = list(result.bounds)
    elif data.procedure == "index":
        result = AnalyticsService().compute_index(
            IndexComputeRequest(
                index=(data.index or "NDVI"),  # type: ignore[arg-type]
                scene_id=data.scene_id or "export",
                bbox=bounds,
                colormap=data.colormap,  # type: ignore[arg-type]
            )
        )
        assert result.overlay_base64
        png = base64.b64decode(result.overlay_base64)
        bounds = list(result.bounds or bounds)
    elif data.procedure == "change":
        if not data.before_scene_id or not data.after_scene_id:
            from app.core.exceptions import ValidationError

            raise ValidationError("before_scene_id and after_scene_id required for change GeoTIFF")
        result = AnalyticsService().change_detection(
            IndexChangeRequest(
                before_scene_id=data.before_scene_id,
                after_scene_id=data.after_scene_id,
                index=(data.index or "NDVI"),  # type: ignore[arg-type]
                bbox=bounds,
            )
        )
        png = base64.b64decode(result.overlay_base64)
        bounds = list(result.bounds)
    elif data.procedure == "classify":
        from app.schemas.classification import ClassificationRequest
        from app.services.classification_service import ClassificationService

        if not data.scene_id:
            from app.core.exceptions import ValidationError

            raise ValidationError("scene_id required for classify GeoTIFF")
        result = ClassificationService().classify(
            ClassificationRequest(scene_id=data.scene_id, bbox=bounds)
        )
        png = base64.b64decode(result.overlay_base64)
        bounds = list(result.bounds)
        if not data.legend_items:
            data.legend_items = [
                LegendItemExport(
                    label=c.label,
                    name=c.name,
                    color=c.color,
                    area_km2=c.area_km2,
                )
                for c in result.classes
            ]
        if data.total_area_km2 is None:
            data.total_area_km2 = float(result.total_area_km2)
        data.decorate = True
    else:
        from app.core.exceptions import ValidationError

        raise ValidationError(
            "Provide overlay_base64 (or dem_grid), or set procedure to "
            "composite/index/stretch/change/classify"
        )

    # Decorate whenever explicitly requested OR legend/area data is supplied
    should_decorate = bool(data.decorate) or bool(data.legend_items)
    if should_decorate and png is not None:
        from app.services.map_cartography import decorate_classification_map

        legend = [item.model_dump() for item in (data.legend_items or [])]
        png, bounds = decorate_classification_map(
            png,
            bounds,
            legend,
            title=data.title or "Land Cover Classification",
            total_area_km2=data.total_area_km2,
        )

    if data.as_png:
        from app.services.geotiff_export import _safe_filename

        png_name = _safe_filename(
            (data.filename or "sateye_map").rsplit(".", 1)[0] + ".png",
            ext="png",
        )
        return Response(
            content=png,
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{png_name}"'},
        )

    tif, filename = png_bytes_to_geotiff(png, bounds, filename=data.filename)
    return Response(
        content=tif,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
