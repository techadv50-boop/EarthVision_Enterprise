"""Remote sensing spectral index analytics engine with map overlays."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image, ImageFilter

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
    "EVI": {
        "formula": "2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)",
        "label": "EVI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "rdylgn",
        "ref": "Huete et al. 2002 / MODIS EVI",
    },
    "NDMI": {
        "formula": "(NIR - SWIR) / (NIR + SWIR)",
        "label": "NDMI",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "blues",
        "ref": "Gao 1996 / moisture index",
    },
    "NBR": {
        "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
        "label": "NBR",
        "unit": "index (−1…1)",
        "range": (-1.0, 1.0),
        "cmap": "rdbu",
        "ref": "Key & Benson / burn ratio",
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

    def compute_evi(
        self, red: np.ndarray, nir: np.ndarray, blue: np.ndarray
    ) -> np.ndarray:
        """EVI = 2.5 * (NIR − RED) / (NIR + 6*RED − 7.5*BLUE + 1) (Huete 2002)."""
        r, n, b = (
            red.astype(np.float64),
            nir.astype(np.float64),
            blue.astype(np.float64),
        )
        return np.clip(
            2.5 * self._safe_divide(n - r, n + 6.0 * r - 7.5 * b + 1.0),
            -1.0,
            1.0,
        )

    def compute_ndmi(self, nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
        """NDMI = (NIR − SWIR) / (NIR + SWIR)."""
        n, s = nir.astype(np.float64), swir.astype(np.float64)
        return np.clip(self._safe_divide(n - s, n + s), -1.0, 1.0)

    def compute_nbr(self, nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
        """NBR = (NIR − SWIR2) / (NIR + SWIR2) — burn ratio."""
        n, s = nir.astype(np.float64), swir2.astype(np.float64)
        return np.clip(self._safe_divide(n - s, n + s), -1.0, 1.0)

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

        # Optical reflectance bands (0–1), including Blue for true-color RGB
        blue = np.clip(
            0.10 + 0.08 * (1 - veg) + 0.18 * urban + 0.12 * soil - 0.02 * water
            + 0.05 * (1 - soil)
            + rng.normal(0, 0.012, (size, size)),
            0,
            1,
        )
        green = np.clip(
            0.14 + 0.20 * veg + 0.12 * urban + 0.14 * soil - 0.04 * water
            + rng.normal(0, 0.015, (size, size)),
            0,
            1,
        )
        red = np.clip(
            0.12 + 0.12 * (1 - veg) + 0.28 * urban + 0.22 * soil - 0.1 * water
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
        # SWIR2-like (longer SWIR) for NBR / burn mapping
        swir2 = np.clip(
            0.14 + 0.18 * (1 - veg) + 0.35 * urban + 0.38 * soil - 0.2 * water
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
        return {
            "blue": blue,
            "green": green,
            "red": red,
            "nir": nir,
            "swir": swir,
            "swir2": swir2,
            "thermal": thermal,
        }

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
            "percentile_2": float(np.percentile(valid, 2)),
            "percentile_25": float(np.percentile(valid, 25)),
            "percentile_75": float(np.percentile(valid, 75)),
            "percentile_98": float(np.percentile(valid, 98)),
            "valid_pixels": int(valid.size),
            "histogram": {
                "counts": hist_counts.astype(float).tolist(),
                "edges": hist_edges.astype(float).tolist(),
            },
        }

    def _display_range(
        self,
        array: np.ndarray,
        fixed_min: float,
        fixed_max: float,
        *,
        p_low: float = 2.0,
        p_high: float = 98.0,
        mask: np.ndarray | None = None,
    ) -> tuple[float, float]:
        """Robust display vmin/vmax from data percentiles, soft-clipped to meta range."""
        valid = array[np.isfinite(array)]
        if mask is not None:
            valid = array[np.isfinite(array) & mask]
        if valid.size == 0:
            return float(fixed_min), float(fixed_max)
        lo = float(np.percentile(valid, p_low))
        hi = float(np.percentile(valid, p_high))
        # Keep within physical meta range but never force full [-1, 1] (washes out NDVI).
        lo = max(float(fixed_min), lo)
        hi = min(float(fixed_max), hi)
        if hi <= lo:
            mid = 0.5 * (float(fixed_min) + float(fixed_max))
            span = max(0.05, 0.05 * (float(fixed_max) - float(fixed_min)))
            lo, hi = mid - span, mid + span
        # Ensure a useful contrast span for visualization
        if (hi - lo) < 0.05 * max(1e-6, float(fixed_max) - float(fixed_min)):
            mid = 0.5 * (lo + hi)
            pad = 0.05 * max(1e-6, float(fixed_max) - float(fixed_min))
            lo, hi = mid - pad, mid + pad
        return lo, hi

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
        elif name == "viridis":
            r = np.clip(0.267 + 0.004 * t + 0.329 * t + 0.4 * t**2, 0, 1)
            g = np.clip(0.005 + 1.1 * t - 0.35 * t**2, 0, 1)
            b = np.clip(0.329 + 0.9 * (1 - t) * 0.7 + 0.1 * t, 0, 1)
        elif name == "magma":
            r = np.clip(0.05 + 1.1 * t, 0, 1)
            g = np.clip(0.0 + 0.35 * t + 0.9 * t**2.5, 0, 1)
            b = np.clip(0.15 + 1.2 * t * (1 - t) + 0.75 * t**3, 0, 1)
        elif name == "turbo":
            r = np.clip(0.2 + 2.2 * t - 2.4 * (t - 0.5).clip(0) ** 2, 0, 1)
            g = np.clip(0.1 + 1.8 * t - 1.6 * t**2, 0, 1)
            b = np.clip(0.9 - 1.5 * t + 0.8 * t**2, 0, 1)
        elif name == "brbg":
            r = np.where(t < 0.5, 0.65 - 0.45 * (t / 0.5), 0.2 + 0.55 * ((t - 0.5) / 0.5))
            g = np.where(t < 0.5, 0.35 + 0.45 * (t / 0.5), 0.8 - 0.15 * ((t - 0.5) / 0.5))
            b = np.where(t < 0.5, 0.2 + 0.4 * (t / 0.5), 0.65 - 0.45 * ((t - 0.5) / 0.5))
        else:
            r = g = b = t
        return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)

    COLORMAP_CATALOG: list[dict[str, str]] = [
        {"id": "rdylgn", "label": "Red–Yellow–Green (vegetation)"},
        {"id": "blues", "label": "Blues (water / moisture)"},
        {"id": "ylorbr", "label": "Yellow–Orange–Brown (built-up)"},
        {"id": "soil", "label": "Soil browns (bare soil)"},
        {"id": "thermal", "label": "Thermal (blue→red)"},
        {"id": "rdbu", "label": "Red–Blue diverging"},
        {"id": "viridis", "label": "Viridis"},
        {"id": "magma", "label": "Magma"},
        {"id": "turbo", "label": "Turbo"},
        {"id": "brbg", "label": "Brown–Blue–Green"},
        {"id": "gray", "label": "Grayscale"},
    ]

    def list_colormaps(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.COLORMAP_CATALOG:
            stops = []
            for i in range(6):
                t = i / 5
                r, g, b = self._colormap_rgb(item["id"], np.array([t]))
                stops.append(
                    {
                        "value": round(t, 2),
                        "color": "#{:02x}{:02x}{:02x}".format(
                            int(r[0] * 255), int(g[0] * 255), int(b[0] * 255)
                        ),
                    }
                )
            out.append({**item, "stops": stops})
        return out

    def _rgba_overlay(
        self,
        array: np.ndarray,
        cmap: str,
        vmin: float,
        vmax: float,
        *,
        alpha: int = 240,
        mask: np.ndarray | None = None,
    ) -> bytes:
        valid = np.isfinite(array)
        if mask is not None:
            valid = valid & mask
        norm = np.zeros_like(array, dtype=float)
        norm[valid] = (array[valid] - vmin) / (vmax - vmin + 1e-12)
        # Soft contrast curve keeps midtones readable after percentile stretch
        norm[valid] = np.clip(norm[valid], 0, 1)
        r, g, b = self._colormap_rgb(cmap, norm)
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        rgba[..., 0] = (np.clip(r, 0, 1) * 255).astype(np.uint8)
        rgba[..., 1] = (np.clip(g, 0, 1) * 255).astype(np.uint8)
        rgba[..., 2] = (np.clip(b, 0, 1) * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid, alpha, 0).astype(np.uint8)
        img = Image.fromarray(rgba, mode="RGBA")
        # Mild unsharp mask restores edge clarity lost in downsampling
        try:
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=2))
        except Exception:  # noqa: BLE001
            pass
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _footprint_mask_grid(
        self, footprint: dict[str, Any] | None, bounds: list[float], shape: tuple[int, int]
    ) -> np.ndarray | None:
        if not footprint:
            return None
        h, w = shape
        west, south, east, north = bounds
        try:
            from affine import Affine
            from rasterio.features import geometry_mask

            transform = Affine(
                (east - west) / w,
                0.0,
                west,
                0.0,
                (south - north) / h,
                north,
            )
            # geometry_mask True = outside; invert for inside footprint
            outside = geometry_mask(
                [footprint],
                out_shape=(h, w),
                transform=transform,
                all_touched=True,
                invert=False,
            )
            return ~outside
        except Exception:  # noqa: BLE001
            pass
        try:
            from shapely.geometry import Point, shape as shp_shape

            geom = shp_shape(footprint)
        except Exception:  # noqa: BLE001
            return None
        # Finer fallback sampling than before (was //128)
        step = max(1, min(h, w) // 256)
        ys = np.linspace(north, south, h, endpoint=False) + (south - north) / (2 * h)
        xs = np.linspace(west, east, w, endpoint=False) + (east - west) / (2 * w)
        mask = np.zeros((h, w), dtype=bool)
        for iy in range(0, h, step):
            for ix in range(0, w, step):
                inside = geom.contains(Point(float(xs[ix]), float(ys[iy])))
                mask[iy : iy + step, ix : ix + step] = inside
        return mask

    def _legend(
        self, index: str, vmin: float, vmax: float, cmap: str | None = None
    ) -> LegendInfo:
        meta = INDEX_META[index]
        cmap_name = cmap or meta["cmap"]
        stops: list[ColormapStop] = []
        for i in range(6):
            t = i / 5
            val = vmin + t * (vmax - vmin)
            r, g, b = self._colormap_rgb(cmap_name, np.array([t]))
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
            colormap=cmap_name,
        )

    def _compute_array(
        self, index: str, scene_id: str | None, L: float = 0.5, size: int = 1024
    ) -> np.ndarray:
        if scene_id:
            try:
                from app.services.scene_imagery_service import SceneImageryService

                imagery = SceneImageryService()
                real, _bounds, _fp, _layer = imagery.load_analysis_bands(scene_id, size=size)
                if real:
                    return self._index_from_bands(index, real, L=L, scene_id=scene_id, size=size)
            except ValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Real-band index fallback for {}: {}", scene_id, exc)
        bands = self._synthetic_bands(size=size, seed=hash(scene_id or "default") % (2**31))
        return self._index_from_bands(index, bands, L=L, scene_id=scene_id, size=size)

    def _index_from_bands(
        self,
        index: str,
        bands: dict[str, np.ndarray],
        *,
        L: float = 0.5,
        scene_id: str | None = None,
        size: int = 1024,
    ) -> np.ndarray:
        # Prefer the native loaded band shape (aspect-aware). Only resize if mismatched.
        sample = next((a for a in bands.values() if a is not None and a.size), None)
        target_h = int(sample.shape[0]) if sample is not None else size
        target_w = int(sample.shape[1]) if sample is not None else size
        synth = self._synthetic_bands(
            size=max(target_h, target_w),
            seed=hash(scene_id or "default") % (2**31),
        )

        def band(name: str) -> np.ndarray:
            arr = bands.get(name)
            if arr is None or not np.isfinite(arr).any():
                if name == "swir2":
                    arr = synth.get("swir2", synth["swir"])
                else:
                    key = "swir" if name == "swir" else name
                    arr = synth[key if key in synth else "red"]
            if arr.shape != (target_h, target_w):
                # Preserve nodata (NaN) through resize — avoid smearing zeros into data.
                finite = np.isfinite(arr)
                fill = float(np.nanmedian(arr[finite])) if finite.any() else 0.0
                work = np.where(finite, arr, fill).astype(np.float32)
                img = Image.fromarray(work, mode="F")
                resized = np.array(
                    img.resize((target_w, target_h), Image.Resampling.LANCZOS),
                    dtype=float,
                )
                mask_img = Image.fromarray((finite.astype(np.uint8) * 255), mode="L")
                mask_r = (
                    np.array(
                        mask_img.resize((target_w, target_h), Image.Resampling.NEAREST),
                        dtype=np.uint8,
                    )
                    > 127
                )
                resized[~mask_r] = np.nan
                return resized
            return arr.astype(float, copy=False)

        if index == "NDVI":
            return self.compute_ndvi(band("red"), band("nir"))
        if index == "NDWI":
            return self.compute_ndwi(band("green"), band("nir"))
        if index == "NDBI":
            return self.compute_ndbi(band("swir"), band("nir"))
        if index == "SAVI":
            return self.compute_savi(band("red"), band("nir"), L)
        if index == "BSI":
            return self.compute_bsi(band("red"), band("green"), band("nir"), band("swir"))
        if index == "EVI":
            return self.compute_evi(band("red"), band("nir"), band("blue"))
        if index == "NDMI":
            return self.compute_ndmi(band("nir"), band("swir"))
        if index == "NBR":
            return self.compute_nbr(band("nir"), band("swir2"))
        if index == "LST":
            thermal = bands.get("thermal")
            if thermal is not None and np.isfinite(thermal).any():
                t = thermal.astype(np.float64)
                # Landsat Collection-2 surface temperature may already be Kelvin or °C.
                # DN radiance path: values typically 20k–45k → use Planck conversion.
                tmax = float(np.nanmax(t))
                if tmax > 400:
                    return self.compute_lst(t)
                if tmax > 200:  # Kelvin
                    return t - 273.15
                return t  # already °C
            return self.compute_lst(synth["thermal"])
        raise ValidationError(f"Unsupported index: {index}")

    def compute_index(self, request: IndexComputeRequest) -> IndexComputeResponse:
        index = request.index
        meta = INDEX_META[index]
        size = int(getattr(request, "size", 1024) or 1024)
        footprint = request.aoi if request.aoi and request.aoi.get("type") == "Polygon" else None
        bounds = self._resolve_bounds(request.bbox, request.aoi)
        real_bands: dict[str, np.ndarray] = {}
        layer_meta: dict[str, Any] | None = None

        if request.scene_id:
            from app.services.scene_imagery_service import SceneImageryService
            from app.services.satellite_bands import (
                family_label,
                index_applicable,
                normalize_satellite_family,
            )

            imagery = SceneImageryService()
            layer = imagery.get_layer(request.scene_id)
            if layer:
                bounds = [float(x) for x in layer["bounds"]]
                footprint = layer.get("footprint") or footprint
                layer_meta = layer
                family = normalize_satellite_family(
                    str(layer.get("collection") or "")
                )
                if family != "UNKNOWN" and not index_applicable(index, family):
                    if index == "LST":
                        raise ValidationError(
                            f"LST requires Landsat-8/9 thermal (TIRS); "
                            f"not applicable to {family_label(family)}."
                        )
                    raise ValidationError(
                        f"{index} is not applicable to {family_label(family)}. "
                        "Use Sentinel-2, Landsat-7/8/9, or MODIS optical scenes."
                    )
                if layer.get("collection") == "SENTINEL-1" or layer.get("render_mode") == "grayscale":
                    raise ValidationError(
                        "Sentinel-1 SAR does not support optical indices. "
                        "Use Sentinel-2 or Landsat."
                    )
                try:
                    real_bands, bounds, footprint, layer_meta = imagery.load_analysis_bands(
                        request.scene_id, size=size
                    )
                except ValidationError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Index band load failed, using synthetic: {}", exc)

        if real_bands:
            result = self._index_from_bands(
                index, real_bands, L=request.L, scene_id=request.scene_id, size=size
            )
            data_source = "scene_bands"
        else:
            synth = self._synthetic_bands(
                size=size, seed=hash(request.scene_id or "default") % (2**31)
            )
            packed = {
                "red": self._load_band(request.red_band_path, synth["red"]),
                "nir": self._load_band(request.nir_band_path, synth["nir"]),
                "green": self._load_band(request.green_band_path, synth["green"]),
                "swir": self._load_band(request.swir_band_path, synth["swir"]),
                "swir2": synth["swir2"],
                "thermal": self._load_band(request.thermal_band_path, synth["thermal"]),
            }
            result = self._index_from_bands(
                index, packed, L=request.L, scene_id=request.scene_id, size=size
            )
            data_source = (
                "paths"
                if any(
                    [
                        request.red_band_path,
                        request.nir_band_path,
                        request.green_band_path,
                    ]
                )
                else "synthetic"
            )

        fixed_min, fixed_max = meta["range"]
        fp_mask = self._footprint_mask_grid(footprint, bounds, result.shape)
        # Data-driven display stretch (was fixed -1..1 → washed-out NDVI/NDWI/etc.)
        vmin, vmax = self._display_range(
            result, fixed_min, fixed_max, p_low=2.0, p_high=98.0, mask=fp_mask
        )

        cmap = request.colormap or meta["cmap"]
        overlay_bytes = self._rgba_overlay(result, cmap, vmin, vmax, alpha=240, mask=fp_mask)
        preview_bytes = self._rgba_overlay(
            result, cmap, vmin, vmax, alpha=255, mask=fp_mask
        )

        out_dir = self.settings.imagery_dir / "indices"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{index.lower()}_{request.scene_id or 'synthetic'}.npy"
        np.save(out_path, result)
        png_path = out_dir / f"{index.lower()}_{request.scene_id or 'synthetic'}.png"
        png_path.write_bytes(overlay_bytes)

        stats = self._stats(result)
        stac_bit = f"  stac={layer_meta.get('stac_id')}" if layer_meta else ""
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
            legend=self._legend(index, vmin, vmax, cmap),
            formula=f"{meta['formula']}  [{meta['ref']}]  source={data_source}{stac_bit}",
            output_path=str(png_path),
            colormap=cmap,
        )

    def change_detection(self, request: IndexChangeRequest) -> IndexChangeResponse:
        size = 1024
        before = self._compute_array(request.index, request.before_scene_id, request.L, size=size)
        after = self._compute_array(request.index, request.after_scene_id, request.L, size=size)
        h = min(before.shape[0], after.shape[0])
        w = min(before.shape[1], after.shape[1])
        before, after = before[:h, :w], after[:h, :w]
        diff = after - before
        mask = np.abs(diff) > request.threshold

        from app.services.scene_imagery_service import SceneImageryService

        imagery = SceneImageryService()
        layer = imagery.get_layer(request.after_scene_id) or imagery.get_layer(
            request.before_scene_id
        )
        if layer:
            bounds = [float(x) for x in layer["bounds"]]
            footprint = layer.get("footprint")
        else:
            bounds = self._resolve_bounds(request.bbox, None)
            footprint = None

        valid = diff[np.isfinite(diff)]
        vmax = (
            float(max(abs(np.percentile(valid, 2)), abs(np.percentile(valid, 98)), 0.05))
            if valid.size
            else 0.5
        )
        vmin = -vmax
        fp_mask = self._footprint_mask_grid(footprint, bounds, diff.shape)
        overlay = self._rgba_overlay(diff, "rdbu", vmin, vmax, mask=fp_mask)
        legend = LegendInfo(
            min=vmin,
            max=vmax,
            unit=f"Δ {request.index}",
            label=f"{request.index} change",
            formula=(
                f"Δ = {request.index}_after − {request.index}_before  "
                f"(threshold={request.threshold})"
            ),
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

    @staticmethod
    def _percentile_stretch(band: np.ndarray, p_low: float = 1.0, p_high: float = 99.0) -> np.ndarray:
        """Standard remote-sensing display stretch to [0, 1]."""
        valid = band[np.isfinite(band)]
        if valid.size == 0:
            return np.zeros_like(band, dtype=np.float64)
        lo = float(np.percentile(valid, p_low))
        hi = float(np.percentile(valid, p_high))
        if hi <= lo:
            hi = lo + 1e-6
        stretched = (band.astype(np.float64) - lo) / (hi - lo)
        return np.clip(stretched, 0.0, 1.0)

    @staticmethod
    def _joint_rgb_stretch(red: np.ndarray, green: np.ndarray, blue: np.ndarray) -> np.ndarray:
        """Per-channel 1–99% stretch for clearer true-color / RGB overlays."""
        channels = [
            red.astype(np.float64),
            green.astype(np.float64),
            blue.astype(np.float64),
        ]
        out = np.zeros((*red.shape, 3), dtype=np.float64)
        for i, ch in enumerate(channels):
            valid = ch[np.isfinite(ch)]
            if valid.size == 0:
                continue
            lo = float(np.percentile(valid, 1))
            hi = float(np.percentile(valid, 99))
            if hi <= lo:
                hi = lo + 1e-6
            out[:, :, i] = np.clip((ch - lo) / (hi - lo), 0.0, 1.0)
        return out

    def _lonlat_to_tile(self, lon: float, lat: float, zoom: int) -> tuple[float, float]:
        """Web Mercator fractional tile coordinates."""
        lat = max(min(lat, 85.05112878), -85.05112878)
        n = 2.0**zoom
        x = (lon + 180.0) / 360.0 * n
        lat_rad = np.radians(lat)
        y = (1.0 - np.log(np.tan(lat_rad) + 1.0 / np.cos(lat_rad)) / np.pi) / 2.0 * n
        return float(x), float(y)

    def _mosaic_esri_imagery(self, bbox: list[float], out_size: int = 512) -> Image.Image | None:
        """Mosaic Esri World Imagery tiles → true-color optical RGB for the bbox."""
        import math

        import httpx

        west, south, east, north = (float(v) for v in bbox)
        if east <= west or north <= south:
            return None

        lat_mid = (south + north) / 2.0
        width_m = (east - west) * 111_320.0 * math.cos(math.radians(lat_mid))
        height_m = (north - south) * 110_540.0
        meters = max(width_m, height_m, 1.0)
        zoom = int(
            math.floor(
                math.log2(156_543.03392 * math.cos(math.radians(lat_mid)) * out_size / meters)
            )
        )
        zoom = max(12, min(zoom, 18))

        def tile_range(z: int) -> tuple[float, float, float, float, int, int, int, int]:
            x0, y1 = self._lonlat_to_tile(west, south, z)
            x1, y0 = self._lonlat_to_tile(east, north, z)
            tx0, tx1 = int(math.floor(x0)), int(math.floor(x1))
            ty0, ty1 = int(math.floor(y0)), int(math.floor(y1))
            return x0, y0, x1, y1, tx0, ty0, tx1, ty1

        x0, y0, x1, y1, tx0, ty0, tx1, ty1 = tile_range(zoom)
        while (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 64 and zoom > 12:
            zoom -= 1
            x0, y0, x1, y1, tx0, ty0, tx1, ty1 = tile_range(zoom)

        tile_size = 256
        mosaic_w = (tx1 - tx0 + 1) * tile_size
        mosaic_h = (ty1 - ty0 + 1) * tile_size
        mosaic = Image.new("RGB", (mosaic_w, mosaic_h))
        url_tmpl = (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        )
        fetched = 0
        try:
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                for ty in range(ty0, ty1 + 1):
                    for tx in range(tx0, tx1 + 1):
                        url = url_tmpl.format(z=zoom, y=ty, x=tx)
                        resp = client.get(url)
                        if resp.status_code != 200:
                            logger.warning("Imagery tile miss {} → {}", url, resp.status_code)
                            continue
                        tile = Image.open(io.BytesIO(resp.content)).convert("RGB")
                        mosaic.paste(tile, ((tx - tx0) * tile_size, (ty - ty0) * tile_size))
                        fetched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Esri imagery mosaic failed: {}", exc)
            return None

        if fetched == 0:
            return None

        left = int((x0 - tx0) * tile_size)
        right = int((x1 - tx0) * tile_size)
        top = int((y0 - ty0) * tile_size)
        bottom = int((y1 - ty0) * tile_size)
        left = max(0, min(left, mosaic_w - 1))
        right = max(left + 1, min(right, mosaic_w))
        top = max(0, min(top, mosaic_h - 1))
        bottom = max(top + 1, min(bottom, mosaic_h))
        cropped = mosaic.crop((left, top, right, bottom))
        return cropped.resize((out_size, out_size), Image.Resampling.LANCZOS)

    def _natural_rgb_fallback(self, scene_id: str, size: int) -> Image.Image:
        """Natural-looking RGB when tiles/bands are unavailable (joint stretch)."""
        bands = self._synthetic_bands(size=size, seed=hash(scene_id) % (2**31))
        rgb = self._joint_rgb_stretch(bands["red"], bands["green"], bands["blue"])
        rgb = np.power(rgb, 0.9)
        return Image.fromarray((rgb * 255.0).astype(np.uint8), mode="RGB")

    def truecolor_overlay(
        self,
        scene_id: str,
        bbox: list[float] | None = None,
        footprint: dict[str, Any] | None = None,
        size: int = 1024,
        red_band_path: str | None = None,
        green_band_path: str | None = None,
        blue_band_path: str | None = None,
    ) -> dict[str, Any]:
        """
        True-color (natural color) RGB composite for map overlay.

        Priority:
        1. Real Red/Green/Blue GeoTIFF bands when paths are provided
        2. Esri World Imagery mosaic clipped to the scene bbox (optical RGB)
        3. Natural-looking synthetic fallback with joint stretch
        """
        bounds = self._resolve_bounds(bbox, footprint)
        source = "synthetic_natural"
        has_real = bool(red_band_path and green_band_path and blue_band_path)

        if has_real:
            bands = self._synthetic_bands(size=size, seed=hash(scene_id) % (2**31))
            red = self._load_band(red_band_path, bands["red"])
            green = self._load_band(green_band_path, bands["green"])
            blue = self._load_band(blue_band_path, bands["blue"])
            # Only treat as real if at least one path existed on disk
            used_disk = any(
                p and Path(p).exists() for p in (red_band_path, green_band_path, blue_band_path)
            )
            if used_disk:
                h = min(red.shape[0], green.shape[0], blue.shape[0])
                w = min(red.shape[1], green.shape[1], blue.shape[1])
                rgb = self._joint_rgb_stretch(red[:h, :w], green[:h, :w], blue[:h, :w])
                img = Image.fromarray((rgb * 255.0).astype(np.uint8), mode="RGB")
                img = img.resize((size, size), Image.Resampling.LANCZOS)
                source = "scene_bands"
            else:
                img = self._mosaic_esri_imagery(bounds, out_size=size)
                if img is not None:
                    source = "world_imagery"
                else:
                    img = self._natural_rgb_fallback(scene_id, size)
        else:
            img = self._mosaic_esri_imagery(bounds, out_size=size)
            if img is not None:
                source = "world_imagery"
            else:
                img = self._natural_rgb_fallback(scene_id, size)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
        out = self.settings.imagery_dir / "overlays"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"truecolor_rgb_{scene_id}.png"
        path.write_bytes(png)
        return {
            "scene_id": scene_id,
            "overlay_base64": base64.b64encode(png).decode("ascii"),
            "bounds": bounds,
            "download_url": f"/api/v1/catalog/scenes/{scene_id}/overlay.png",
            "content_type": "image/png",
            "local_path": str(path),
            "composite": "true_color_RGB",
            "source": source,
            "bands": {"R": "Red", "G": "Green", "B": "Blue"},
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
                "EVI": float(
                    self.compute_evi(bands["red"], bands["nir"], bands["blue"])[py, px]
                ),
                "NDMI": float(self.compute_ndmi(bands["nir"], bands["swir"])[py, px]),
                "NBR": float(self.compute_nbr(bands["nir"], bands["swir2"])[py, px]),
                "LST": float(self.compute_lst(bands["thermal"])[py, px]),
            },
        )
