"""RGB band composites, false-color presets, and histogram stretch for EO scenes."""

from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image, ImageEnhance, ImageFilter

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.composite import (
    CompositeRequest,
    CompositeResponse,
    StretchRequest,
    StretchResponse,
)

# Standard remote-sensing RGB band combinations (Sentinel-2 / Landsat OLI mapping)
COMPOSITE_PRESETS: dict[str, dict[str, Any]] = {
    "true_color": {
        "label": "True Color (Natural)",
        "keys": ("red", "green", "blue"),
        "display": {"R": "Red", "G": "Green", "B": "Blue"},
        "s2": "B04-B03-B02",
        "landsat": "B4-B3-B2",
        "formula": "R=Red, G=Green, B=Blue — natural color",
        "use": "General mapping, visual interpretation",
    },
    "false_color_infrared": {
        "label": "False Color Infrared (FCC)",
        "keys": ("nir", "red", "green"),
        "display": {"R": "NIR", "G": "Red", "B": "Green"},
        "s2": "B08-B04-B03",
        "landsat": "B5-B4-B3",
        "formula": "R=NIR, G=Red, B=Green — vegetation appears bright red",
        "use": "Vegetation vigor, land/water contrast (classic FCC)",
    },
    "false_color_agriculture": {
        "label": "Agriculture / SWIR",
        "keys": ("swir", "nir", "blue"),
        "display": {"R": "SWIR1", "G": "NIR", "B": "Blue"},
        "s2": "B11-B08-B02",
        "landsat": "B6-B5-B2",
        "formula": "R=SWIR1, G=NIR, B=Blue — crops & soils",
        "use": "Crop health, bare soil vs vegetation",
    },
    "false_color_urban": {
        "label": "Urban / Built-up",
        "keys": ("swir", "nir", "red"),
        "display": {"R": "SWIR1", "G": "NIR", "B": "Red"},
        "s2": "B11-B08-B04",
        "landsat": "B6-B5-B4",
        "formula": "R=SWIR1, G=NIR, B=Red — built-up bright",
        "use": "Urban fabric, impervious surfaces (pairs with NDBI)",
    },
    "swir_composite": {
        "label": "SWIR Composite",
        "keys": ("swir2", "swir", "red"),
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "Red"},
        "s2": "B12-B11-B04",
        "landsat": "B7-B6-B4",
        "formula": "R=SWIR2, G=SWIR1, B=Red — moisture & geology",
        "use": "Soil moisture, lithology, burn scars",
    },
    "geology": {
        "label": "Geology / Lithology",
        "keys": ("swir2", "swir", "blue"),
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "Blue"},
        "s2": "B12-B11-B02",
        "landsat": "B7-B6-B2",
        "formula": "R=SWIR2, G=SWIR1, B=Blue — rock & soil types",
        "use": "Geological mapping",
    },
    "atmospheric_penetration": {
        "label": "Atmospheric Penetration",
        "keys": ("swir2", "swir", "nir"),
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "NIR"},
        "s2": "B12-B11-B08",
        "landsat": "B7-B6-B5",
        "formula": "R=SWIR2, G=SWIR1, B=NIR — haze penetration",
        "use": "Smoke/haze penetration, fire mapping",
    },
    "land_water": {
        "label": "Land / Water",
        "keys": ("nir", "swir", "red"),
        "display": {"R": "NIR", "G": "SWIR1", "B": "Red"},
        "s2": "B08-B11-B04",
        "landsat": "B5-B6-B4",
        "formula": "R=NIR, G=SWIR1, B=Red — water dark, land bright",
        "use": "Shorelines, flooding (pairs with NDWI)",
    },
    "vegetation_health": {
        "label": "Vegetation Health (NIR-focused)",
        "keys": ("nir", "swir", "green"),
        "display": {"R": "NIR", "G": "SWIR1", "B": "Green"},
        "s2": "B08-B11-B03",
        "landsat": "B5-B6-B3",
        "formula": "R=NIR, G=SWIR1, B=Green — healthy veg bright",
        "use": "Vegetation stress (pairs with NDVI / NDMI)",
    },
    "burn_severity": {
        "label": "Burn Severity Preview",
        "keys": ("swir2", "nir", "green"),
        "display": {"R": "SWIR2", "G": "NIR", "B": "Green"},
        "s2": "B12-B08-B03",
        "landsat": "B7-B5-B3",
        "formula": "R=SWIR2, G=NIR, B=Green — burns magenta/red",
        "use": "Fire scars (pairs with NBR)",
    },
}

