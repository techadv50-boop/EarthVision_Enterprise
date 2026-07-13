"""Remote sensing spectral index analytics engine."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.schemas.analytics import (
    IndexComputeRequest,
    IndexComputeResponse,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesResponse,
)


class AnalyticsService:
    """Compute vegetation, water, urban, and thermal indices."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def _safe_divide(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.true_divide(a, b)
            result[~np.isfinite(result)] = np.nan
        return result

    def compute_ndvi(self, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        return self._safe_divide(nir.astype(float) - red.astype(float), nir.astype(float) + red.astype(float))

    def compute_ndwi(self, green: np.ndarray, nir: np.ndarray) -> np.ndarray:
        return self._safe_divide(
            green.astype(float) - nir.astype(float), green.astype(float) + nir.astype(float)
        )

    def compute_ndbi(self, swir: np.ndarray, nir: np.ndarray) -> np.ndarray:
        return self._safe_divide(
            swir.astype(float) - nir.astype(float), swir.astype(float) + nir.astype(float)
        )

    def compute_savi(self, red: np.ndarray, nir: np.ndarray, L: float = 0.5) -> np.ndarray:
        return self._safe_divide(
            (nir.astype(float) - red.astype(float)) * (1 + L),
            nir.astype(float) + red.astype(float) + L,
        )

    def compute_bsi(self, red: np.ndarray, green: np.ndarray, nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
        num = (swir.astype(float) + red.astype(float)) - (nir.astype(float) + green.astype(float))
        den = (swir.astype(float) + red.astype(float)) + (nir.astype(float) + green.astype(float))
        return self._safe_divide(num, den)

    def compute_lst(self, thermal: np.ndarray, ml: float = 0.00341802, al: float = 149.0) -> np.ndarray:
        """Approximate LST from Landsat thermal DN using radiance conversion + Planck."""
        radiance = thermal.astype(float) * ml + al
        # Simplified brightness temperature (K) then Celsius
        k1, k2 = 774.8853, 1321.0789
        with np.errstate(divide="ignore", invalid="ignore"):
            bt = k2 / np.log((k1 / radiance) + 1) - 273.15
            bt[~np.isfinite(bt)] = np.nan
        return bt

    def _synthetic_bands(self, size: int = 256, seed: int = 42) -> dict[str, np.ndarray]:
        """Generate realistic synthetic multi-spectral bands for demo analysis."""
        rng = np.random.default_rng(seed)
        y, x = np.mgrid[0:size, 0:size]
        # Vegetation gradient + urban patch + water body
        veg = np.clip(0.4 + 0.3 * np.sin(x / 30) * np.cos(y / 40) + rng.normal(0, 0.05, (size, size)), 0, 1)
        urban = ((x > size * 0.6) & (y < size * 0.4)).astype(float) * 0.7
        water = ((x - size * 0.3) ** 2 + (y - size * 0.7) ** 2 < (size * 0.12) ** 2).astype(float)

        red = np.clip(0.15 + 0.1 * (1 - veg) + 0.25 * urban - 0.1 * water + rng.normal(0, 0.02, (size, size)), 0, 1)
        green = np.clip(0.18 + 0.15 * veg + 0.1 * urban - 0.05 * water + rng.normal(0, 0.02, (size, size)), 0, 1)
        nir = np.clip(0.25 + 0.45 * veg + 0.05 * urban - 0.2 * water + rng.normal(0, 0.02, (size, size)), 0, 1)
        swir = np.clip(0.2 + 0.1 * (1 - veg) + 0.35 * urban - 0.15 * water + rng.normal(0, 0.02, (size, size)), 0, 1)
        thermal = np.clip(
            300 + 15 * urban - 8 * water - 5 * veg + rng.normal(0, 2, (size, size)), 250, 350
        )
        return {"red": red, "green": green, "nir": nir, "swir": swir, "thermal": thermal}

    def _load_band(self, path: str | None, fallback: np.ndarray) -> np.ndarray:
        if not path:
            return fallback
        p = Path(path)
        if not p.exists():
            logger.warning("Band path not found: {}", path)
            return fallback
        try:
            # Prefer rasterio if available
            try:
                import rasterio

                with rasterio.open(p) as src:
                    return src.read(1).astype(float)
            except ImportError:
                img = Image.open(p)
                return np.array(img.convert("F"), dtype=float)
        except Exception as exc:
            logger.warning("Failed to load band {}: {}", path, exc)
            return fallback

    def _stats(self, array: np.ndarray) -> dict[str, float | int | dict]:
        valid = array[np.isfinite(array)]
        if valid.size == 0:
            raise ValidationError("No valid pixels for index computation")
        hist_counts, hist_edges = np.histogram(valid, bins=32)
        return {
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid)),
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "median": float(np.median(valid)),
            "percentile_25": float(np.percentile(valid, 25)),
            "percentile_75": float(np.percentile(valid, 75)),
            "valid_pixels": int(valid.size),
            "histogram": {
                "counts": hist_counts.astype(float).tolist(),
                "edges": hist_edges.astype(float).tolist(),
            },
        }

    def _preview_base64(self, array: np.ndarray, cmap: str = "RdYlGn") -> str:
        valid = array[np.isfinite(array)]
        vmin, vmax = float(np.percentile(valid, 2)), float(np.percentile(valid, 98))
        norm = np.clip((array - vmin) / (vmax - vmin + 1e-9), 0, 1)
        # Simple RdYlGn-like colormap
        r = np.clip(1.5 - 2 * norm, 0, 1)
        g = np.clip(1 - 1.5 * np.abs(norm - 0.5), 0, 1)
        b = np.clip(2 * norm - 0.5, 0, 1)
        rgb = np.stack([r, g, b], axis=-1)
        rgb[~np.isfinite(array)] = 0
        img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def compute_index(self, request: IndexComputeRequest) -> IndexComputeResponse:
        bands = self._synthetic_bands(seed=hash(request.scene_id or "default") % (2**31))
        red = self._load_band(request.red_band_path, bands["red"])
        nir = self._load_band(request.nir_band_path, bands["nir"])
        green = self._load_band(request.green_band_path, bands["green"])
        swir = self._load_band(request.swir_band_path, bands["swir"])
        thermal = self._load_band(request.thermal_band_path, bands["thermal"])

        index = request.index
        if index == "NDVI":
            result = self.compute_ndvi(red, nir)
        elif index == "NDWI":
            result = self.compute_ndwi(green, nir)
        elif index == "NDBI":
            result = self.compute_ndbi(swir, nir)
        elif index == "SAVI":
            result = self.compute_savi(red, nir, request.L)
        elif index == "BSI":
            result = self.compute_bsi(red, green, nir, swir)
        elif index == "LST":
            result = self.compute_lst(thermal)
        else:
            raise ValidationError(f"Unsupported index: {index}")

        # Persist output
        out_dir = self.settings.imagery_dir / "indices"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{index.lower()}_{request.scene_id or 'synthetic'}.npy"
        np.save(out_path, result)

        stats = self._stats(result)
        return IndexComputeResponse(
            index=index,
            mean=stats["mean"],  # type: ignore[arg-type]
            std=stats["std"],  # type: ignore[arg-type]
            min=stats["min"],  # type: ignore[arg-type]
            max=stats["max"],  # type: ignore[arg-type]
            median=stats["median"],  # type: ignore[arg-type]
            percentile_25=stats["percentile_25"],  # type: ignore[arg-type]
            percentile_75=stats["percentile_75"],  # type: ignore[arg-type]
            valid_pixels=stats["valid_pixels"],  # type: ignore[arg-type]
            histogram=stats["histogram"],  # type: ignore[arg-type]
            preview_base64=self._preview_base64(result),
            output_path=str(out_path),
        )

    def time_series(self, request: TimeSeriesRequest) -> TimeSeriesResponse:
        points: list[TimeSeriesPoint] = []
        values: list[float] = []
        for i, scene_id in enumerate(request.scene_ids):
            req = IndexComputeRequest(index=request.index, scene_id=scene_id)
            result = self.compute_index(req)
            # Use mean; if point provided, sample approximate pixel
            value = result.mean
            if request.point:
                bands = self._synthetic_bands(seed=hash(scene_id) % (2**31))
                # Sample center-ish based on hash of lon/lat
                lon, lat = request.point
                size = 256
                px = int(((lon + 180) / 360) * (size - 1)) % size
                py = int(((90 - lat) / 180) * (size - 1)) % size
                if request.index == "NDVI":
                    arr = self.compute_ndvi(bands["red"], bands["nir"])
                elif request.index == "NDWI":
                    arr = self.compute_ndwi(bands["green"], bands["nir"])
                else:
                    arr = self.compute_ndvi(bands["red"], bands["nir"])
                value = float(arr[py, px]) if np.isfinite(arr[py, px]) else result.mean
            date = f"2024-{(i % 12) + 1:02d}-15"
            points.append(TimeSeriesPoint(date=date, value=value, scene_id=scene_id))
            values.append(value)

        x = np.arange(len(values), dtype=float)
        y = np.array(values, dtype=float)
        if len(values) >= 2:
            slope, intercept = np.polyfit(x, y, 1)
        else:
            slope, intercept = 0.0, float(values[0]) if values else 0.0

        return TimeSeriesResponse(
            index=request.index,
            points=points,
            trend_slope=float(slope),
            trend_intercept=float(intercept),
        )

    def inspect_pixel(self, request: PixelInspectRequest) -> PixelInspectResponse:
        bands = self._synthetic_bands(seed=hash(request.scene_id or "pixel") % (2**31))
        size = 256
        px = int(((request.longitude + 180) / 360) * (size - 1)) % size
        py = int(((90 - request.latitude) / 180) * (size - 1)) % size
        values = {name: float(arr[py, px]) for name, arr in bands.items()}
        ndvi = float(self.compute_ndvi(bands["red"], bands["nir"])[py, px])
        ndwi = float(self.compute_ndwi(bands["green"], bands["nir"])[py, px])
        ndbi = float(self.compute_ndbi(bands["swir"], bands["nir"])[py, px])
        return PixelInspectResponse(
            longitude=request.longitude,
            latitude=request.latitude,
            values=values,
            indices={"NDVI": ndvi, "NDWI": ndwi, "NDBI": ndbi},
        )
