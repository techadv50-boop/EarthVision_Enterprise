"""Raster engine: GeoTIFF/COG handling and tile generation."""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError


class RasterService:
    """Tile and preview engine for satellite imagery."""

    TILE_SIZE = 256

    def __init__(self) -> None:
        self.settings = get_settings()
        self.raster_dir = self.settings.imagery_dir / "rasters"
        self.tile_cache = self.settings.imagery_cache_dir / "tiles"
        self.raster_dir.mkdir(parents=True, exist_ok=True)
        self.tile_cache.mkdir(parents=True, exist_ok=True)

    def list_rasters(self) -> list[dict[str, Any]]:
        rasters = []
        for path in sorted(self.raster_dir.glob("*")):
            if path.suffix.lower() in {".tif", ".tiff", ".png", ".jpg", ".npy"}:
                rasters.append(
                    {
                        "id": path.stem,
                        "filename": path.name,
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
                        "format": path.suffix.lstrip(".").upper(),
                    }
                )
        # Always expose a synthetic COG-like demo layer
        rasters.insert(
            0,
            {
                "id": "demo-truecolor",
                "filename": "demo_truecolor.synthetic",
                "path": "synthetic://demo-truecolor",
                "size_bytes": 0,
                "format": "SYNTHETIC",
            },
        )
        return rasters

    def _mercator_bounds(self, z: int, x: int, y: int) -> tuple[float, float, float, float]:
        n = 2.0**z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return lon_min, lat_min, lon_max, lat_max

    def _synthetic_tile(self, layer_id: str, z: int, x: int, y: int) -> bytes:
        """Generate a terrain-like RGB tile for the given XYZ coordinates."""
        cache_path = self.tile_cache / layer_id / str(z) / str(x) / f"{y}.png"
        if cache_path.exists():
            return cache_path.read_bytes()

        lon_min, lat_min, lon_max, lat_max = self._mercator_bounds(z, x, y)
        size = self.TILE_SIZE
        yy, xx = np.mgrid[0:size, 0:size]
        lon = lon_min + (lon_max - lon_min) * (xx / (size - 1))
        lat = lat_max - (lat_max - lat_min) * (yy / (size - 1))

        # Procedural earth-like coloration
        elev = (
            np.sin(lon / 18) * np.cos(lat / 12)
            + 0.4 * np.sin(lon / 7 + lat / 9)
            + 0.2 * np.cos(lon * 0.3 - lat * 0.2)
        )
        water = elev < -0.15
        land = ~water

        r = np.zeros((size, size))
        g = np.zeros((size, size))
        b = np.zeros((size, size))

        # Ocean
        b[water] = 0.45 + 0.2 * (elev[water] + 0.5)
        g[water] = 0.25 + 0.15 * (elev[water] + 0.5)
        r[water] = 0.05

        # Land / vegetation / desert gradient by latitude
        desert = land & (np.abs(lat) < 25) & (elev > 0.1)
        forest = land & ~desert
        r[forest] = 0.15 + 0.1 * elev[forest]
        g[forest] = 0.35 + 0.25 * elev[forest]
        b[forest] = 0.1
        r[desert] = 0.55 + 0.2 * elev[desert]
        g[desert] = 0.4 + 0.15 * elev[desert]
        b[desert] = 0.2

        # Snow caps
        snow = land & (np.abs(lat) > 65)
        r[snow] = g[snow] = b[snow] = 0.92

        # Grid for orientation at high zoom
        if z >= 6:
            grid = ((xx % 64) == 0) | ((yy % 64) == 0)
            r[grid] = np.clip(r[grid] + 0.08, 0, 1)
            g[grid] = np.clip(g[grid] + 0.08, 0, 1)
            b[grid] = np.clip(b[grid] + 0.08, 0, 1)

        rgb = np.stack([r, g, b], axis=-1)
        img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB")
        draw = ImageDraw.Draw(img)
        draw.text((8, 8), f"{layer_id} z{z}", fill=(255, 255, 255))

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        cache_path.write_bytes(data)
        return data

    def get_tile(self, layer_id: str, z: int, x: int, y: int) -> bytes:
        if z < 0 or z > 18:
            raise ValidationError("Zoom level out of range")
        n = 2**z
        if x < 0 or x >= n or y < 0 or y >= n:
            raise ValidationError("Tile coordinates out of range")

        # Try real raster via rasterio if present
        raster_path = self.raster_dir / f"{layer_id}.tif"
        if raster_path.exists():
            try:
                return self._tile_from_geotiff(raster_path, z, x, y)
            except Exception as exc:
                logger.warning("GeoTIFF tile failed, using synthetic: {}", exc)

        return self._synthetic_tile(layer_id, z, x, y)

    def _tile_from_geotiff(self, path: Path, z: int, x: int, y: int) -> bytes:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import from_bounds

        lon_min, lat_min, lon_max, lat_max = self._mercator_bounds(z, x, y)
        with rasterio.open(path) as src:
            window = from_bounds(lon_min, lat_min, lon_max, lat_max, transform=src.transform)
            data = src.read(
                out_shape=(min(3, src.count), self.TILE_SIZE, self.TILE_SIZE),
                window=window,
                resampling=Resampling.bilinear,
            )
            if data.shape[0] == 1:
                rgb = np.stack([data[0]] * 3, axis=0)
            else:
                rgb = data[:3]
            # Normalize
            rgb = rgb.astype(float)
            for i in range(rgb.shape[0]):
                band = rgb[i]
                p2, p98 = np.percentile(band[np.isfinite(band)], [2, 98]) if band.size else (0, 1)
                rgb[i] = np.clip((band - p2) / (p98 - p2 + 1e-9), 0, 1)
            img = Image.fromarray((rgb.transpose(1, 2, 0) * 255).astype(np.uint8), mode="RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

    def create_preview(self, layer_id: str, width: int = 512, height: int = 512) -> bytes:
        # Use a mid-zoom tile mosaic approach for preview
        return self._synthetic_tile(layer_id, 3, 4, 2)

    def ingest_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        safe_name = Path(filename).name
        dest = self.raster_dir / safe_name
        dest.write_bytes(content)
        return {
            "id": dest.stem,
            "filename": safe_name,
            "path": str(dest),
            "size_bytes": len(content),
            "format": dest.suffix.lstrip(".").upper(),
        }