# Recommended RGB / thematic display notes per spectral index
INDEX_THEMATIC: dict[str, dict[str, str]] = {
    "NDVI": {
        "formula": "(NIR − RED) / (NIR + RED)",
        "bands": "NIR + Red (S2: B08+B04 · Landsat: B5+B4)",
        "thematic_rgb": "False Color Infrared (NIR-Red-Green) for context",
        "colormap": "RdYlGn (−1…1)",
    },
    "NDWI": {
        "formula": "(GREEN − NIR) / (GREEN + NIR)  [McFeeters]",
        "bands": "Green + NIR (S2: B03+B08 · Landsat: B3+B5)",
        "thematic_rgb": "Land/Water composite (NIR-SWIR-Red)",
        "colormap": "Blues (−1…1)",
    },
    "NDBI": {
        "formula": "(SWIR1 − NIR) / (SWIR1 + NIR)",
        "bands": "SWIR1 + NIR (S2: B11+B08 · Landsat: B6+B5)",
        "thematic_rgb": "Urban composite (SWIR-NIR-Red)",
        "colormap": "YlOrBr (−1…1)",
    },
    "SAVI": {
        "formula": "((NIR − RED) × (1+L)) / (NIR + RED + L)  [L=0.5]",
        "bands": "NIR + Red (S2: B08+B04 · Landsat: B5+B4)",
        "thematic_rgb": "False Color Infrared (NIR-Red-Green)",
        "colormap": "RdYlGn (−1…1)",
    },
    "BSI": {
        "formula": "((SWIR+RED) − (NIR+GREEN)) / ((SWIR+RED) + (NIR+GREEN))",
        "bands": "SWIR1 + Red + NIR + Green",
        "thematic_rgb": "Agriculture / SWIR composite",
        "colormap": "Soil browns (−1…1)",
    },
    "EVI": {
        "formula": "2.5 × (NIR−RED) / (NIR + 6·RED − 7.5·GREEN + 1)",
        "bands": "NIR + Red + Green (S2: B08+B04+B03)",
        "thematic_rgb": "False Color Infrared (NIR-Red-Green)",
        "colormap": "RdYlGn (−1…1)",
    },
    "NDMI": {
        "formula": "(NIR − SWIR1) / (NIR + SWIR1)",
        "bands": "NIR + SWIR1 (S2: B08+B11 · Landsat: B5+B6)",
        "thematic_rgb": "Vegetation Health (NIR-SWIR-Green)",
        "colormap": "BrBG (−1…1)",
    },
    "NBR": {
        "formula": "(NIR − SWIR2) / (NIR + SWIR2)",
        "bands": "NIR + SWIR2 (S2: B08+B12 · Landsat: B5+B7)",
        "thematic_rgb": "Burn Severity (SWIR2-NIR-Green)",
        "colormap": "RdYlBu (−1…1)",
    },
    "LST": {
        "formula": "BT = K2 / ln(K1/Lλ + 1) − 273.15 °C  (Landsat TIRS)",
        "bands": "Thermal (Landsat ST_B10 / lwir11)",
        "thematic_rgb": "True Color underlay + thermal colormap",
        "colormap": "Thermal (°C)",
    },
}


