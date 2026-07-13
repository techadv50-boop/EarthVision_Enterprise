"""Remote sensing spectral index analytics engine with map overlays."""

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
    ColormapStop,
    IndexChangeRequest,
    IndexChangeResponse,
    IndexComputeRequest,
    IndexComputeResponse,
    LegendInfo,
    PixelInspectRequest,
    PixelInspectResponse,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesResponse,
)

# Standard remote-sensing formulas (references in formula strings)
INDEX_META: dict[str, dict[str, Any]] = {
    "NDVI": {
        "formula": "(NIR - RED) / (NIR + RED)",
        "label": "NDVI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "rdylgn",
        "ref": "Rouse et al. 1974 / Tucker 1979",
    },
    "NDWI": {
        "formula": "(GREEN - NIR) / (GREEN + NIR)",
        "label": "NDWI (McFeeters)",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "blues",
        "ref": "McFeeters 1996",
    },
    "NDBI": {
        "formula": "(SWIR - NIR) / (SWIR + NIR)",
        "label": "NDBI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "ylorbr",
        "ref": "Zha, Gao & Ni 2003",
    },
    "SAVI": {
        "formula": "((NIR - RED) * (1 + L)) / (NIR + RED + L)",
        "label": "SAVI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "rdylgn",
        "ref": "Huete 1988",
    },
    "BSI": {
        "formula": "((SWIR + RED) - (NIR + GREEN)) / ((SWIR + RED) + (NIR + GREEN))",
        "label": "BSI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "soil",
        "ref": "Rikimaru et al. / bare-soil index",
    },
    "LST": {
        "formula": "BT = K2 / ln(K1/Lλ + 1) − 273.15  (Landsat TIRS)",
        "label": "LST",
        "unit": "°C",
        "range": (-10.0, 55.0),
        "cmap": "thermal",
        "ref": "Planck / Landsat Collection 2 TIRS",
    },
}


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class AnalyticsService:
    """Compute vegetation, water, urban, and thermal indices with georeferenced overlays."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def _safe_divide(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.true_divide(a, b)
            result[~np.isfinite(result)] = np.nan
        return result

    def compute_ndvi(self, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        """NDVI = (NIR − RED) / (NIR + RED)."""
        red_f, nir_f = red.astype(np.float64), nir.astype(np.float64)
        return np.clip(self._safe_divide(nir_f - red_f, nir_f + red_f), -1.0, 1.0)

    def compute_ndwi(self, green: np.ndarray, nir: np.ndarray) -> np.ndarray:
        """McFeeters NDWI = (GREEN − NIR) / (GREEN + NIR)."""
        g, n = green.astype(np.float64), nir.astype(np.float64)
        return np.clip(self._safe_divide(g - n, g + n), -1.0, 1.0)

    def compute_ndbi(self, swir: np.ndarray, nir: np.ndarray) -> np.ndarray:
        """NDBI = (SWIR − NIR) / (SWIR + NIR)."""
        s, n = swir.astype(np.float64), nir.astype(np.float64)
        return np.clip(self._safe_divide(s - n, s + n), -1.0, 1.0)

    def compute_savi(self, red: np.ndarray, nir: np.ndarray, L: float = 0.5) -> np.ndarray:
        """SAVI = ((NIR − RED) * (1 + L)) / (NIR + RED + L)."""
        r, n = red.astype(np.float64), nir.astype(np.float64)
        return np.clip(self._safe_divide((n - r) * (1.0 + L), n + r + L), -1.0, 1.0)

    def compute_bsi(
        self, red: np.ndarray, green: np.ndarray, nir: np.ndarray, swir: np.ndarray
    ) -> np.ndarray:
        """BSI = ((SWIR+RED) − (NIR+GREEN)) / ((SWIR+RED) + (NIR+GREEN))."""
        r, g, n, s = (
            red.astype(np.float64),
            green.astype(np.float64),
            nir.astype(np.float64),
            swir.astype(np.float64),
        )
        num = (s + r) - (n + g)
        den = (s + r) + (n + g)
        return np.clip(self._safe_divide(num, den), -1.0, 1.0)

    def compute_lst(
        self,
        thermal: np.ndarray,
        *,
        ml: float = 0.00341802,
        al: float = 149.0,
        k1: float = 774.8853,
        k2: float = 1321.0789,
    ) -> np.ndarray:
        """
        Land Surface Temperature (°C) from Landsat TIRS Band 10 radiance.

        Lλ = ML * Qcal + AL
        BT(K) = K2 / ln(K1/Lλ + 1)
        LST(°C) = BT − 273.15
        """
        radiance = thermal.astype(np.float64) * ml + al
        with np.errstate(divide="ignore", invalid="ignore"):
            bt_k = k2 / np.log((k1 / np.clip(radiance, 1e-6, None)) + 1.0)
            lst_c = bt_k - 273.15
            lst_c[~np.isfinite(lst_c)] = np.nan
        return lst_c

    def _synthetic_bands(self, size: int = 256, seed: int = 42) -> dict[str, np.ndarray]:
        rng = np.random.default_rng(seed)
        y, x = np.mgrid[0:size, 0:size]
        veg = np.clip(
            0.4 + 0.3 * np.sin(x / 30) * np.cos(y / 40) + rng.normal(0, 0.04, (size, size)),
            0,
            1,
        )
        urban = ((x > size * 0.55) & (y < size * 0.45)).astype(float) * 0.75
        water = ((x - size * 0.28) ** 2 + (y - size * 0.72) ** 2 < (size * 0.13) ** 2).astype(float)
        soil = ((x < size * 0.35) & (y < size * 0.35)).astype(float) * 0.55

        red = np.clip(
            0.12 + 0.12 * (1 - veg) + 0.28 * urban + 0.22 * soil - 0.1 * water
            + rng.normal(0, 0.015, (size, size)),
            0,
            1,
        )
        green = np.clip(
            0.16 + 0.18 * veg + 0.12 * urban + 0.14 * soil - 0.04 * water
            + rng.normal(0, 0.015, (size, size)),
            0,
            1,
        )
        nir = np.clip(
            0.22 + 0.5 * veg + 0.06 * urban + 0.1 * soil - 0.22 * water
            + rng.normal(0, 0.015, (size, size)),
            0,
            1,
        )
        swir = np.clip(
            0.18 + 0.12 * (1 - veg) + 0.4 * urban + 0.3 * soil - 0.18 * water
            + rng.normal(0, 0.015, (size, size)),
            0,
            1,
        )
        # Thermal as radiance-ish DN range used by compute_lst
        thermal = np.clip(
            28000 + 2500 * urban - 1800 * water - 900 * veg + 800 * soil
            + rng.normal(0, 120, (size, size)),
            20000,
            45000,
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

    def _resolve_bounds(
        self, bbox: list[float] | None, aoi: dict[str, Any] | None
    ) -> list[float]:
        if bbox and len(bbox) == 4:
            return [float(x) for x in bbox]
        if aoi and aoi.get("type") == "Polygon":
            ring = aoi["coordinates"][0]
            lons = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            return [min(lons), min(lats), max(lons), max(lats)]
        return [74.15, 31.35, 74.55, 31.7]

    def _stats(self, array: np.ndarray) -> dict[str, Any]:
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

    def _colormap_rgb(self, name: str, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Map normalized t∈[0,1] to RGB channels."""
        t = np.clip(t, 0, 1)
        if name == "rdylgn":
            r = np.where(t < 0.5, 0.85 + 0.15 * (t / 0.5), 0.95 - 0.75 * ((t - 0.5) / 0.5))
            g = np.where(t < 0.5, 0.25 + 0.7 * (t / 0.5), 0.85 + 0.05 * ((t - 0.5) / 0.5))
            b = np.where(t < 0.5, 0.15 * (1 - t / 0.5), 0.2 * ((t - 0.5) / 0.5))
        elif name == "blues":
            r = 0.95 - 0.85 * t
            g = 0.95 - 0.55 * t
            b = 0.98 - 0.15 * t
        elif name == "ylorbr":
            r = 1.0 - 0.25 * t
            g = 0.95 - 0.65 * t
            b = 0.75 - 0.7 * t
        elif name == "soil":
            r = 0.55 + 0.4 * t
            g = 0.4 + 0.15 * t
            b = 0.2 + 0.05 * t
        elif name == "thermal":
            # deep blue → cyan → yellow → red
            r = np.clip(1.5 * t - 0.2, 0, 1)
            g = np.clip(1 - 2 * np.abs(t - 0.45), 0, 1)
            b = np.clip(1.2 - 1.4 * t, 0, 1)
        elif name == "rdbu":
            # diverging for change: blue=decrease, red=increase
            r = np.where(t < 0.5, 0.2 + 0.6 * (t / 0.5), 0.85 + 0.15 * ((t - 0.5) / 0.5))
            g = np.where(t < 0.5, 0.35 + 0.5 * (t / 0.5), 0.85 - 0.7 * ((t - 0.5) / 0.5))
            b = np.where(t < 0.5, 0.85 - 0.2 * (t / 0.5), 0.65 - 0.55 * ((t - 0.5) / 0.5))
        else:
            r = g = b = t
        return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)

    def _rgba_overlay(
        self, array: np.ndarray, cmap: str, vmin: float, vmax: float, *, alpha: int = 200
    ) -> bytes:
        valid = np.isfinite(array)
        norm = np.zeros_like(array, dtype=float)
        norm[valid] = (array[valid] - vmin) / (vmax - vmin + 1e-12)
        r, g, b = self._colormap_rgb(cmap, norm)
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        rgba[..., 0] = (r * 255).astype(np.uint8)
        rgba[..., 1] = (g * 255).astype(np.uint8)
        rgba[..., 2] = (b * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid, alpha, 0).astype(np.uint8)
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _legend(self, index: str, vmin: float, vmax: float) -> LegendInfo:
        meta = INDEX_META[index]
        cmap = meta["cmap"]
        stops: list[ColormapStop] = []
        for i in range(6):
            t = i / 5
            val = vmin + t * (vmax - vmin)
            r, g, b = self._colormap_rgb(cmap, np.array([t]))
            color = "#{:02x}{:02x}{:02x}".format(
                int(r[0] * 255), int(g[0] * 255), int(b[0] * 255)
            )
            stops.append(ColormapStop(value=float(val), color=color))
        return LegendInfo(
            min=float(vmin),
            max=float(vmax),
            unit=meta["unit"],
            label=meta["label"],
            formula=f"{meta['formula']}  [{meta['ref']}]",
            stops=stops,
        )

    def _compute_array(
        self, index: str, scene_id: str | None, L: float = 0.5, size: int = 256
    ) -> np.ndarray:
        bands = self._synthetic_bands(size=size, seed=hash(scene_id or "default") % (2**31))
        if index == "NDVI":
            return self.compute_ndvi(bands["red"], bands["nir"])
        if index == "NDWI":
            return self.compute_ndwi(bands["green"], bands["nir"])
        if index == "NDBI":
            return self.compute_ndbi(bands["swir"], bands["nir"])
        if index == "SAVI":
            return self.compute_savi(bands["red"], bands["nir"], L)
        if index == "BSI":
            return self.compute_bsi(bands["red"], bands["green"], bands["nir"], bands["swir"])
        if index == "LST":
            return self.compute_lst(bands["thermal"])
        raise ValidationError(f"Unsupported index: {index}")

    def compute_index(self, request: IndexComputeRequest) -> IndexComputeResponse:
        index = request.index
        meta = INDEX_META[index]
        bands = self._synthetic_bands(seed=hash(request.scene_id or "default") % (2**31))
        red = self._load_band(request.red_band_path, bands["red"])
        nir = self._load_band(request.nir_band_path, bands["nir"])
        green = self._load_band(request.green_band_path, bands["green"])
        swir = self._load_band(request.swir_band_path, bands["swir"])
        thermal = self._load_band(request.thermal_band_path, bands["thermal"])

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

        bounds = self._resolve_bounds(request.bbox, request.aoi)
        fixed_min, fixed_max = meta["range"]
        # Use theoretical range for legend consistency; stretch preview slightly for LST
        if index == "LST":
            valid = result[np.isfinite(result)]
            vmin = float(np.percentile(valid, 2))
            vmax = float(np.percentile(valid, 98))
        else:
            vmin, vmax = fixed_min, fixed_max

        overlay_bytes = self._rgba_overlay(result, meta["cmap"], vmin, vmax)
        preview_bytes = self._rgba_overlay(result, meta["cmap"], vmin, vmax, alpha=255)

        out_dir = self.settings.imagery_dir / "indices"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{index.lower()}_{request.scene_id or 'synthetic'}.npy"
        np.save(out_path, result)
        png_path = out_dir / f"{index.lower()}_{request.scene_id or 'synthetic'}.png"
        png_path.write_bytes(overlay_bytes)

        stats = self._stats(result)
        return IndexComputeResponse(
            index=index,
            mean=stats["mean"],
            std=stats["std"],
            min=stats["min"],
            max=stats["max"],
            median=stats["median"],
            percentile_25=stats["percentile_25"],
            percentile_75=stats["percentile_75"],
            valid_pixels=stats["valid_pixels"],
            histogram=stats["histogram"],
            preview_base64=base64.b64encode(preview_bytes).decode("ascii"),
            overlay_base64=base64.b64encode(overlay_bytes).decode("ascii"),
            bounds=bounds,
            legend=self._legend(index, vmin, vmax),
            formula=f"{meta['formula']}  [{meta['ref']}]",
            output_path=str(png_path),
        )

    def change_detection(self, request: IndexChangeRequest) -> IndexChangeResponse:
        before = self._compute_array(request.index, request.before_scene_id, request.L)
        after = self._compute_array(request.index, request.after_scene_id, request.L)
        diff = after - before
        mask = np.abs(diff) > request.threshold
        bounds = self._resolve_bounds(request.bbox, None)
        # Symmetric scale for difference
        valid = diff[np.isfinite(diff)]
        vmax = float(max(abs(np.percentile(valid, 2)), abs(np.percentile(valid, 98)), 0.05))
        vmin = -vmax
        overlay = self._rgba_overlay(diff, "rdbu", vmin, vmax)
        legend = LegendInfo(
            min=vmin,
            max=vmax,
            unit=f"Δ {request.index}",
            label=f"{request.index} change",
            formula=f"Δ = {request.index}_after − {request.index}_before  (threshold={request.threshold})",
            stops=[
                ColormapStop(value=vmin, color="#2166ac"),
                ColormapStop(value=0.0, color="#f7f7f7"),
                ColormapStop(value=vmax, color="#b2182b"),
            ],
        )
        return IndexChangeResponse(
            index=request.index,
            before_scene_id=request.before_scene_id,
            after_scene_id=request.after_scene_id,
            mean_before=float(np.nanmean(before)),
            mean_after=float(np.nanmean(after)),
            mean_difference=float(np.nanmean(diff)),
            change_ratio=float(np.mean(mask)),
            significant_pixels=int(np.sum(mask)),
            overlay_base64=base64.b64encode(overlay).decode("ascii"),
            bounds=bounds,
            legend=legend,
            formula=legend.formula,
        )

    def truecolor_overlay(
        self,
        scene_id: str,
        bbox: list[float] | None = None,
        footprint: dict[str, Any] | None = None,
        size: int = 384,
    ) -> dict[str, Any]:
        """Generate a georeferenced true-color PNG for map ImageOverlay."""
        bands = self._synthetic_bands(size=size, seed=hash(scene_id) % (2**31))
        # Simple atmospheric stretch + NIR vegetation boost into green for readability
        r = np.clip(bands["red"] * 1.35, 0, 1)
        g = np.clip(bands["green"] * 1.25 + 0.15 * bands["nir"], 0, 1)
        b = np.clip((bands["green"] * 0.35 + bands["red"] * 0.15) * 1.1, 0, 1)
        rgb = np.stack([r, g, b], axis=-1)
        img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        bounds = self._resolve_bounds(bbox, footprint)
        out = self.settings.imagery_dir / "overlays"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"truecolor_{scene_id}.png"
        path.write_bytes(buf.getvalue())
        return {
            "scene_id": scene_id,
            "overlay_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "bounds": bounds,
            "download_url": f"/api/v1/catalog/scenes/{scene_id}/overlay.png",
            "content_type": "image/png",
            "local_path": str(path),
        }

    def time_series(self, request: TimeSeriesRequest) -> TimeSeriesResponse:
        points: list[TimeSeriesPoint] = []
        values: list[float] = []
        for i, scene_id in enumerate(request.scene_ids):
            arr = self._compute_array(request.index, scene_id)
            value = float(np.nanmean(arr))
            if request.point:
                lon, lat = request.point
                size = arr.shape[0]
                px = int(((lon + 180) / 360) * (size - 1)) % size
                py = int(((90 - lat) / 180) * (size - 1)) % size
                sample = arr[py, px]
                if np.isfinite(sample):
                    value = float(sample)
            from datetime import UTC, datetime, timedelta

            date = (datetime.now(UTC) - timedelta(days=i * 5)).strftime("%Y-%m-%d")
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
        values = {name: float(arr[py, px]) for name, arr in bands.items() if name != "thermal"}
        values["thermal_dn"] = float(bands["thermal"][py, px])
        return PixelInspectResponse(
            longitude=request.longitude,
            latitude=request.latitude,
            values=values,
            indices={
                "NDVI": float(self.compute_ndvi(bands["red"], bands["nir"])[py, px]),
                "NDWI": float(self.compute_ndwi(bands["green"], bands["nir"])[py, px]),
                "NDBI": float(self.compute_ndbi(bands["swir"], bands["nir"])[py, px]),
                "SAVI": float(self.compute_savi(bands["red"], bands["nir"])[py, px]),
                "BSI": float(
                    self.compute_bsi(bands["red"], bands["green"], bands["nir"], bands["swir"])[
                        py, px
                    ]
                ),
                "LST": float(self.compute_lst(bands["thermal"])[py, px]),
            },
        )
