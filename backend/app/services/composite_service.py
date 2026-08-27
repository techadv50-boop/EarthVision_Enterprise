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
from app.services.satellite_bands import (
    COMPOSITE_BAND_CODES,
    COMPOSITE_REQUIRED_KEYS,
    INDEX_APPLICABLE,
    INDEX_BAND_NOTES,
    OPTICAL_SWIR_FAMILY,
    composite_applicable_families,
    composite_for_family,
    family_label,
    normalize_satellite_family,
    unsupported_image_processing_reason,
)

# Standard remote-sensing RGB band combinations (sensor-accurate codes in satellite_bands)
COMPOSITE_PRESETS: dict[str, dict[str, Any]] = {
    "true_color": {
        "label": "True Color (Natural)",
        "keys": COMPOSITE_REQUIRED_KEYS["true_color"],
        "display": {"R": "Red", "G": "Green", "B": "Blue"},
        "formula": "R=Red, G=Green, B=Blue — natural color",
        "use": "General mapping, visual interpretation",
    },
    "false_color_infrared": {
        "label": "False Color Infrared (FCC)",
        "keys": COMPOSITE_REQUIRED_KEYS["false_color_infrared"],
        "display": {"R": "NIR", "G": "Red", "B": "Green"},
        "formula": "R=NIR, G=Red, B=Green — vegetation appears bright red",
        "use": "Vegetation vigor, land/water contrast (classic FCC)",
    },
    "false_color_agriculture": {
        "label": "Agriculture / SWIR",
        "keys": COMPOSITE_REQUIRED_KEYS["false_color_agriculture"],
        "display": {"R": "SWIR1", "G": "NIR", "B": "Blue"},
        "formula": "R=SWIR1, G=NIR, B=Blue — crops & soils",
        "use": "Crop health, bare soil vs vegetation",
    },
    "false_color_urban": {
        "label": "Urban / Built-up",
        "keys": COMPOSITE_REQUIRED_KEYS["false_color_urban"],
        "display": {"R": "SWIR1", "G": "NIR", "B": "Red"},
        "formula": "R=SWIR1, G=NIR, B=Red — built-up bright",
        "use": "Urban fabric, impervious surfaces (pairs with NDBI)",
    },
    "swir_composite": {
        "label": "SWIR Composite",
        "keys": COMPOSITE_REQUIRED_KEYS["swir_composite"],
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "Red"},
        "formula": "R=SWIR2, G=SWIR1, B=Red — moisture & geology",
        "use": "Soil moisture, lithology, burn scars",
    },
    "geology": {
        "label": "Geology / Lithology",
        "keys": COMPOSITE_REQUIRED_KEYS["geology"],
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "Blue"},
        "formula": "R=SWIR2, G=SWIR1, B=Blue — rock & soil types",
        "use": "Geological mapping",
    },
    "atmospheric_penetration": {
        "label": "Atmospheric Penetration",
        "keys": COMPOSITE_REQUIRED_KEYS["atmospheric_penetration"],
        "display": {"R": "SWIR2", "G": "SWIR1", "B": "NIR"},
        "formula": "R=SWIR2, G=SWIR1, B=NIR — haze penetration",
        "use": "Smoke/haze penetration, fire mapping",
    },
    "land_water": {
        "label": "Land / Water",
        "keys": COMPOSITE_REQUIRED_KEYS["land_water"],
        "display": {"R": "NIR", "G": "SWIR1", "B": "Red"},
        "formula": "R=NIR, G=SWIR1, B=Red — water dark, land bright",
        "use": "Shorelines, flooding (pairs with NDWI)",
    },
    "vegetation_health": {
        "label": "Vegetation Health (NIR-focused)",
        "keys": COMPOSITE_REQUIRED_KEYS["vegetation_health"],
        "display": {"R": "NIR", "G": "SWIR1", "B": "Green"},
        "formula": "R=NIR, G=SWIR1, B=Green — healthy veg bright",
        "use": "Vegetation stress (pairs with NDVI / NDMI)",
    },
    "burn_severity": {
        "label": "Burn Severity Preview",
        "keys": COMPOSITE_REQUIRED_KEYS["burn_severity"],
        "display": {"R": "SWIR2", "G": "NIR", "B": "Green"},
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
        "formula": "2.5 × (NIR−RED) / (NIR + 6·RED − 7.5·BLUE + 1)",
        "bands": "NIR + Red + Blue (S2: B08+B04+B02 · LS8: B5+B4+B2)",
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
        "formula": "LST(°C) = DN×0.00341802 + 149 − 273.15  (Landsat C2 L2 ST_B10)",
        "bands": "Thermal ST_B10 / lwir11 (Landsat-8/9 Collection-2 Level-2)",
        "thematic_rgb": "True Color underlay + thermal colormap",
        "colormap": "Thermal (°C)",
    },
}