class CompositeService:
    """Build RGB composites and stretch previews from scene analysis bands."""

    def list_presets(self) -> list[dict[str, Any]]:
        return [
            {
                "id": key,
                "label": meta["label"],
                "formula": meta["formula"],
                "use": meta["use"],
                "sentinel2": meta["s2"],
                "landsat": meta["landsat"],
                "bands": meta["display"],
            }
            for key, meta in COMPOSITE_PRESETS.items()
        ]

    def list_index_thematic(self) -> list[dict[str, str]]:
        return [{"id": k, **v} for k, v in INDEX_THEMATIC.items()]

    def render_composite(self, request: CompositeRequest) -> CompositeResponse:
        preset_id = request.preset
        meta = COMPOSITE_PRESETS.get(preset_id)
        if request.red_band and request.green_band and request.blue_band:
            keys = (request.red_band, request.green_band, request.blue_band)
            label = f"Custom ({keys[0]}-{keys[1]}-{keys[2]})"
            display = {"R": keys[0], "G": keys[1], "B": keys[2]}
            formula = f"R={keys[0]}, G={keys[1]}, B={keys[2]}"
            band_keys = {"R": keys[0], "G": keys[1], "B": keys[2]}
        elif meta:
            keys = meta["keys"]
            label = meta["label"]
            display = meta["display"]
            formula = meta["formula"]
            band_keys = {"R": keys[0], "G": keys[1], "B": keys[2]}
        else:
            raise ValidationError(f"Unknown composite preset: {preset_id}")

        # True color: prefer ESA/USGS visual COG (already display-balanced) over AOI.
        if preset_id == "true_color" and request.scene_id:
            visual = self._load_visual_rgb(request.scene_id, request.bbox, request.size)
            if visual is not None:
                rgb, bounds, valid_mask = visual
                # Keep TCI color balance; only apply mild user brightness/contrast
                # (ignore aggressive gamma meant for raw reflectance bands).
                rgb = self._polish_visual(
                    rgb,
                    gamma=1.0,
                    brightness=min(request.brightness or 1.0, 1.1),
                    contrast=min(request.contrast or 1.0, 1.15),
                )
                hist = self._rgb_histogram(rgb)
                png = self._rgb_to_png(rgb, valid_mask=valid_mask)
                return CompositeResponse(
                    preset=preset_id,
                    label=label,
                    bands=display,
                    band_keys=band_keys,
                    formula=formula + " · visual/TCI",
                    bounds=bounds,
                    overlay_base64=base64.b64encode(png).decode("ascii"),
                    histogram=hist,
                    legend=self._rgb_legend(label, formula),
                    message=f"{label} · visual product (AOI)",
                    stretch="visual",
                )

        bands, bounds = self._load_bands(request.scene_id, request.bbox, request.size)
        r = self._pick(bands, keys[0])
        g = self._pick(bands, keys[1])
        b = self._pick(bands, keys[2])
        valid_mask = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)

        # True color → joint + cloud-robust; false color → per-channel on land pixels
        stretch_mode = "joint_land" if preset_id == "true_color" else "channel_land"
        rgb = self._stack_stretch(
            r, g, b,
            mode=stretch_mode if request.stretch == "percentile" else request.stretch,
            p_low=request.p_low,
            p_high=request.p_high,
            gamma=request.gamma,
            brightness=request.brightness,
            contrast=request.contrast,
        )
        hist = self._rgb_histogram(rgb)
        png = self._rgb_to_png(rgb, valid_mask=valid_mask)
        return CompositeResponse(
            preset=preset_id,
            label=label,
            bands=display,
            band_keys=band_keys,
            formula=formula,
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            histogram=hist,
            legend=self._rgb_legend(label, formula),
            message=f"{label} · {stretch_mode} p{request.p_low}-{request.p_high}%",
            stretch=f"{stretch_mode} p{request.p_low}-{request.p_high} γ={request.gamma}",
        )

    def stretch_scene(self, request: StretchRequest) -> StretchResponse:
        # Prefer visual product when stretching true-color appearance
        if request.scene_id and request.source == "true_color":
            visual = self._load_visual_rgb(request.scene_id, request.bbox, request.size)
            if visual is not None:
                rgb, bounds, valid_mask = visual
                rgb = self._polish_visual(rgb, request.gamma, request.brightness, request.contrast)
                hist = self._rgb_histogram(rgb)
                png = self._rgb_to_png(rgb, valid_mask=valid_mask)
                return StretchResponse(
                    bounds=bounds,
                    overlay_base64=base64.b64encode(png).decode("ascii"),
                    histogram=hist,
                    p_low=request.p_low,
                    p_high=request.p_high,
                    gamma=request.gamma,
                    brightness=request.brightness,
                    contrast=request.contrast,
                    message=(
                        f"Visual stretch · γ={request.gamma} · "
                        f"brightness={request.brightness} · contrast={request.contrast}"
                    ),
                )

        bands, bounds = self._load_bands(request.scene_id, request.bbox, request.size)
        r = self._pick(bands, "red")
        g = self._pick(bands, "green")
        b = self._pick(bands, "blue")
        valid_mask = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
        rgb = self._stack_stretch(
            r, g, b,
            mode="joint_land",
            p_low=request.p_low,
            p_high=request.p_high,
            gamma=request.gamma,
            brightness=request.brightness,
            contrast=request.contrast,
        )
        hist = self._rgb_histogram(rgb)
        raw_hist = self._channel_histograms(r, g, b)
        hist["raw"] = raw_hist
        png = self._rgb_to_png(rgb, valid_mask=valid_mask)
        return StretchResponse(
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            histogram=hist,
            p_low=request.p_low,
            p_high=request.p_high,
            gamma=request.gamma,
            brightness=request.brightness,
            contrast=request.contrast,
            message=(
                f"Histogram stretch {request.p_low}–{request.p_high}% · "
                f"γ={request.gamma} · brightness={request.brightness} · contrast={request.contrast}"
            ),
        )

    def _rgb_legend(self, label: str, formula: str) -> LegendInfo:
        return LegendInfo(
            min=0,
            max=255,
            unit="DN",
            label=label,
            formula=formula,
            stops=[
                ColormapStop(value=0, color="#000000"),
                ColormapStop(value=128, color="#808080"),
                ColormapStop(value=255, color="#ffffff"),
            ],
        )

    def _load_visual_rgb(
        self, scene_id: str, bbox: list[float] | None, size: int
    ) -> tuple[np.ndarray, list[float], np.ndarray] | None:
        try:
            from app.services.scene_imagery_service import SceneImageryService

            imagery = SceneImageryService()
            layer = imagery.get_layer(scene_id)
            if not layer:
                return None
            bounds = imagery.clip_bounds_to_layer(layer, bbox)
            result = imagery.read_visual_rgb(scene_id, bounds, size=size)
            if result is None:
                return None
            rgb, bounds = result
            valid = np.any(rgb > 0.01, axis=2) & np.all(np.isfinite(rgb), axis=2)
            return rgb, bounds, valid
        except Exception as exc:  # noqa: BLE001
            logger.warning("Visual composite load failed: {}", exc)
            return None

    @staticmethod
    def _polish_visual(
        rgb: np.ndarray, gamma: float, brightness: float, contrast: float
    ) -> np.ndarray:
        """Very light polish on TCI/visual — keep ESA/USGS color balance intact."""
        out = np.clip(rgb.astype(np.float64), 0, 1)
        # TCI is already display-ready; only apply mild user adjustments.
        g = float(gamma) if gamma and abs(gamma - 1.0) > 1e-3 else 1.0
        if abs(g - 1.0) > 1e-3:
            out = np.power(out, 1.0 / max(0.85, min(g, 1.25)))
        c = float(contrast) if contrast else 1.0
        b = float(brightness) if brightness else 1.0
        if abs(c - 1.0) > 1e-3:
            out = (out - 0.5) * max(0.85, min(c, 1.2)) + 0.5
        if abs(b - 1.0) > 1e-3:
            out = out * max(0.85, min(b, 1.15))
        return np.clip(out, 0, 1)

    def _load_bands(
        self, scene_id: str | None, bbox: list[float] | None, size: int
    ) -> tuple[dict[str, np.ndarray], list[float]]:
        bounds = bbox if bbox and len(bbox) == 4 else [74.15, 31.35, 74.55, 31.7]
        if scene_id:
            try:
                from app.services.scene_imagery_service import SceneImageryService

                imagery = SceneImageryService()
                bands, bounds, _fp, _layer = imagery.load_analysis_bands(
                    scene_id, size=size, bounds=bbox
                )
                if bands:
                    if "swir2" not in bands and "swir" in bands:
                        bands["swir2"] = bands["swir"]
                    return bands, bounds
            except Exception as exc:  # noqa: BLE001
                logger.warning("Composite band load failed: {}", exc)

        from app.services.analytics_service import AnalyticsService

        synth = AnalyticsService()._synthetic_bands(
            size=size, seed=hash(scene_id or "comp") % (2**31)
        )
        return synth, [float(x) for x in bounds]

    def _pick(self, bands: dict[str, np.ndarray], key: str) -> np.ndarray:
        if key in bands:
            return bands[key].astype(np.float64)
        # Fallbacks
        aliases = {
            "swir2": ["swir2", "swir", "nir"],
            "swir": ["swir", "swir2", "red"],
            "nir": ["nir", "green"],
            "red": ["red", "nir"],
            "green": ["green", "blue"],
            "blue": ["blue", "green"],
        }
        for alt in aliases.get(key, [key]):
            if alt in bands:
                return bands[alt].astype(np.float64)
        # Last resort: zeros matching any available band shape
        for arr in bands.values():
            return np.zeros_like(arr, dtype=np.float64)
        raise ValidationError(f"Band '{key}' not available")

    @staticmethod
    def _land_mask(stacked: np.ndarray) -> np.ndarray:
        """Pixels used for stretch stats — exclude nodata and bright clouds/snow."""
        finite = np.all(np.isfinite(stacked), axis=2)
        if not finite.any():
            return finite
        # Brightness in reflectance units (or normalized visual)
        bright = np.nanmean(stacked, axis=2)
        vals = bright[finite]
        # Drop the brightest ~8% (clouds/snow) from statistics so land isn't crushed
        cloud_cut = float(np.percentile(vals, 92))
        # Also drop near-zero fill
        dark_cut = float(np.percentile(vals, 2))
        land = finite & (bright >= dark_cut) & (bright <= cloud_cut)
        # Fallback if too aggressive
        if land.sum() < max(64, int(0.05 * finite.sum())):
            land = finite & (bright > 0)
        return land

    def _stack_stretch(
        self,
        r: np.ndarray,
        g: np.ndarray,
        b: np.ndarray,
        *,
        mode: str,
        p_low: float,
        p_high: float,
        gamma: float,
        brightness: float,
        contrast: float,
    ) -> np.ndarray:
        stacked = np.stack(
            [r.astype(np.float64), g.astype(np.float64), b.astype(np.float64)],
            axis=-1,
        )
        # Reflectance bands should already be 0–1; clip wild values
        if np.nanmax(stacked) > 1.5:
            stacked = stacked / 10000.0
        stacked = np.clip(stacked, 0, 1)
        finite = np.all(np.isfinite(stacked), axis=2)
        out = np.zeros_like(stacked, dtype=np.float64)

        if mode == "none":
            out = np.nan_to_num(stacked, nan=0.0)
            out = np.clip(out, 0, 1)
        elif mode == "minmax":
            for i in range(3):
                ch = stacked[:, :, i]
                m = np.isfinite(ch)
                if not m.any():
                    continue
                lo, hi = float(np.nanmin(ch)), float(np.nanmax(ch))
                out[:, :, i] = np.clip((ch - lo) / (hi - lo + 1e-9), 0, 1)
                out[:, :, i][~m] = 0
        elif mode in {"joint_land", "percentile"}:
            # Shared stretch across RGB using land pixels (natural color balance)
            land = self._land_mask(stacked)
            vals = stacked[land]
            if vals.size == 0:
                vals = stacked[finite]
            if vals.size:
                lo = float(np.percentile(vals, p_low))
                hi = float(np.percentile(vals, p_high))
                # Cap hi so bright clouds don't force land into darkness
                hi = min(hi, max(lo + 0.05, float(np.percentile(vals, 90)) * 1.15, 0.35))
                if hi <= lo:
                    hi = lo + 1e-6
                out = np.clip((stacked - lo) / (hi - lo), 0, 1)
                out[~finite] = 0
        else:  # channel_land — per-channel on land (FCC / thematic)
            land = self._land_mask(stacked)
            for i in range(3):
                ch = stacked[:, :, i]
                sample = ch[land & np.isfinite(ch)]
                if sample.size == 0:
                    sample = ch[finite]
                if sample.size == 0:
                    continue
                lo = float(np.percentile(sample, p_low))
                hi = float(np.percentile(sample, p_high))
                hi = min(hi, max(lo + 0.05, float(np.percentile(sample, 90)) * 1.2, 0.45))
                if hi <= lo:
                    hi = lo + 1e-6
                out[:, :, i] = np.clip((ch - lo) / (hi - lo), 0, 1)
                out[:, :, i][~finite] = 0

        # Midtone lift — EO reflectance often looks dark without gamma > 1
        g = gamma if gamma and gamma > 0 else 1.15
        out = np.power(np.clip(out, 0, 1), 1.0 / g)
        out = (out - 0.5) * contrast + 0.5
        out = out * brightness
        return np.clip(out, 0, 1)

    def _rgb_to_png(self, rgb: np.ndarray, valid_mask: np.ndarray | None = None) -> bytes:
        u8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        if valid_mask is None:
            valid_mask = np.any(u8 > 2, axis=2)
        alpha = np.where(valid_mask, 255, 0).astype(np.uint8)
        rgba = np.dstack([u8, alpha])
        img = Image.fromarray(rgba, mode="RGBA")
        # Light sharpen only — heavy unsharp made composites look crunchy/blocky
        try:
            img = img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=3))
        except Exception:  # noqa: BLE001
            pass
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _rgb_histogram(self, rgb: np.ndarray) -> dict[str, Any]:
        u8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        edges = list(range(0, 257, 8))
        channels = {}
        for i, name in enumerate(("red", "green", "blue")):
            counts, _ = np.histogram(u8[:, :, i].ravel(), bins=edges)
            channels[name] = counts.astype(int).tolist()
        return {"edges": edges, "channels": channels}

    def _channel_histograms(
        self, r: np.ndarray, g: np.ndarray, b: np.ndarray
    ) -> dict[str, Any]:
        edges = np.linspace(0, 1, 33).tolist()
        channels = {}
        for name, ch in (("red", r), ("green", g), ("blue", b)):
            valid = ch[np.isfinite(ch)]
            if valid.size == 0:
                channels[name] = [0] * 32
                continue
            counts, _ = np.histogram(np.clip(valid, 0, 1), bins=32, range=(0, 1))
            channels[name] = counts.astype(int).tolist()
        return {"edges": edges, "channels": channels}

    def enhance_png(
        self,
        overlay_b64: str,
        *,
        brightness: float = 1.0,
        contrast: float = 1.0,
        sharpen: bool = False,
        denoise: bool = False,
    ) -> str:
        raw = base64.b64decode(overlay_b64)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        rgb = img.convert("RGB")
        if abs(brightness - 1.0) > 1e-6:
            rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
        if abs(contrast - 1.0) > 1e-6:
            rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
        if sharpen:
            rgb = rgb.filter(ImageFilter.SHARPEN)
        if denoise:
            rgb = rgb.filter(ImageFilter.MedianFilter(size=3))
        out = Image.merge("RGBA", (*rgb.split(), img.split()[-1]))
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
