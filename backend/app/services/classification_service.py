"""Ensemble unsupervised land-cover classification (6 classes).

Produces a categorical map:
  snow, bare soil, built-up, vegetation, water, roads

Amalgam of:
  1) Adaptive spectral decision rules (NDVI / MNDWI / AWEI / NDBI / BSI)
  2) Over-clustered K-means mapped onto the 6 target classes
  3) OBIA-like object majority with spectral overrides
  4) Linear-feature enhancement for canals (water) and roads
  5) Wet-channel growth for turbid / wet river beds
"""

from __future__ import annotations

import base64
import io
import math

import numpy as np
from PIL import Image, ImageFilter

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.classification import (
    ClassAreaStat,
    ClassificationRequest,
    ClassificationResponse,
)

# Class ids
SNOW = 0
BARE_SOIL = 1
BUILT_UP = 2
VEGETATION = 3
WATER = 4
ROADS = 5
NODATA = 255
N_CLASSES = 6

CLASS_META: dict[int, dict[str, str]] = {
    SNOW: {"name": "snow", "label": "Snow", "color": "#FFFFFF"},
    BARE_SOIL: {"name": "bare_soil", "label": "Bare Soil", "color": "#D4A574"},
    BUILT_UP: {"name": "built_up", "label": "Built-up", "color": "#E85D04"},
    VEGETATION: {"name": "vegetation", "label": "Vegetation", "color": "#4CAF50"},
    WATER: {"name": "water", "label": "Water", "color": "#1565C0"},
    ROADS: {"name": "roads", "label": "Roads", "color": "#6B7280"},
}

# Backward-compatible aliases used by older helpers / tests
SOIL = BARE_SOIL


