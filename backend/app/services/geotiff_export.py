"""Convert procedure overlays (PNG / arrays) into georeferenced GeoTIFF downloads."""

from __future__ import annotations

import io
import re
from typing import Any

import numpy as np
from PIL import Image

from app.core.exceptions import ValidationError


def _safe_filename(name: str, ext: str = "tif") -> str:
    """Sanitize a download filename while preserving real extensions (.tif/.tiff/.zip)."""
    base = re.sub(r"[^\w.\-]+", "_", (name or "sateye").strip())[:160] or "sateye"
    lower = base.lower()
    if lower.endswith((".tif", ".tiff", ".zip", ".png", ".jp2")):
        return base
    return f"{base}.{ext}"


def png_bytes_to_geotiff(
    png_bytes: bytes,
    bounds: list[float],
    *,
    filename: str = "overlay.tif",
) -> tuple[bytes, str]:
    """Wrap an RGBA/RGB PNG as a georeferenced GeoTIFF (EPSG:4326)."""
    if not png_bytes:
        raise ValidationError("No image data to export as GeoTIFF")
    if not bounds or len(bounds) != 4:
        raise ValidationError("bounds [west,south,east,north] are required for GeoTIFF export")

    west, south, east, north = (float(v) for v in bounds)
    if east <= west or north <= south:
        raise ValidationError("Invalid bounds for GeoTIFF export")

    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    arr = np.asarray(img)
    height, width = int(arr.shape[0]), int(arr.shape[1])
    if height < 2 or width < 2:
        raise ValidationError("Image too small for GeoTIFF export")

    try:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("rasterio is required for GeoTIFF export") from exc

    # PIL row 0 = north for our EO overlays; GeoTIFF north-up matches that.
    transform = from_bounds(west, south, east, north, width, height)
    bands = np.transpose(arr, (2, 0, 1))  # (4, H, W)

    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            height=height,
            width=width,
            count=4,
            dtype="uint8",
            crs="EPSG:4326",
            transform=transform,
            compress="lzw",
            photometric="RGB",
        ) as dst:
            dst.write(bands)
            dst.update_tags(
                AREA_OR_POINT="Area",
                TIFFTAG_SOFTWARE="SAT EYE",
            )
            # Mark alpha as undefined photometric extra band
            dst.colorinterp = [
                rasterio.enums.ColorInterp.red,
                rasterio.enums.ColorInterp.green,
                rasterio.enums.ColorInterp.blue,
                rasterio.enums.ColorInterp.alpha,
            ]
        return mem.read(), _safe_filename(filename)


def dem_grid_to_geotiff(
    dem_grid: list[list[float]] | np.ndarray,
    bounds: list[float],
    *,
    filename: str = "dem.tif",
    nodata: float = -9999.0,
) -> tuple[bytes, str]:
    """Write a float32 DEM grid as a single-band GeoTIFF."""
    if not bounds or len(bounds) != 4:
        raise ValidationError("bounds [west,south,east,north] are required for DEM GeoTIFF")
    west, south, east, north = (float(v) for v in bounds)
    arr = np.asarray(dem_grid, dtype=np.float32)
    if arr.ndim != 2 or arr.size < 4:
        raise ValidationError("DEM grid must be a 2D array")
    height, width = arr.shape

    try:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("rasterio is required for GeoTIFF export") from exc

    transform = from_bounds(west, south, east, north, width, height)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            compress="lzw",
            nodata=nodata,
        ) as dst:
            dst.write(arr, 1)
            dst.update_tags(
                AREA_OR_POINT="Area",
                TIFFTAG_SOFTWARE="SAT EYE",
                UNIT="meters",
            )
        return mem.read(), _safe_filename(filename)


def band_arrays_to_geotiff(
    bands: dict[str, np.ndarray],
    bounds: list[float],
    *,
    filename: str = "bands.tif",
    band_order: list[str] | None = None,
    nodata: float = -9999.0,
) -> tuple[bytes, str]:
    """Write selected named float bands into a multi-band GeoTIFF (EPSG:4326)."""
    if not bands:
        raise ValidationError("No bands selected for GeoTIFF export")
    if not bounds or len(bounds) != 4:
        raise ValidationError("bounds [west,south,east,north] are required")
    west, south, east, north = (float(v) for v in bounds)
    if east <= west or north <= south:
        raise ValidationError("Invalid bounds for GeoTIFF export")

    order = [b for b in (band_order or list(bands.keys())) if b in bands]
    if not order:
        raise ValidationError("Selected bands were not available")

    arrays = [np.asarray(bands[name], dtype=np.float32) for name in order]
    height, width = arrays[0].shape
    for name, arr in zip(order, arrays):
        if arr.shape != (height, width):
            raise ValidationError(f"Band '{name}' has mismatched shape {arr.shape}")

    try:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("rasterio is required for GeoTIFF export") from exc

    stacked = np.stack(arrays, axis=0)
    # NaNs → nodata for GIS tools
    stacked = np.where(np.isfinite(stacked), stacked, nodata).astype(np.float32)
    transform = from_bounds(west, south, east, north, width, height)

    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            height=height,
            width=width,
            count=len(order),
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            compress="lzw",
            nodata=nodata,
        ) as dst:
            dst.write(stacked)
            for i, name in enumerate(order, start=1):
                dst.set_band_description(i, name)
            dst.update_tags(
                AREA_OR_POINT="Area",
                TIFFTAG_SOFTWARE="SAT EYE",
                BANDS=",".join(order),
            )
        return mem.read(), _safe_filename(filename)


def decode_overlay_png(
    *,
    overlay_base64: str | None = None,
    png_bytes: bytes | None = None,
) -> bytes:
    if png_bytes:
        return png_bytes
    if overlay_base64:
        import base64

        raw = overlay_base64
        if "," in raw and raw.strip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        return base64.b64decode(raw)
    raise ValidationError("Provide overlay_base64 or png bytes")


def export_meta_tags(extra: dict[str, Any] | None = None) -> dict[str, str]:
    tags = {"TIFFTAG_SOFTWARE": "SAT EYE"}
    if extra:
        for k, v in extra.items():
            if v is None:
                continue
            tags[str(k)[:64]] = str(v)[:256]
    return tags