class CompositeService:
    """Build RGB composites and stretch previews from scene analysis bands."""

    def list_presets(self, collection: str | None = None) -> list[dict[str, Any]]:
        family = normalize_satellite_family(collection) if collection else None
        out: list[dict[str, Any]] = []
        for key, meta in COMPOSITE_PRESETS.items():
            applicable = composite_applicable_families(key)
            sat_bands = COMPOSITE_BAND_CODES.get(key) or {}
            active = composite_for_family(key, family) if family else None
            # Default display codes: S2 / Landsat-8 / MODIS for UI cards
            s2 = (sat_bands.get("SENTINEL-2") or {}).get("codes", "")
            ls8 = (sat_bands.get("LANDSAT-8") or {}).get("codes", "")
            ls9 = (sat_bands.get("LANDSAT-9") or {}).get("codes", "")
            l7 = (sat_bands.get("LANDSAT-7") or {}).get("codes", "")
            modis = (sat_bands.get("MODIS") or {}).get("codes", "")
            formula = (active or {}).get("formula") or meta["formula"]
            codes = (active or {}).get("codes") or s2
            enabled = True if family is None else family in applicable
            reason = None
            if family and not enabled:
                reason = unsupported_image_processing_reason(family) or (
                    f"Not applicable to {family_label(family)} — needs optical "
                    f"SWIR/VIS bands (supported: {', '.join(family_label(f) for f in applicable)})"
                )
            out.append(
                {
                    "id": key,
                    "label": meta["label"],
                    "formula": formula,
                    "use": meta["use"],
                    "sentinel2": s2,
                    "landsat": ls8,
                    "landsat8": ls8,
                    "landsat9": ls9,
                    "landsat7": l7,
                    "modis": modis,
                    "bands": meta["display"],
                    "applicable": applicable,
                    "enabled": enabled,
                    "disabled_reason": reason,
                    "active_codes": codes if enabled else None,
                    "active_family": family if family and family != "UNKNOWN" else None,
                    "satellite_formulas": {
                        fam: {
                            "codes": info["codes"],
                            "formula": info["formula"],
                        }
                        for fam, info in sat_bands.items()
                    },
                }
            )
        return out

    def list_index_thematic(self, collection: str | None = None) -> list[dict[str, Any]]:
        family = normalize_satellite_family(collection) if collection else None
        rows: list[dict[str, Any]] = []
        for k, v in INDEX_THEMATIC.items():
            applicable = list(INDEX_APPLICABLE.get(k, OPTICAL_SWIR_FAMILY))
            enabled = True if family is None else family in applicable
            notes = INDEX_BAND_NOTES.get(k) or {}
            band_note = notes.get(family or "", v.get("bands", ""))
            reason = None
            if family and not enabled:
                if k == "LST":
                    reason = "LST requires Landsat-8/9 thermal (TIRS) in this app"
                else:
                    reason = unsupported_image_processing_reason(family) or (
                        f"Not applicable to {family_label(family)} — needs optical "
                        f"multispectral bands"
                    )
            rows.append(
                {
                    "id": k,
                    **v,
                    "bands": band_note or v.get("bands", ""),
                    "applicable": applicable,
                    "enabled": enabled,
                    "disabled_reason": reason,
                    "satellite_bands": notes,
                }
            )
        return rows

    def render_composite(self, request: CompositeRequest) -> CompositeResponse:
        preset_id = request.preset
        meta = COMPOSITE_PRESETS.get(preset_id)
        family = self._resolve_family(request.scene_id, request.collection)

        if request.red_band and request.green_band and request.blue_band:
            keys = (request.red_band, request.green_band, request.blue_band)
            label = f"Custom ({keys[0]}-{keys[1]}-{keys[2]})"
            display = {"R": keys[0], "G": keys[1], "B": keys[2]}
            formula = f"R={keys[0]}, G={keys[1]}, B={keys[2]}"
            band_keys = {"R": keys[0], "G": keys[1], "B": keys[2]}
        elif meta:
            applicable = composite_applicable_families(preset_id)
            if family and family not in applicable and family != "UNKNOWN":
                raise ValidationError(
                    f"'{meta['label']}' is not applicable to {family_label(family)}. "
                    f"Use with: {', '.join(family_label(f) for f in applicable)}."
                )
            keys = meta["keys"]
            label = meta["label"]
            display = meta["display"]
            sat = composite_for_family(preset_id, family) if family else None
            formula = (sat or {}).get("formula") or meta["formula"]
            band_keys = {"R": keys[0], "G": keys[1], "B": keys[2]}
        else:
            raise ValidationError(f"Unknown composite preset: {preset_id}")

        # True/false color: build from surface-reflectance bands with EO stretch.
        # Extent follows the scene layer bounds passed by the client (original image).
        # Use client size as-is — interactive map overlays stay fast on slow links.
        size = max(64, min(int(request.size or 512), 640))
        bands, bounds = self._load_bands(
            request.scene_id, request.bbox, size, band_names=keys
        )
        r = self._pick(bands, keys[0], required=True)
        g = self._pick(bands, keys[1], required=True)
        b = self._pick(bands, keys[2], required=True)
        valid_mask = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)

        if preset_id == "true_color":
            # Sentinel Hub L2A Optimized natural color (professional standard)
            from app.services.professional_viz import true_color_l2a_optimized

            rgb = true_color_l2a_optimized(
                r, g, b,
                brightness=request.brightness,
                contrast=request.contrast,
            )
            stretch_label = "l2a_optimized"
        else:
            from app.services.professional_viz import false_color_professional

            rgb = false_color_professional(
                r, g, b,
                p_low=request.p_low,
                p_high=request.p_high,
                gamma=request.gamma if request.gamma else 1.35,
                brightness=request.brightness,
                contrast=request.contrast,
            )
            stretch_label = "fcc_professional"

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
            message=(
                f"{label} · {family_label(family) if family else 'scene'} · "
                f"{stretch_label} · professional EO standard"
            ),
            stretch=f"{stretch_label} p{request.p_low}-{request.p_high}",
        )

    def _resolve_family(self, scene_id: str | None, collection: str | None) -> str | None:
        if collection:
            fam = normalize_satellite_family(collection)
            if fam != "UNKNOWN":
                return fam
        if scene_id:
            try:
                from app.services.scene_imagery_service import SceneImageryService

                layer = SceneImageryService().get_layer(scene_id)
                if layer and layer.get("collection"):
                    return normalize_satellite_family(str(layer["collection"]))
            except Exception:  # noqa: BLE001
                pass
        return None

    def stretch_scene(self, request: StretchRequest) -> StretchResponse:
        family = self._resolve_family(request.scene_id, None)
        if family:
            blocked = unsupported_image_processing_reason(family)
            if blocked:
                raise ValidationError(blocked)
        size = max(64, min(int(request.size or 512), 640))
        bands, bounds = self._load_bands(
            request.scene_id,
            request.bbox,
            size,
            band_names=("red", "green", "blue"),
        )
        r = self._pick(bands, "red")
        g = self._pick(bands, "green")
        b = self._pick(bands, "blue")
        valid_mask = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
        if request.source == "true_color":
            from app.services.professional_viz import true_color_l2a_optimized

            rgb = true_color_l2a_optimized(
                r, g, b,
                brightness=request.brightness,
                contrast=request.contrast,
            )
        else:
            from app.services.professional_viz import false_color_professional

            rgb = false_color_professional(
                r, g, b,
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

    def _true_color_stretch(
        self,
        r: np.ndarray,
        g: np.ndarray,
        b: np.ndarray,
        *,
        p_low: float,
        p_high: float,
        gamma: float,
        brightness: float,
        contrast: float,
    ) -> np.ndarray:
        """Natural-looking S2/Landsat true color from surface reflectance.

        Stretch statistics are computed on land (cloud/snow excluded), with a soft
        knee on highlights so bright clouds don't wash the whole composite out.
        """
        stacked = np.stack(
            [r.astype(np.float64), g.astype(np.float64), b.astype(np.float64)],
            axis=-1,
        )
        if np.nanmax(stacked) > 1.5:
            stacked = stacked / 10000.0
        stacked = np.clip(stacked, 0, 1)
        finite = np.all(np.isfinite(stacked), axis=2)
        bright = np.nanmean(stacked, axis=2)
        # Cloud / bright roof mask for statistics only
        cloud = finite & ((stacked[:, :, 2] > 0.25) | (bright > 0.28))
        land = finite & ~cloud
        if land.sum() < max(64, int(0.08 * max(1, finite.sum()))):
            land = self._land_mask(stacked)

        vals = stacked[land]
        if vals.size == 0:
            vals = stacked[finite]
        if vals.size == 0:
            return np.zeros_like(stacked)

        lo = float(np.percentile(vals, p_low))
        hi = float(np.percentile(vals, p_high))
        hi = min(max(hi, lo + 0.04), 0.24)
        lo = max(0.0, min(lo, hi - 0.03))

        norm = (stacked - lo) / (hi - lo + 1e-9)
        # Soft knee above 1.0 keeps cloud structure without crushing land
        over = norm > 1.0
        norm = np.where(over, 1.0 + 0.25 * np.tanh(norm - 1.0), np.clip(norm, 0, 1))
        norm = np.clip(norm, 0, 1.2) / 1.2
        norm[~finite] = 0

        g = float(gamma) if gamma and gamma > 0 else 1.45
        # Keep gamma moderate — too high re-washes urban surfaces
        out = np.power(np.clip(norm, 0, 1), 1.0 / max(1.2, min(g, 1.7)))

        # Mild saturation so vegetation/urban read clearer
        mean = out.mean(axis=2, keepdims=True)
        out = np.clip(mean + (out - mean) * 1.12, 0, 1)

        c = float(contrast) if contrast else 1.05
        bval = float(brightness) if brightness else 1.0
        out = (out - 0.5) * max(0.9, min(c, 1.15)) + 0.5
        out = out * max(0.9, min(bval, 1.1))
        return np.clip(out, 0, 1)

    def _load_bands(
        self,
        scene_id: str | None,
        bbox: list[float] | None,
        size: int,
        band_names: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[dict[str, np.ndarray], list[float]]:
        bounds = bbox if bbox and len(bbox) == 4 else [74.15, 31.35, 74.55, 31.7]
        if scene_id:
            from app.services.scene_imagery_service import SceneImageryService

            imagery = SceneImageryService()
            try:
                bands, bounds, _fp, _layer = imagery.load_analysis_bands(
                    scene_id,
                    size=size,
                    bounds=bbox,
                    band_names=band_names,
                )
            except ValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Composite band load failed: {}", exc)
                raise ValidationError(
                    "Failed to load satellite bands for this scene — "
                    "turn the eye off/on and retry True Color."
                ) from exc
            if not bands:
                raise ValidationError(
                    "No optical bands available for this scene — "
                    "turn the eye on first, then retry the composite."
                )
            return bands, bounds

        from app.services.analytics_service import AnalyticsService

        # Synthetic only for demos without a prepared scene — never mask COG failures.
        synth = AnalyticsService()._synthetic_bands(
            size=size, seed=hash(scene_id or "comp") % (2**31)
        )
        return synth, [float(x) for x in bounds]

    def _pick(
        self,
        bands: dict[str, np.ndarray],
        key: str,
        *,
        required: bool = False,
    ) -> np.ndarray:
        if key in bands:
            return bands[key].astype(np.float64)
        # Naming aliases only (never substitute a different spectral region)
        aliases = {
            "swir2": ["swir2", "swir22"],
            "swir": ["swir", "swir16"],
            "nir": ["nir", "nir08"],
            "red": ["red"],
            "green": ["green"],
            "blue": ["blue"],
            "thermal": ["thermal", "lwir11"],
        }
        for alt in aliases.get(key, [key]):
            if alt in bands:
                return bands[alt].astype(np.float64)
        if required:
            available = ", ".join(sorted(bands.keys())) or "none"
            raise ValidationError(
                f"Required band '{key}' is not available for this satellite "
                f"(have: {available}). Choose a composite that matches the sensor."
            )
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
        from app.services.overlay_encode import encode_rgb_mask_overlay

        data, _mime = encode_rgb_mask_overlay(rgb, valid_mask, quality=70)
        return data

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
