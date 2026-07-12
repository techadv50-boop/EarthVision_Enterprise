"""Raster processing, tile generation, and COG support.

Band layout for EarthVision synthetic / Sentinel-2-like scenes:
  1 = Blue  (B2)
  2 = Green (B3)
  3 = Red   (B4)
  4 = NIR   (B8)
  5 = SWIR1 (B11)
  6 = SWIR2 (B12)

Legacy 4-band layouts are also supported (1=R, 2=G, 3=B, 4=NIR or 1=B,2=G,3=R,4=NIR).
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from app.core.config import get_settings


class RasterService:
    """Spectral index computation, AOI masking, tiling, and COG conversion."""

    # Documented band roles for 6-band scenes
    BAND_BLUE = 1
    BAND_GREEN = 2
    BAND_RED = 3
    BAND_NIR = 4
    BAND_SWIR1 = 5
    BAND_SWIR2 = 6

    def __init__(self):
        self.settings = get_settings()

    def _read_bands(
        self, src, aoi_geojson: Optional[str] = None
    ) -> tuple[dict[str, np.ndarray], object]:
        """Read spectral bands, optionally clipped to AOI. Returns (bands_dict, profile-like info)."""
        import rasterio
        from rasterio.mask import mask as rio_mask
        from shapely.geometry import mapping, shape

        profile = src.profile.copy()
        transform = src.transform

        if aoi_geojson:
            try:
                data = json.loads(aoi_geojson)
                if data.get("type") == "Feature":
                    geoms = [mapping(shape(data["geometry"]))]
                elif data.get("type") == "FeatureCollection":
                    geoms = [mapping(shape(f["geometry"])) for f in data.get("features", [])]
                else:
                    geoms = [mapping(shape(data))]

                out_image, transform = rio_mask(src, geoms, crop=True, filled=True, nodata=0)
                profile.update(
                    {
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": transform,
                    }
                )
                stack = out_image.astype(float)
            except Exception as exc:
                logger.warning(f"AOI mask failed, using full raster: {exc}")
                stack = src.read().astype(float)
        else:
            stack = src.read().astype(float)

        n = stack.shape[0]
        bands: dict[str, np.ndarray] = {}

        if n >= 6:
            # Canonical 6-band: B,G,R,NIR,SWIR1,SWIR2
            bands["blue"] = stack[0]
            bands["green"] = stack[1]
            bands["red"] = stack[2]
            bands["nir"] = stack[3]
            bands["swir1"] = stack[4]
            bands["swir2"] = stack[5]
        elif n >= 4:
            # Assume B,G,R,NIR (matches synthetic historically written as 4-band BGRN)
            # Also works if layout is R,G,B,NIR — NDVI still meaningful via red/nir pair.
            bands["blue"] = stack[0]
            bands["green"] = stack[1]
            bands["red"] = stack[2]
            bands["nir"] = stack[3]
            bands["swir1"] = stack[2]  # fallback approximations
            bands["swir2"] = stack[0]
        elif n >= 3:
            bands["red"] = stack[0]
            bands["green"] = stack[1]
            bands["blue"] = stack[2]
            bands["nir"] = stack[0]
            bands["swir1"] = stack[1]
            bands["swir2"] = stack[2]
        else:
            raise ValueError("Scene requires at least 3 bands for index computation")

        return bands, profile

    def compute_index(
        self,
        file_path: str,
        index_type: str,
        aoi_geojson: Optional[str] = None,
    ) -> tuple[np.ndarray, dict[str, float]]:
        import rasterio

        index_type = index_type.upper()
        supported = {"NDVI", "NDWI", "NDBI", "SAVI", "BSI", "LST"}
        if index_type not in supported:
            raise ValueError(f"Unsupported index: {index_type}. Supported: {sorted(supported)}")

        with rasterio.open(file_path) as src:
            if src.count < 3:
                raise ValueError("Scene requires at least 3 bands for index computation")
            bands, _ = self._read_bands(src, aoi_geojson)

        red = bands["red"]
        green = bands["green"]
        blue = bands["blue"]
        nir = bands["nir"]
        swir1 = bands["swir1"]
        swir2 = bands["swir2"]

        eps = 1e-10

        if index_type == "NDVI":
            result = (nir - red) / (nir + red + eps)
        elif index_type == "NDWI":
            result = (green - nir) / (green + nir + eps)
        elif index_type == "NDBI":
            # Built-up: (SWIR1 - NIR) / (SWIR1 + NIR) when SWIR1 available
            result = (swir1 - nir) / (swir1 + nir + eps)
        elif index_type == "SAVI":
            L = 0.5
            result = ((nir - red) / (nir + red + L + eps)) * (1 + L)
        elif index_type == "BSI":
            result = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue) + eps)
        elif index_type == "LST":
            # Land Surface Temperature approximation (°C-like scale).
            # Uses NIR/SWIR emissivity proxy + brightness temperature proxy from red/SWIR.
            # Formula adapted for broadband optical when no dedicated TIRS band exists.
            ndvi = (nir - red) / (nir + red + eps)
            ndvi = np.clip(ndvi, -1, 1)
            # Proportion of vegetation
            pv = np.square(np.clip((ndvi - (-0.05)) / (0.7 - (-0.05) + eps), 0, 1))
            # Emissivity estimate
            emissivity = 0.004 * pv + 0.986
            # Brightness temperature proxy from SWIR/NIR ratio scaled to Kelvin-ish then °C
            bt = 273.15 + 20.0 + 25.0 * ((swir1 - nir) / (swir1 + nir + eps))
            # Simplified Planck inversion proxy
            result = bt / (1 + (0.00115 * bt / 1.4388) * np.log(emissivity + eps)) - 273.15
            # Soft clip to plausible surface temps
            result = np.clip(result, -40, 70)
        else:
            raise ValueError(f"Unsupported index: {index_type}")

        if index_type != "LST":
            result = np.clip(result, -1, 1)

        valid = result[np.isfinite(result)]
        if valid.size == 0:
            stats = {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0, "median": 0.0}
        else:
            stats = {
                "min": float(np.min(valid)),
                "max": float(np.max(valid)),
                "mean": float(np.mean(valid)),
                "std": float(np.std(valid)),
                "median": float(np.median(valid)),
            }

        return result, stats

    def save_index_raster(
        self, index_data: np.ndarray, source_path: str, index_type: str, job_id: int
    ) -> str:
        import rasterio

        output_dir = self.settings.imagery_cache_dir / "indices"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"index_{index_type}_{job_id}.tif"

        with rasterio.open(source_path) as src:
            profile = src.profile.copy()
            profile.update(
                dtype="float32",
                count=1,
                compress="deflate",
                tiled=True,
                height=index_data.shape[0],
                width=index_data.shape[1],
            )
            # If AOI-clipped, dimensions may differ; keep transform from source unless sizes match
            if index_data.shape[0] != src.height or index_data.shape[1] != src.width:
                # Write with updated dimensions; transform may be approximate for clipped AOI
                profile.update(height=index_data.shape[0], width=index_data.shape[1])

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(index_data.astype(np.float32), 1)

        return str(output_path)

    def compute_histogram(self, data: np.ndarray, bins: int = 50) -> dict:
        valid = data[np.isfinite(data)]
        if valid.size == 0:
            return {
                "bins": [0.0] * (bins + 1),
                "counts": [0] * bins,
                "min_value": 0.0,
                "max_value": 0.0,
                "mean": 0.0,
                "std": 0.0,
            }
        counts, bin_edges = np.histogram(valid, bins=bins)
        return {
            "bins": bin_edges.tolist(),
            "counts": counts.tolist(),
            "min_value": float(np.min(valid)),
            "max_value": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid)),
        }

    def get_tile_info(self, file_path: str) -> dict:
        import rasterio

        with rasterio.open(file_path) as src:
            return {
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "crs": str(src.crs),
                "bounds": list(src.bounds),
                "transform": list(src.transform)[:6],
                "dtype": str(src.dtypes[0]),
                "band_descriptions": [
                    src.descriptions[i] or f"band_{i+1}" for i in range(src.count)
                ],
            }

    def convert_to_cog(self, input_path: str) -> str:
        """Write a full-resolution Cloud Optimized GeoTIFF with overviews."""
        import rasterio
        from rasterio.enums import Resampling

        output_path = Path(input_path).with_suffix(".cog.tif")

        with rasterio.open(input_path) as src:
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress="deflate",
                interleave="band",
                BIGTIFF="IF_SAFER",
            )

            with rasterio.open(output_path, "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    dst.write(src.read(i), i)
                    if src.descriptions[i - 1]:
                        dst.set_band_description(i, src.descriptions[i - 1])

                # Build internal overviews on the written COG
                factors = []
                max_dim = max(src.width, src.height)
                level = 2
                while max_dim // level >= 256:
                    factors.append(level)
                    level *= 2
                if not factors:
                    factors = [2, 4]
                dst.build_overviews(factors, Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")

        return str(output_path)

    def render_tile(self, file_path: str, z: int, x: int, y: int) -> bytes:
        """Render a slippy-map PNG tile for the given z/x/y from a raster file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Raster not found: {file_path}")

        # Prefer rio-tiler when available
        try:
            from rio_tiler.io import Reader

            with Reader(str(path)) as src:
                img = src.tile(x, y, z)
                # Colorize single-band; RGB for multi-band
                if img.data.shape[0] == 1:
                    data = img.data[0]
                    valid = data[np.isfinite(data)]
                    if valid.size:
                        lo, hi = np.percentile(valid, (2, 98))
                    else:
                        lo, hi = 0.0, 1.0
                    if hi <= lo:
                        hi = lo + 1
                    stretched = np.clip((data - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
                    from PIL import Image

                    # Simple RdYlGn-ish colormap for indices
                    cmap = self._index_colormap(stretched)
                    buf = io.BytesIO()
                    Image.fromarray(cmap, mode="RGBA").save(buf, format="PNG")
                    return buf.getvalue()

                content = img.render(imgformat="PNG")
                return content
        except Exception as exc:
            logger.debug(f"rio-tiler tile failed ({exc}); falling back to manual windowed read")

        return self._manual_render_tile(str(path), z, x, y)

    def _manual_render_tile(self, file_path: str, z: int, x: int, y: int) -> bytes:
        """Manual XYZ tile via windowed read + Pillow when rio-tiler is unavailable."""
        import rasterio
        from PIL import Image
        from rasterio.windows import from_bounds as window_from_bounds
        from rasterio.warp import transform_bounds

        # Web Mercator tile bounds
        n = 2.0**z
        lon_left = x / n * 360.0 - 180.0
        lon_right = (x + 1) / n * 360.0 - 180.0
        lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

        with rasterio.open(file_path) as src:
            try:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, lon_left, lat_bottom, lon_right, lat_top
                )
            except Exception:
                left, bottom, right, top = lon_left, lat_bottom, lon_right, lat_top

            window = window_from_bounds(left, bottom, right, top, transform=src.transform)
            window = window.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
            if window.width <= 0 or window.height <= 0:
                img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()

            count = min(src.count, 3)
            data = src.read(
                list(range(1, count + 1)),
                window=window,
                out_shape=(count, 256, 256),
                resampling=rasterio.enums.Resampling.bilinear,
            )

        if data.shape[0] == 1:
            band = data[0].astype(float)
            valid = band[np.isfinite(band)]
            lo, hi = (np.percentile(valid, (2, 98)) if valid.size else (0.0, 1.0))
            if hi <= lo:
                hi = lo + 1
            stretched = np.clip((band - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            rgba = self._index_colormap(stretched)
            image = Image.fromarray(rgba, mode="RGBA")
        else:
            # For 6-band: use R,G,B = bands 3,2,1 if available via reading first 3 incorrectly;
            # re-open preference: if original had >=3, we already read 1..3 which for 6-band is B,G,R
            # Swap to RGB display order when 3 bands were BGR-ordered
            if data.shape[0] >= 3:
                # Assume band order B,G,R for display -> rearrange to R,G,B
                display = np.stack([data[2], data[1], data[0]], axis=0)
            else:
                display = data

            rgb = np.zeros((256, 256, 3), dtype=np.uint8)
            for i in range(min(3, display.shape[0])):
                band = display[i].astype(float)
                valid = band[np.isfinite(band) & (band > 0)]
                if valid.size:
                    lo, hi = np.percentile(valid, (2, 98))
                else:
                    lo, hi = 0.0, 1.0
                if hi <= lo:
                    hi = lo + 1
                rgb[:, :, i] = np.clip((band - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            image = Image.fromarray(rgb, mode="RGB")

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _index_colormap(gray: np.ndarray) -> np.ndarray:
        """Map uint8 grayscale to an RGBA RdYlGn-like palette."""
        h, w = gray.shape
        t = gray.astype(np.float64) / 255.0
        r = np.clip(1.5 - 2.0 * t, 0, 1)
        g = np.clip(1.0 - 2.0 * np.abs(t - 0.5), 0, 1) * 0.9 + 0.1
        b = np.clip(2.0 * t - 0.5, 0, 1)
        alpha = np.where(gray > 0, 220, 0).astype(np.uint8)
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[:, :, 0] = (r * 255).astype(np.uint8)
        rgba[:, :, 1] = (g * 255).astype(np.uint8)
        rgba[:, :, 2] = (b * 255).astype(np.uint8)
        rgba[:, :, 3] = alpha
        return rgba