class ClassificationService:
    def classify(self, request: ClassificationRequest) -> ClassificationResponse:
        size = max(int(request.size), 1280)
        bands, bounds, footprint = self._load_bands(
            request.scene_id, request.bbox, size
        )
        features, valid = self._build_features(bands)
        valid = self._apply_footprint_mask(valid, bounds, footprint)
        if int(valid.sum()) < 64:
            raise ValidationError(
                "Not enough valid pixels to classify — show a Sentinel-2 or Landsat scene first"
            )

        thresholds = self._adaptive_thresholds(features, valid)
        cloud = self._cloud_mask(features, valid)

        rule_map, rule_conf = self._classify_spectral_rules(
            features, valid, cloud, thresholds
        )
        kmeans_map, kmeans_conf = self._classify_kmeans(
            features, valid, cloud, thresholds
        )
        obia_map = self._classify_obia_like(
            features, valid, cloud, thresholds, seed_map=kmeans_map
        )

        amalgam, agreement = self._weighted_amalgam(
            [
                (rule_map, rule_conf, 1.50),
                (kmeans_map, kmeans_conf, 1.0),
                (obia_map, np.clip(kmeans_conf * 0.9 + 0.1, 0, 1), 0.85),
            ],
            valid,
            cloud,
            features,
            thresholds,
        )
        amalgam = self._cleanup_implausible_snow(amalgam, features, valid, thresholds)
        amalgam = self._recover_dark_water(amalgam, features, valid, thresholds)
        amalgam = self._refine_water_bodies(amalgam, features, valid, thresholds)
        amalgam = self._expand_wet_channels(amalgam, features, valid, thresholds)
        amalgam = self._enhance_linear_features(amalgam, features, valid, thresholds)
        amalgam = self._refine_impervious(amalgam, features, valid, thresholds)
        amalgam = self._majority_filter(amalgam, valid, iterations=1)
        amalgam = self._expand_wet_channels(
            amalgam, features, valid, thresholds, iterations=4
        )
        amalgam = self._enhance_linear_features(amalgam, features, valid, thresholds)
        amalgam = self._recover_dark_water(amalgam, features, valid, thresholds)
        amalgam = self._strip_false_vegetation(amalgam, features, valid, thresholds)

        stats, total_km2 = self._area_stats(amalgam, valid, bounds)
        overlay = self._class_map_to_png(amalgam, valid)

        return ClassificationResponse(
            scene_id=request.scene_id,
            algorithm="amalgam(adaptive_rules + ISODATA-kmeans + OBIA-like + linear)",
            classes=stats,
            total_area_km2=total_km2,
            valid_pixels=int(valid.sum()),
            bounds=[float(x) for x in bounds],
            overlay_base64=base64.b64encode(overlay).decode("ascii"),
            legend=self._legend(),
            formula=(
                "6-class unsupervised LULC: Snow / Bare Soil / Built-up / Vegetation / "
                "Water / Roads — adaptive spectral rules ⊕ over-clustered K-means ⊕ "
                "OBIA-like majority ⊕ canal/road linear enhancement ⊕ wet-channel growth"
            ),
            message=(
                f"Classified into {N_CLASSES} classes · agreement {agreement:.0f}% · "
                f"total {total_km2:.2f} km²"
            ),
            agreement_percent=round(float(agreement), 1),
            metadata={
                "members": [
                    "adaptive_spectral_rules",
                    "isodata_kmeans",
                    "obia_like",
                    "linear_roads_canals",
                ],
                "n_classes": N_CLASSES,
                "thresholds": {k: round(float(v), 4) for k, v in thresholds.items()},
                "cloud_pixels": int(cloud.sum()),
                "colors": {m["name"]: m["color"] for m in CLASS_META.values()},
                "footprint_clipped": bool(footprint),
            },
        )

    def results_csv(self, result: ClassificationResponse) -> str:
        rows = ["class_id,name,label,color,pixels,percent,area_km2"]
        for c in result.classes:
            rows.append(
                f"{c.class_id},{c.name},{c.label},{c.color},{c.pixels},"
                f"{c.percent:.4f},{c.area_km2:.6f}"
            )
        rows.append(f",,,TOTAL,,,{result.total_area_km2:.6f}")
        rows.append(f"algorithm,,,{result.algorithm},,,")
        rows.append(f"agreement_percent,,,{result.agreement_percent},,,")
        rows.append(f"valid_pixels,,,{result.valid_pixels},,,")
        rows.append(f"bounds,,,{' '.join(str(x) for x in result.bounds)},,,")
        return "\n".join(rows) + "\n"

    # ------------------------------------------------------------------ load
    def _load_bands(
        self, scene_id: str, bbox: list[float] | None, size: int
    ) -> tuple[dict[str, np.ndarray], list[float], dict | None]:
        from app.services.scene_imagery_service import SceneImageryService

        imagery = SceneImageryService()
        bands, bounds, footprint, _layer = imagery.load_analysis_bands(
            scene_id, size=size, bounds=bbox
        )
        if not bands:
            raise ValidationError("No optical bands available for classification")
        return bands, [float(x) for x in bounds], footprint

    def _apply_footprint_mask(
        self,
        valid: np.ndarray,
        bounds: list[float],
        footprint: dict | None,
    ) -> np.ndarray:
        if not footprint or footprint.get("type") != "Polygon":
            return valid
        try:
            from shapely.geometry import Point, shape
        except ImportError:
            return valid
        try:
            geom = shape(footprint)
        except Exception:  # noqa: BLE001
            return valid

        h, w = valid.shape
        west, south, east, north = (float(v) for v in bounds)
        if east <= west or north <= south or h < 2 or w < 2:
            return valid

        step = 4 if min(h, w) >= 128 else 2
        ys = np.linspace(north, south, h, endpoint=False) + (south - north) / (2 * h)
        xs = np.linspace(west, east, w, endpoint=False) + (east - west) / (2 * w)
        mask_small = np.zeros(
            ((h + step - 1) // step, (w + step - 1) // step), dtype=bool
        )
        for iy, lat in enumerate(ys[::step]):
            for ix, lon in enumerate(xs[::step]):
                if iy >= mask_small.shape[0] or ix >= mask_small.shape[1]:
                    continue
                mask_small[iy, ix] = geom.contains(Point(lon, lat)) or geom.touches(
                    Point(lon, lat)
                )
        mask = np.repeat(np.repeat(mask_small, step, axis=0), step, axis=1)[:h, :w]
        if mask.shape != valid.shape:
            padded = np.zeros_like(valid, dtype=bool)
            padded[: mask.shape[0], : mask.shape[1]] = mask
            mask = padded
        return valid & mask

    def _pick(self, bands: dict[str, np.ndarray], *keys: str) -> np.ndarray | None:
        for k in keys:
            if k in bands:
                return bands[k].astype(np.float64)
        return None

    def _build_features(
        self, bands: dict[str, np.ndarray]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        blue = self._pick(bands, "blue", "coastal")
        green = self._pick(bands, "green")
        red = self._pick(bands, "red")
        nir = self._pick(bands, "nir", "nir08")
        swir1 = self._pick(bands, "swir", "swir16")
        swir2 = self._pick(bands, "swir2", "swir22", "swir", "swir16")

        ref = next(v for v in (red, green, blue, nir) if v is not None)
        h, w = ref.shape

        def _fill(a: np.ndarray | None, fallback: np.ndarray) -> np.ndarray:
            return fallback.copy() if a is None else a.astype(np.float64)

        blue = _fill(blue, np.zeros((h, w)))
        green = _fill(green, np.zeros((h, w)))
        red = _fill(red, np.zeros((h, w)))
        nir = _fill(nir, green)
        swir1 = _fill(swir1, red)
        swir2 = _fill(swir2, swir1)

        def _norm(a: np.ndarray) -> np.ndarray:
            out = a.astype(np.float64)
            finite = np.isfinite(out)
            if finite.any() and float(np.nanmax(out[finite])) > 1.5:
                out = out / 10000.0
            out = np.clip(out, 0, 1)
            out[~finite] = np.nan
            return out

        blue, green, red, nir, swir1, swir2 = map(
            _norm, (blue, green, red, nir, swir1, swir2)
        )
        valid = (
            np.isfinite(blue)
            & np.isfinite(green)
            & np.isfinite(red)
            & np.isfinite(nir)
            & np.isfinite(swir1)
            & ((red + green + blue + nir) > 0.015)
        )

        eps = 1e-6
        ndvi = (nir - red) / (nir + red + eps)
        evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0 + eps)
        evi = np.clip(evi, -1.0, 1.0)
        savi = 1.5 * (nir - red) / (nir + red + 0.5 + eps)
        ndwi = (green - nir) / (green + nir + eps)
        mndwi = (green - swir1) / (green + swir1 + eps)
        ndsi = (green - swir1) / (green + swir1 + eps)
        ndbi = (swir1 - nir) / (swir1 + nir + eps)
        bu = ndbi - ndvi
        bsi = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue) + eps)
        awei = 4.0 * (green - swir1) - (0.25 * nir + 2.75 * swir2)
        brightness = (blue + green + red) / 3.0
        dark_ir = 1.0 - np.clip((nir + swir1) * 0.5 / 0.25, 0, 1)
        shadow = (brightness < 0.08) & (nir < 0.12)
        # UI / asphalt cue: low chroma, moderate brightness, low NDVI
        grey = 1.0 - np.clip(
            (
                np.abs(red - green)
                + np.abs(green - blue)
                + np.abs(red - blue)
            )
            / 0.18,
            0,
            1,
        )

        return {
            "blue": blue,
            "green": green,
            "red": red,
            "nir": nir,
            "swir1": swir1,
            "swir2": swir2,
            "ndvi": ndvi,
            "evi": evi,
            "savi": savi,
            "ndwi": ndwi,
            "mndwi": mndwi,
            "ndsi": ndsi,
            "ndbi": ndbi,
            "bu": bu,
            "bsi": bsi,
            "awei": awei,
            "dark_ir": dark_ir,
            "brightness": brightness,
            "grey": grey,
            "shadow": shadow.astype(np.float64),
        }, valid

    def _pct(self, arr: np.ndarray, mask: np.ndarray, q: float, default: float) -> float:
        vals = arr[mask]
        vals = vals[np.isfinite(vals)]
        if vals.size < 32:
            return default
        return float(np.percentile(vals, q))

    def _adaptive_thresholds(
        self, f: dict[str, np.ndarray], valid: np.ndarray
    ) -> dict[str, float]:
        ndvi, evi = f["ndvi"], f["evi"]
        mndwi, ndsi, ndbi, bsi = f["mndwi"], f["ndsi"], f["ndbi"], f["bsi"]
        bright, awei = f["brightness"], f["awei"]

        ndvi_p50 = self._pct(ndvi, valid, 50, 0.22)
        ndvi_p70 = self._pct(ndvi, valid, 70, 0.32)
        ndvi_p40 = self._pct(ndvi, valid, 40, 0.16)
        evi_p65 = self._pct(evi, valid, 65, 0.22)
        mndwi_p85 = self._pct(mndwi, valid, 85, 0.02)
        mndwi_p90 = self._pct(mndwi, valid, 90, 0.05)
        ndsi_p70 = self._pct(ndsi, valid, 70, 0.10)
        ndsi_p85 = self._pct(ndsi, valid, 85, 0.25)
        ndsi_p95 = self._pct(ndsi, valid, 95, 0.35)
        ndbi_p70 = self._pct(ndbi, valid, 70, 0.0)
        bsi_p60 = self._pct(bsi, valid, 60, 0.05)
        bright_p85 = self._pct(bright, valid, 85, 0.35)
        awei_p85 = self._pct(awei, valid, 85, 0.0)
        swir_p50 = self._pct(f["swir1"], valid, 50, 0.15)

        arid_ag = ndvi_p50 < 0.30 and ndsi_p85 < 0.25
        snowy_scene = ndsi_p70 > 0.18 or ndsi_p85 > 0.30

        if snowy_scene:
            snow_ndsi = float(np.clip(max(0.22, min(0.45, ndsi_p70 * 0.90)), 0.20, 0.48))
            snow_bright = float(np.clip(max(0.18, bright_p85 * 0.55), 0.16, 0.40))
        else:
            snow_ndsi = float(np.clip(max(0.40, min(0.70, ndsi_p95 * 0.92)), 0.38, 0.75))
            snow_bright = float(np.clip(max(0.28, bright_p85 * 0.85), 0.25, 0.55))

        # Vegetation must be STRICT — roads/canals were collapsing into agriculture
        if arid_ag:
            veg_ndvi = float(np.clip(max(0.22, min(0.38, ndvi_p70 * 0.88)), 0.20, 0.40))
            soil_ndvi_max = float(np.clip(max(0.10, min(0.22, ndvi_p40)), 0.08, 0.24))
            water_mndwi = float(
                np.clip(max(0.03, min(0.18, mndwi_p85 * 0.50)), 0.02, 0.20)
            )
        else:
            veg_ndvi = float(np.clip(max(0.26, min(0.42, ndvi_p70 * 0.90)), 0.24, 0.45))
            soil_ndvi_max = float(np.clip(max(0.12, min(0.24, ndvi_p40)), 0.10, 0.26))
            water_mndwi = float(
                np.clip(max(0.04, min(0.22, mndwi_p90 * 0.55)), 0.03, 0.26)
            )

        return {
            "veg_ndvi": veg_ndvi,
            "veg_evi": float(np.clip(max(0.16, min(0.40, evi_p65 * 0.92)), 0.14, 0.42)),
            "soil_ndvi_max": soil_ndvi_max,
            "water_mndwi": water_mndwi,
            "water_awei": float(
                np.clip(max(-0.08, min(0.25, awei_p85 * 0.40)), -0.12, 0.30)
            ),
            "water_nir_max": 0.16,
            "water_swir_max": float(np.clip(min(0.16, swir_p50 * 0.65), 0.10, 0.18)),
            "water_bright_max": 0.32,
            "wet_nir_max": 0.28,
            "wet_swir_max": 0.28,
            "wet_bright_max": 0.45,
            "wet_mndwi_min": float(np.clip(water_mndwi - 0.14, -0.12, 0.10)),
            "snow_ndsi": snow_ndsi,
            "snow_bright": snow_bright,
            "snowy_scene": 1.0 if snowy_scene else 0.0,
            "arid_ag": 1.0 if arid_ag else 0.0,
            "urban_ndbi": float(np.clip(ndbi_p70 - 0.01, -0.06, 0.20)),
            "road_ndbi": float(np.clip(ndbi_p70 - 0.04, -0.10, 0.16)),
            "bare_bsi": float(np.clip(bsi_p60, -0.05, 0.35)),
            "cloud_bright": float(np.clip(bright_p85 + 0.05, 0.32, 0.60)),
        }

    def _cloud_mask(
        self, f: dict[str, np.ndarray], valid: np.ndarray
    ) -> np.ndarray:
        bright, blue, nir = f["brightness"], f["blue"], f["nir"]
        swir1, ndvi, ndsi = f["swir1"], f["ndvi"], f["ndsi"]
        return (
            valid
            & (bright > 0.34)
            & (blue > 0.28)
            & (ndvi < 0.18)
            & (swir1 > 0.08)
            & (nir > 0.20)
            & ~((ndsi > 0.45) & (swir1 < 0.12))
        )

    def _hard_urban_mask(
        self, f: dict[str, np.ndarray], t: dict[str, float]
    ) -> np.ndarray:
        return (
            (f["ndbi"] > t["urban_ndbi"] + 0.03)
            & (f["swir1"] > 0.18)
            & (f["nir"] > 0.20)
            & (f["brightness"] > 0.24)
            & (f["mndwi"] < t["water_mndwi"] - 0.03)
            & (f["ndvi"] < t["veg_ndvi"] - 0.04)
        )

    def _elongation(self, mask: np.ndarray) -> np.ndarray:
        """Directional contrast — high for canals/roads, low for blob fields."""
        m = mask.astype(np.float64)
        h = sum(np.roll(m, i, axis=1) for i in range(-3, 4))
        v = sum(np.roll(m, i, axis=0) for i in range(-3, 4))
        d1 = sum(np.roll(np.roll(m, i, 0), i, 1) for i in range(-3, 4))
        d2 = sum(np.roll(np.roll(m, i, 0), -i, 1) for i in range(-3, 4))
        stack = np.stack([h, v, d1, d2], axis=0)
        return stack.max(axis=0) - stack.min(axis=0)

    # --------------------------------------------------------- classifiers
    def _classify_spectral_rules(
        self,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        cloud: np.ndarray,
        t: dict[str, float],
    ) -> tuple[np.ndarray, np.ndarray]:
        h, w = valid.shape
        out = np.full((h, w), NODATA, dtype=np.uint8)
        conf = np.zeros((h, w), dtype=np.float64)

        ndvi, evi, savi = f["ndvi"], f["evi"], f["savi"]
        mndwi, ndwi, awei = f["mndwi"], f["ndwi"], f["awei"]
        ndsi, ndbi, bu, bsi = f["ndsi"], f["ndbi"], f["bu"], f["bsi"]
        bright, nir, swir1, grey = f["brightness"], f["nir"], f["swir1"], f["grey"]
        land = valid & ~cloud

        urban_like = self._hard_urban_mask(f, t)
        red = f["red"]
        # Pitch-black / near-zero reflectance — NDVI is unstable here and must
        # never be treated as vegetation (common failure on canals & rivers).
        pitch_black = (
            (bright < 0.12)
            & (nir < 0.09)
            & (swir1 < 0.09)
            & ((red + f["green"] + f["blue"]) < 0.28)
        )

        # --- Water (clear + turbid + pitch-black); canals refined by linear enhance
        water_black = land & ~urban_like & pitch_black
        water_core = (
            land
            & ~urban_like
            & ~pitch_black
            & (ndvi < 0.20)
            & (nir < t["water_nir_max"])
            & (swir1 < t["water_swir_max"])
            & (bright < t["water_bright_max"])
            & (
                (mndwi > t["water_mndwi"])
                | (awei > t["water_awei"])
                | ((mndwi > t["water_mndwi"] - 0.03) & (ndwi > 0.0))
            )
        )
        water_dark = (
            land
            & ~urban_like
            & (nir < 0.11)
            & (swir1 < 0.11)
            & (bright < 0.20)
            # Do NOT require low NDVI — dark water often has noisy NDVI
            & (
                (mndwi > t["water_mndwi"] - 0.08)
                | (awei > t["water_awei"] - 0.10)
                | (ndwi > -0.15)
                | pitch_black
            )
        )
        water_turbid = (
            land
            & ~urban_like
            & (ndvi < 0.18)
            & (nir < t["wet_nir_max"])
            & (swir1 < t["wet_swir_max"])
            & (bright < t["wet_bright_max"])
            & (nir <= f["green"] * 1.15 + 0.02)
            & (
                (mndwi > t["wet_mndwi_min"])
                | (ndwi > -0.08)
                | (awei > t["water_awei"] - 0.10)
            )
            & (
                (mndwi > t["water_mndwi"] - 0.06)
                | (awei > t["water_awei"] - 0.04)
                | ((ndwi > -0.02) & (nir < 0.18))
            )
        )
        water = water_black | water_core | water_dark | water_turbid

        # --- Snow
        snow = (
            land
            & ~water
            & (ndsi > t["snow_ndsi"])
            & (bright > t["snow_bright"])
            & (swir1 < 0.16)
            & (ndvi < 0.15)
            & (f["blue"] > 0.22)
        )

        # --- Vegetation: requires HIGH NIR (photosynthetic). Dark water has low NIR
        # even when noisy NDVI looks "green", so NIR floor is the key guardrail.
        veg = (
            land
            & ~water
            & ~snow
            & ~pitch_black
            & (nir > 0.18)  # crops/trees are bright in NIR; canals are not
            & (bright > 0.08)
            & (mndwi < t["water_mndwi"] + 0.02)
            & (ndvi > t["veg_ndvi"])
            & (evi > t["veg_evi"] * 0.75)
            & (bsi < t["bare_bsi"] + 0.12)
        )
        veg |= (
            land
            & ~water
            & ~snow
            & ~pitch_black
            & ~veg
            & (nir > 0.22)
            & (ndvi > t["veg_ndvi"] + 0.04)
            & (savi > t["veg_ndvi"])
            & (mndwi < t["water_mndwi"])
        )

        # --- Built-up first: bright roofs / dense settlement clusters
        built = (
            land
            & ~water
            & ~snow
            & ~veg
            & (ndvi < t["veg_ndvi"] - 0.04)
            & (mndwi < t["water_mndwi"])
            & (
                urban_like
                | (
                    (ndbi > t["urban_ndbi"] - 0.02)
                    & (bright > 0.26)
                    & (swir1 > 0.16)
                )
                | (
                    (bu > 0.0)
                    & (bright > 0.28)
                    & (ndvi < t["soil_ndvi_max"] + 0.06)
                    & (swir1 > 0.18)
                )
            )
        )

        # --- Roads: mid-tone grey asphalt (not bright roofs), low NDVI, not water
        roads = (
            land
            & ~water
            & ~snow
            & ~veg
            & ~built
            & (ndvi < t["soil_ndvi_max"] + 0.06)
            & (ndvi < t["veg_ndvi"] - 0.08)
            & (mndwi < t["water_mndwi"] - 0.02)
            & (nir > t["water_nir_max"] * 0.7)
            & (bright > 0.12)
            & (bright < 0.30)  # roofs are brighter; keep those as built-up
            & (
                ((ndbi > t["road_ndbi"] - 0.02) & (grey > 0.45))
                | ((bu > -0.02) & (grey > 0.50) & (ndvi < 0.18))
            )
        )

        # --- Bare soil / fallow
        bare = (
            land
            & ~water
            & ~snow
            & ~veg
            & ~roads
            & ~built
            & (
                (ndvi < t["soil_ndvi_max"] + 0.04)
                | ((bsi > t["bare_bsi"] - 0.02) & (ndvi < t["veg_ndvi"] - 0.06))
            )
        )
        leftover = land & ~water & ~snow & ~veg & ~roads & ~built & ~bare
        bare |= leftover

        # Shadows → bare (unless water)
        shadow = f["shadow"] > 0.5
        shadow_land = land & shadow & ~water
        bare |= shadow_land
        veg &= ~shadow_land

        out[bare] = BARE_SOIL
        out[built] = BUILT_UP
        out[veg] = VEGETATION
        out[snow] = SNOW
        out[water] = WATER
        out[roads] = ROADS
        out[cloud & valid] = BARE_SOIL

        conf[water] = np.clip((mndwi[water] - t["water_mndwi"]) / 0.25 + 0.45, 0.35, 1)
        conf[snow] = np.clip((ndsi[snow] - t["snow_ndsi"]) / 0.25 + 0.40, 0.30, 1)
        conf[veg] = np.clip((ndvi[veg] - t["veg_ndvi"]) / 0.30 + 0.45, 0.35, 1)
        conf[roads] = np.clip(0.40 + grey[roads] * 0.35 + np.maximum(0, ndbi[roads]) * 0.5, 0.30, 0.90)
        conf[built] = np.clip(0.40 + np.maximum(0, ndbi[built]) * 0.9, 0.30, 0.90)
        conf[bare] = np.clip(0.30 + np.maximum(0, bsi[bare]) * 0.5, 0.25, 0.80)
        conf[cloud & valid] = 0.20
        conf[~valid] = 0
        return out, conf

    def _classify_kmeans(
        self,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        cloud: np.ndarray,
        t: dict[str, float],
    ) -> tuple[np.ndarray, np.ndarray]:
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.preprocessing import StandardScaler

        h, w = valid.shape
        out = np.full((h, w), NODATA, dtype=np.uint8)
        conf = np.zeros((h, w), dtype=np.float64)

        train_mask = valid & ~cloud
        if int(train_mask.sum()) < 128:
            train_mask = valid

        keys = [
            "blue",
            "green",
            "red",
            "nir",
            "swir1",
            "ndvi",
            "evi",
            "mndwi",
            "awei",
            "ndsi",
            "ndbi",
            "bu",
            "bsi",
            "brightness",
            "grey",
        ]
        stack = np.stack([f[k] for k in keys], axis=-1)
        samples = stack[train_mask]
        if samples.shape[0] < 64:
            return out, conf

        rng = np.random.default_rng(42)
        n = samples.shape[0]
        idx = rng.choice(n, size=min(n, 80000), replace=False)
        train = samples[idx]
        scaler = StandardScaler()
        train_z = scaler.fit_transform(train)

        n_clusters = int(np.clip(round(math.sqrt(max(n, 256)) / 2.4), 12, 20))
        km = MiniBatchKMeans(
            n_clusters=n_clusters,
            random_state=42,
            batch_size=8192,
            n_init=5,
            max_iter=140,
        )
        km.fit(train_z)

        labels = km.predict(scaler.transform(stack[valid]))
        centers = scaler.inverse_transform(km.cluster_centers_)

        i_ndvi, i_evi, i_mndwi, i_awei = 5, 6, 7, 8
        i_ndsi, i_ndbi, i_bu, i_bsi = 9, 10, 11, 12
        i_bright, i_grey = 13, 14
        i_nir, i_swir = 3, 4

        mapping: dict[int, int] = {}
        strength: dict[int, float] = {}
        for cid in range(n_clusters):
            ndvi_c = float(centers[cid, i_ndvi])
            evi_c = float(centers[cid, i_evi])
            mndwi_c = float(centers[cid, i_mndwi])
            awei_c = float(centers[cid, i_awei])
            ndsi_c = float(centers[cid, i_ndsi])
            ndbi_c = float(centers[cid, i_ndbi])
            bu_c = float(centers[cid, i_bu])
            bsi_c = float(centers[cid, i_bsi])
            bright_c = float(centers[cid, i_bright])
            grey_c = float(centers[cid, i_grey])
            nir_c = float(centers[cid, i_nir])
            swir_c = float(centers[cid, i_swir])

            scores = {
                WATER: (
                    2.4 * mndwi_c
                    + 1.6 * awei_c
                    - 1.4 * ndvi_c
                    - 1.6 * nir_c
                    - 1.8 * swir_c
                    - 1.2 * max(ndbi_c, 0)
                    + (0.6 if bright_c < 0.22 else -0.8)
                ),
                SNOW: (
                    2.6 * ndsi_c
                    + 1.1 * bright_c
                    - 1.4 * swir_c
                    - 1.0 * max(ndvi_c, 0)
                ),
                VEGETATION: (
                    3.0 * ndvi_c
                    + 1.4 * evi_c
                    - 1.2 * max(mndwi_c, 0)
                    - 0.8 * max(ndbi_c, 0)
                    - 0.8 * max(bsi_c, 0)
                ),
                ROADS: (
                    1.4 * grey_c
                    + 1.2 * ndbi_c
                    + 0.6 * bu_c
                    - 2.2 * ndvi_c
                    - 1.0 * max(mndwi_c, 0)
                    + (0.4 if 0.14 < bright_c < 0.40 else -0.5)
                ),
                BUILT_UP: (
                    1.8 * ndbi_c
                    + 1.2 * bu_c
                    + 0.8 * bright_c
                    - 1.8 * ndvi_c
                    - 1.0 * max(mndwi_c, 0)
                    - 0.4 * grey_c
                ),
                BARE_SOIL: (
                    1.4 * bsi_c
                    + 0.6 * swir_c
                    - 1.6 * ndvi_c
                    - 0.8 * max(mndwi_c, 0)
                    + 0.2
                ),
            }
            if ndsi_c < t["snow_ndsi"] - 0.05 or swir_c > 0.18:
                scores[SNOW] -= 2.5
            if (
                mndwi_c < t["water_mndwi"] - 0.03 and awei_c < t["water_awei"] - 0.05
            ) or nir_c > t["water_nir_max"] + 0.04:
                scores[WATER] -= 2.8
            if ndvi_c < t["veg_ndvi"] - 0.02:
                scores[VEGETATION] -= 2.0
            if grey_c < 0.35 or ndvi_c > 0.22:
                scores[ROADS] -= 1.5
            if ndbi_c < t["urban_ndbi"] - 0.02 and bright_c < 0.22:
                scores[BUILT_UP] -= 1.2

            best = max(scores, key=scores.get)
            mapping[cid] = best
            ordered = sorted(scores.values(), reverse=True)
            strength[cid] = float(
                np.clip(
                    (ordered[0] - ordered[1]) / (abs(ordered[0]) + 0.5) + 0.35,
                    0.2,
                    1.0,
                )
            )

        mapped = np.array([mapping[int(x)] for x in labels], dtype=np.uint8)
        conf_vals = np.array([strength[int(x)] for x in labels], dtype=np.float64)
        out[valid] = mapped
        conf[valid] = conf_vals
        out[cloud & valid] = BARE_SOIL
        conf[cloud & valid] = np.minimum(conf[cloud & valid], 0.25)
        return out, conf

    def _classify_obia_like(
        self,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        cloud: np.ndarray,
        t: dict[str, float],
        seed_map: np.ndarray,
    ) -> np.ndarray:
        ndvi_s = self._smooth(f["ndvi"], radius=1.5)
        mndwi_s = self._smooth(f["mndwi"], radius=1.5)
        ndsi_s = self._smooth(f["ndsi"], radius=1.5)
        bright_s = self._smooth(f["brightness"], radius=1.5)
        ndbi_s = self._smooth(f["ndbi"], radius=1.5)
        grey_s = self._smooth(f["grey"], radius=1.2)

        ndvi_q = np.digitize(ndvi_s, bins=[-0.05, 0.12, 0.22, 0.35, 0.5, 0.65])
        mndwi_q = np.digitize(mndwi_s, bins=[-0.2, -0.05, 0.05, 0.15, 0.3])
        bright_q = np.digitize(bright_s, bins=[0.08, 0.15, 0.25, 0.35, 0.5])
        object_id = (ndvi_q * 100 + mndwi_q * 10 + bright_q).astype(np.int32)
        object_id[~valid] = -1

        out = seed_map.copy()
        for oid in np.unique(object_id):
            if oid < 0:
                continue
            mask = object_id == oid
            if cloud[mask].mean() > 0.55:
                out[mask] = BARE_SOIL
                continue
            vals = seed_map[mask]
            vals = vals[vals != NODATA]
            if vals.size == 0:
                continue
            majority = int(np.argmax(np.bincount(vals, minlength=N_CLASSES)))
            out[mask] = majority

            mean_mndwi = float(np.nanmean(mndwi_s[mask]))
            mean_ndvi = float(np.nanmean(ndvi_s[mask]))
            mean_ndsi = float(np.nanmean(ndsi_s[mask]))
            mean_bright = float(np.nanmean(bright_s[mask]))
            mean_ndbi = float(np.nanmean(ndbi_s[mask]))
            mean_nir = float(np.nanmean(f["nir"][mask]))
            mean_swir = float(np.nanmean(f["swir1"][mask]))
            mean_awei = float(np.nanmean(f["awei"][mask]))
            mean_grey = float(np.nanmean(grey_s[mask]))

            if (
                mean_ndvi < 0.14
                and mean_nir < t["water_nir_max"]
                and mean_swir < t["water_swir_max"]
                and mean_bright < t["water_bright_max"]
                and mean_ndbi < t["urban_ndbi"] + 0.05
                and (mean_mndwi > t["water_mndwi"] or mean_awei > t["water_awei"])
            ):
                out[mask] = WATER
            elif (
                mean_ndsi > t["snow_ndsi"]
                and mean_bright > t["snow_bright"]
                and mean_ndvi < 0.15
                and mean_swir < 0.14
            ):
                out[mask] = SNOW
            elif mean_ndvi > t["veg_ndvi"] and mean_mndwi < t["water_mndwi"]:
                out[mask] = VEGETATION
            elif (
                mean_ndvi < t["veg_ndvi"] - 0.06
                and mean_grey > 0.48
                and mean_mndwi < t["water_mndwi"] - 0.02
                and 0.12 < mean_bright < 0.40
            ):
                out[mask] = ROADS
            elif mean_ndbi > t["urban_ndbi"] and mean_ndvi < t["veg_ndvi"] - 0.04:
                out[mask] = BUILT_UP
            elif mean_ndvi < t["soil_ndvi_max"] + 0.04:
                out[mask] = BARE_SOIL

        out[~valid] = NODATA
        out[cloud & valid] = BARE_SOIL
        return out

    def _weighted_amalgam(
        self,
        members: list[tuple[np.ndarray, np.ndarray, float]],
        valid: np.ndarray,
        cloud: np.ndarray,
        f: dict[str, np.ndarray],
        t: dict[str, float],
    ) -> tuple[np.ndarray, float]:
        h, w = valid.shape
        scores = np.zeros((N_CLASSES, h, w), dtype=np.float64)
        for class_map, conf, weight in members:
            for cid in range(N_CLASSES):
                hit = (class_map == cid) & valid
                scores[cid][hit] += weight * conf[hit]

        wet = np.clip(
            np.maximum(
                (f["mndwi"] - t["water_mndwi"]) / 0.2,
                (f["awei"] - t["water_awei"]) / 0.3,
            ),
            0,
            1,
        ) * f["dark_ir"]
        scores[WATER] += 0.75 * wet * valid

        urban_prior = np.clip(
            0.5 * np.clip((f["ndbi"] - t["urban_ndbi"]) / 0.2, 0, 1)
            + 0.4 * np.clip((f["swir1"] - t["water_swir_max"]) / 0.15, 0, 1)
            + 0.3 * np.clip((f["brightness"] - t["water_bright_max"]) / 0.2, 0, 1),
            0,
            1,
        )
        scores[BUILT_UP] += 0.65 * urban_prior * valid
        scores[WATER] -= 1.10 * urban_prior * valid

        scores[WATER] -= 0.45 * np.clip(
            (f["nir"] - t["wet_nir_max"]) / 0.15, 0, 1
        ) * valid
        scores[WATER] += 0.55 * np.clip(
            (f["mndwi"] - t["wet_mndwi_min"]) / 0.25, 0, 1
        ) * (f["ndvi"] < 0.18) * valid

        # Strong vegetation prior only for truly green + high-NIR pixels
        scores[VEGETATION] += 0.70 * np.clip(
            (f["ndvi"] - t["veg_ndvi"]) / 0.25, 0, 1
        ) * (f["nir"] > 0.18) * valid
        # Anti-veg prior for low-NDVI / dark / low-NIR (roads, canals, soil)
        scores[VEGETATION] -= 1.20 * np.clip(
            (t["veg_ndvi"] - f["ndvi"]) / 0.25, 0, 1
        ) * valid
        scores[VEGETATION] -= 1.80 * np.clip((0.14 - f["nir"]) / 0.10, 0, 1) * valid
        scores[VEGETATION] -= 1.50 * np.clip((0.12 - f["brightness"]) / 0.10, 0, 1) * valid
        # Pitch-black → hard water prior
        scores[WATER] += 1.40 * np.clip((0.12 - f["brightness"]) / 0.10, 0, 1) * (
            f["nir"] < 0.12
        ) * valid

        scores[ROADS] += 0.55 * np.clip(f["grey"] - 0.4, 0, 1) * (
            f["ndvi"] < t["veg_ndvi"] - 0.06
        ) * valid
        scores[BARE_SOIL] += 0.40 * np.clip(
            (f["bsi"] - t["bare_bsi"]) / 0.25, 0, 1
        ) * valid
        scores[SNOW] += 0.50 * np.clip(
            (f["ndsi"] - t["snow_ndsi"]) / 0.2, 0, 1
        ) * valid

        scores[SNOW][cloud] = -1
        scores[WATER][cloud] = -1

        winner = np.argmax(scores, axis=0).astype(np.uint8)
        out = np.full((h, w), NODATA, dtype=np.uint8)
        out[valid] = winner[valid]
        out[cloud & valid] = BARE_SOIL

        stack = np.stack([m[0] for m in members], axis=0)
        agree = (
            ((stack[0] == stack[1]) | (stack[0] == stack[2]) | (stack[1] == stack[2]))
            & valid
        )
        pct = 100.0 * float(agree.sum()) / float(max(int(valid.sum()), 1))
        return out, pct

    def _cleanup_implausible_snow(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        out = class_map.copy()
        snow = (out == SNOW) & valid
        if not snow.any():
            return out
        strong = snow & (f["ndsi"] > t["snow_ndsi"]) & (f["swir1"] < 0.18) & (
            f["brightness"] > t["snow_bright"] * 0.85
        )
        if t.get("snowy_scene", 0) >= 0.5:
            weak = snow & ((f["swir1"] > 0.22) | (f["ndsi"] < t["snow_ndsi"] - 0.08))
            out[weak] = BARE_SOIL
            return out
        weak = snow & ~strong
        out[weak] = BARE_SOIL
        if strong.sum() < 0.003 * max(int(valid.sum()), 1):
            out[snow] = BARE_SOIL
        return out

    def _refine_water_bodies(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        out = class_map.copy()
        mndwi, ndwi, ndvi, awei = f["mndwi"], f["ndwi"], f["ndvi"], f["awei"]
        nir, swir1, bright = f["nir"], f["swir1"], f["brightness"]
        not_urban = ~self._hard_urban_mask(f, t)

        recover = (
            valid
            & (out != WATER)
            & (out != SNOW)
            & not_urban
            & (ndvi < 0.18)
            & (nir < t["wet_nir_max"])
            & (swir1 < t["wet_swir_max"])
            & (bright < t["wet_bright_max"])
            & (
                (mndwi > t["water_mndwi"] - 0.04)
                | (awei > t["water_awei"] - 0.04)
                | ((ndwi > -0.05) & (nir < t["water_nir_max"]))
            )
        )
        out[recover] = WATER

        water = ((out == WATER) & valid).astype(np.uint8) * 255
        if water.any():
            closed = (
                Image.fromarray(water, mode="L")
                .filter(ImageFilter.MaxFilter(3))
                .filter(ImageFilter.MinFilter(3))
            )
            closed_arr = np.array(closed, dtype=np.uint8) > 127
            add = (
                closed_arr
                & valid
                & (out != SNOW)
                & not_urban
                & (ndvi < 0.18)
                & (nir < t["wet_nir_max"])
                & (swir1 < t["wet_swir_max"])
            )
            out[add] = WATER
        return out

    def _expand_wet_channels(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
        iterations: int = 10,
    ) -> np.ndarray:
        out = class_map.copy()
        urban = self._hard_urban_mask(f, t)
        ndvi, mndwi, ndwi, awei = f["ndvi"], f["mndwi"], f["ndwi"], f["awei"]
        nir, swir1, bright, bsi = f["nir"], f["swir1"], f["brightness"], f["bsi"]

        seeds = (out == WATER) & valid & ~urban
        if not seeds.any():
            strong = (
                valid
                & ~urban
                & (ndvi < 0.14)
                & (nir < t["water_nir_max"])
                & (swir1 < t["water_swir_max"])
                & ((mndwi > t["water_mndwi"]) | (awei > t["water_awei"]))
            )
            seeds = strong
            out[seeds] = WATER
        if not seeds.any():
            return out

        wet_candidate = (
            valid
            & ~urban
            & (out != SNOW)
            & (ndvi < 0.20)
            & (nir < t["wet_nir_max"] + 0.04)
            & (swir1 < t["wet_swir_max"] + 0.06)
            & (bright < t["wet_bright_max"] + 0.05)
            & (
                (mndwi > t["wet_mndwi_min"])
                | (ndwi > -0.14)
                | (awei > t["water_awei"] - 0.16)
                | (
                    (ndvi < 0.12)
                    & (bsi > t["bare_bsi"] - 0.05)
                    & (mndwi > t["wet_mndwi_min"] - 0.06)
                    & (nir < 0.32)
                )
            )
        )
        wet_candidate &= ~((out == VEGETATION) & (ndvi > t["veg_ndvi"] + 0.05))
        # Do not overwrite clear roads during wet growth
        wet_candidate &= ~(
            (out == ROADS) & (f["grey"] > 0.55) & (mndwi < t["water_mndwi"] - 0.05)
        )

        mask = seeds.copy()
        for _ in range(max(1, int(iterations))):
            dil = (
                np.array(
                    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").filter(
                        ImageFilter.MaxFilter(3)
                    ),
                    dtype=np.uint8,
                )
                > 127
            )
            grown = dil & wet_candidate & valid & ~urban
            if not (grown & ~mask).any():
                break
            mask |= grown
        out[mask] = WATER
        return out

    def _recover_dark_water(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        """Force pitch-black / very dark IR pixels to water (never vegetation)."""
        out = class_map.copy()
        urban = self._hard_urban_mask(f, t)
        bright, nir, swir1 = f["brightness"], f["nir"], f["swir1"]
        red, green, blue = f["red"], f["green"], f["blue"]

        pitch_black = (
            valid
            & ~urban
            & (bright < 0.13)
            & (nir < 0.10)
            & (swir1 < 0.10)
            & ((red + green + blue) < 0.32)
        )
        # Slightly broader dark-water: still much darker than crops in NIR
        dark_water = (
            valid
            & ~urban
            & (nir < 0.12)
            & (swir1 < 0.12)
            & (bright < 0.16)
            & (nir < green * 0.95 + 0.02)
            & (
                (f["mndwi"] > t["wet_mndwi_min"] - 0.06)
                | (f["ndwi"] > -0.20)
                | (f["awei"] > t["water_awei"] - 0.15)
                | pitch_black
            )
        )
        force = pitch_black | dark_water
        # Reclaim anything currently labeled vegetation / bare / roads on dark water
        out[force & (out != SNOW)] = WATER
        return out

    def _enhance_linear_features(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        """Promote canal-like wet lines to water and elongated grey lines to roads."""
        out = class_map.copy()
        ndvi, mndwi, ndwi = f["ndvi"], f["mndwi"], f["ndwi"]
        nir, swir1, bright, grey = f["nir"], f["swir1"], f["brightness"], f["grey"]
        ndbi, awei = f["ndbi"], f["awei"]
        urban = self._hard_urban_mask(f, t)

        # Canal candidates: include pitch-black lines even if NDVI is noisy/high
        pitch_black = (bright < 0.13) & (nir < 0.10) & (swir1 < 0.10)
        canal_cand = (
            valid
            & ~urban
            & (out != SNOW)
            & (nir < t["wet_nir_max"] + 0.02)
            & (
                pitch_black
                | (
                    (ndvi < 0.25)
                    & (
                        (mndwi > t["wet_mndwi_min"] - 0.02)
                        | (ndwi > -0.12)
                        | (awei > t["water_awei"] - 0.12)
                        | ((bright < 0.22) & (nir < 0.16) & (swir1 < 0.16))
                    )
                )
            )
        )
        elong_canal = self._elongation(canal_cand | pitch_black)
        canal = canal_cand & ((elong_canal >= 3.0) | (out == WATER) | pitch_black)
        # Grow canals a bit along the line
        if canal.any():
            dil = (
                np.array(
                    Image.fromarray((canal.astype(np.uint8) * 255), mode="L").filter(
                        ImageFilter.MaxFilter(3)
                    ),
                    dtype=np.uint8,
                )
                > 127
            )
            canal |= dil & canal_cand & valid
            # Always reclaim false vegetation on dark/canal pixels
            out[canal & (out != SNOW)] = WATER
            out[pitch_black & valid & (out == VEGETATION)] = WATER

        # Road candidates: grey, low NDVI, not water-wet
        road_cand = (
            valid
            & (out != WATER)
            & (out != SNOW)
            & (ndvi < t["veg_ndvi"] - 0.08)
            & (ndvi < 0.22)
            & (mndwi < t["water_mndwi"] - 0.02)
            & (grey > 0.42)
            & (bright > 0.12)
            & (bright < 0.45)
            & (nir > t["water_nir_max"] * 0.65)
            & ((ndbi > t["road_ndbi"] - 0.04) | (f["bu"] > -0.04))
        )
        elong_road = self._elongation(road_cand)
        roads = road_cand & ((elong_road >= 3.0) | (out == ROADS))
        if roads.any():
            dil = (
                np.array(
                    Image.fromarray((roads.astype(np.uint8) * 255), mode="L").filter(
                        ImageFilter.MaxFilter(3)
                    ),
                    dtype=np.uint8,
                )
                > 127
            )
            roads |= dil & road_cand & valid & (out != WATER)
            # Prefer roads over bare/veg for linear grey features
            out[roads & (out != WATER) & (out != SNOW) & (out != BUILT_UP)] = ROADS
            # Also reclaim false vegetation on road lines
            out[roads & (out == VEGETATION)] = ROADS
        return out

    def _refine_impervious(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        out = class_map.copy()
        ndvi, ndbi, bright, grey = f["ndvi"], f["ndbi"], f["brightness"], f["grey"]

        # Bright high-NDBI cores mislabeled as vegetation → built-up
        urban_core = (
            valid
            & (out == VEGETATION)
            & (ndvi < t["veg_ndvi"] + 0.02)
            & (ndbi > t["urban_ndbi"])
            & (bright > 0.22)
        )
        out[urban_core] = BUILT_UP

        # Dense green labeled bare → vegetation
        green_fill = (
            valid
            & (out == BARE_SOIL)
            & (ndvi > t["veg_ndvi"] + 0.03)
            & (f["evi"] > t["veg_evi"])
            & (ndbi < t["urban_ndbi"] + 0.05)
            & (f["mndwi"] < t["water_mndwi"])
        )
        out[green_fill] = VEGETATION

        # Compact bright settlement blobs → built-up (not roads)
        built = (
            valid
            & (out == ROADS)
            & (bright > 0.26)
            & (ndbi > t["urban_ndbi"] - 0.02)
        )
        # Non-linear bright road patches are settlements
        if built.any():
            elong = self._elongation(out == ROADS)
            built |= (
                valid
                & (out == ROADS)
                & (bright > 0.24)
                & (elong < 2.5)
                & (ndvi < t["veg_ndvi"] - 0.06)
            )
        out[built] = BUILT_UP
        return out

    def _strip_false_vegetation(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        """Final pass: non-photosynthetic 'agriculture' → water/roads/soil/built-up."""
        out = class_map.copy()
        ndvi, mndwi, grey = f["ndvi"], f["mndwi"], f["grey"]
        ndbi, bright, nir = f["ndbi"], f["brightness"], f["nir"]
        swir1 = f["swir1"]

        # Any vegetation label on dark / low-NIR pixels is wrong (canals, shadows)
        dark_as_veg = valid & (out == VEGETATION) & (
            ((bright < 0.14) & (nir < 0.14))
            | ((nir < 0.16) & (swir1 < 0.14))
            | (nir < 0.12)
        )
        out[dark_as_veg] = WATER

        false_veg = valid & (out == VEGETATION) & (
            (ndvi < t["veg_ndvi"] - 0.02) | (nir < 0.20)
        )
        to_water = false_veg & (
            (mndwi > t["wet_mndwi_min"])
            | ((nir < t["water_nir_max"]) & (swir1 < t["water_swir_max"]))
            | ((bright < 0.18) & (nir < 0.15))
        )
        out[to_water] = WATER
        false_veg = false_veg & ~to_water

        to_roads = false_veg & (grey > 0.45) & (bright < 0.42) & (
            ndbi > t["road_ndbi"] - 0.05
        )
        out[to_roads] = ROADS
        false_veg = false_veg & ~to_roads

        to_built = false_veg & (ndbi > t["urban_ndbi"]) & (bright > 0.22)
        out[to_built] = BUILT_UP
        false_veg = false_veg & ~to_built

        out[false_veg] = BARE_SOIL
        return out

    def _majority_filter(
        self, class_map: np.ndarray, valid: np.ndarray, iterations: int = 1
    ) -> np.ndarray:
        out = class_map.copy()
        for _ in range(iterations):
            img = Image.fromarray(out, mode="L")
            filtered = img.filter(ImageFilter.ModeFilter(size=3))
            arr = np.array(filtered, dtype=np.uint8)
            arr[~valid] = NODATA
            arr[out == NODATA] = NODATA
            # Preserve thin linear water/roads from being majority-eaten
            preserve = (out == WATER) | (out == ROADS)
            arr[preserve & valid] = out[preserve & valid]
            out = arr
        return out

    def _smooth(self, arr: np.ndarray, radius: float = 2) -> np.ndarray:
        scaled = np.clip((arr + 1.0) * 0.5, 0, 1)
        u8 = Image.fromarray((scaled * 255).astype(np.uint8), mode="L")
        blurred = u8.filter(ImageFilter.GaussianBlur(radius=radius))
        return (np.array(blurred, dtype=np.float64) / 255.0) * 2.0 - 1.0

    # -------------------------------------------------------------- areas
    def _pixel_area_km2(self, bounds: list[float], shape: tuple[int, int]) -> float:
        west, south, east, north = bounds
        h, w = shape
        if h <= 0 or w <= 0:
            return 0.0
        mid_lat = (south + north) / 2.0
        m_per_deg_lat = 111_320.0
        m_per_deg_lon = 111_320.0 * max(0.01, math.cos(math.radians(mid_lat)))
        px_h_m = abs(north - south) / h * m_per_deg_lat
        px_w_m = abs(east - west) / w * m_per_deg_lon
        return (px_h_m * px_w_m) / 1_000_000.0

    def _area_stats(
        self, class_map: np.ndarray, valid: np.ndarray, bounds: list[float]
    ) -> tuple[list[ClassAreaStat], float]:
        px_km2 = self._pixel_area_km2(bounds, class_map.shape)
        valid_n = int(valid.sum())
        stats: list[ClassAreaStat] = []
        total_km2 = 0.0
        for cid, meta in CLASS_META.items():
            n = int(((class_map == cid) & valid).sum())
            area = n * px_km2
            total_km2 += area
            pct = (100.0 * n / valid_n) if valid_n else 0.0
            stats.append(
                ClassAreaStat(
                    class_id=cid,
                    name=meta["name"],
                    label=meta["label"],
                    color=meta["color"],
                    pixels=n,
                    percent=round(pct, 2),
                    area_km2=round(area, 4),
                )
            )
        return stats, round(total_km2, 4)

    # ------------------------------------------------------------- render
    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _class_map_to_png(self, class_map: np.ndarray, valid: np.ndarray) -> bytes:
        h, w = class_map.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        alpha = {
            SNOW: 235,
            BARE_SOIL: 200,
            BUILT_UP: 220,
            VEGETATION: 210,
            WATER: 245,
            ROADS: 230,
        }
        for cid, meta in CLASS_META.items():
            r, g, b = self._hex_to_rgb(meta["color"])
            mask = (class_map == cid) & valid
            rgba[mask, 0] = r
            rgba[mask, 1] = g
            rgba[mask, 2] = b
            rgba[mask, 3] = alpha[cid]
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _legend(self) -> LegendInfo:
        return LegendInfo(
            min=0,
            max=float(N_CLASSES - 1),
            unit="class",
            label="Land cover (6 classes)",
            formula="Snow / Bare Soil / Built-up / Vegetation / Water / Roads",
            colormap="lulc6",
            stops=[
                ColormapStop(value=float(cid), color=meta["color"])
                for cid, meta in CLASS_META.items()
            ],
        )
