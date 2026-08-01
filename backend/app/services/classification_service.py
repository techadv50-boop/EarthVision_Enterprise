"""Ensemble unsupervised land-cover classification (4 classes).

Produces a categorical map:
  snow (white), soil/built-up (light orange), vegetation (light green), water (blue)

Amalgam of:
  1) Adaptive spectral decision rules (NDVI / MNDWI / NDSI / NDBI + cloud mask)
  2) Over-clustered K-means / ISODATA-style mapping onto the 4 target classes
  3) OBIA-like object majority with spectral overrides
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
SOIL = 1
VEGETATION = 2
WATER = 3
NODATA = 255

CLASS_META: dict[int, dict[str, str]] = {
    SNOW: {"name": "snow", "label": "Snow", "color": "#FFFFFF"},
    SOIL: {"name": "soil", "label": "Soil (Built-up)", "color": "#FFB366"},
    VEGETATION: {"name": "vegetation", "label": "Vegetation", "color": "#A8E6A1"},
    WATER: {"name": "water", "label": "Water", "color": "#3B82F6"},
}


class ClassificationService:
    def classify(self, request: ClassificationRequest) -> ClassificationResponse:
        size = max(int(request.size), 1024)
        bands, bounds, footprint = self._load_bands(
            request.scene_id, request.bbox, size
        )
        features, valid = self._build_features(bands)
        # Clip to the STAC scene footprint so the map matches the eye-loaded image
        # (tilted Landsat / S2 swaths leave transparent corners in the bbox).
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
                (rule_map, rule_conf, 1.45),
                (kmeans_map, kmeans_conf, 1.0),
                (obia_map, np.clip(kmeans_conf * 0.9 + 0.1, 0, 1), 0.90),
            ],
            valid,
            cloud,
            features,
            thresholds,
        )
        amalgam = self._cleanup_implausible_snow(amalgam, features, valid, thresholds)
        amalgam = self._refine_water_bodies(amalgam, features, valid, thresholds)
        amalgam = self._refine_urban_soil(amalgam, features, valid, thresholds)
        amalgam = self._majority_filter(amalgam, valid, iterations=2)

        stats, total_km2 = self._area_stats(amalgam, valid, bounds)
        overlay = self._class_map_to_png(amalgam, valid)

        return ClassificationResponse(
            scene_id=request.scene_id,
            algorithm="amalgam(adaptive_rules + ISODATA-kmeans + OBIA-like)",
            classes=stats,
            total_area_km2=total_km2,
            valid_pixels=int(valid.sum()),
            bounds=[float(x) for x in bounds],
            overlay_base64=base64.b64encode(overlay).decode("ascii"),
            legend=self._legend(),
            formula=(
                "Ensemble unsupervised LULC: adaptive NDVI/EVI/MNDWI/NDSI/NDBI rules ⊕ "
                "over-clustered K-means mapped to 4 classes ⊕ OBIA-like object majority "
                "(cloud + footprint masked) → confidence-weighted amalgam"
            ),
            message=(
                f"Classified into 4 classes · agreement {agreement:.0f}% · "
                f"total {total_km2:.2f} km²"
            ),
            agreement_percent=round(float(agreement), 1),
            metadata={
                "members": ["adaptive_spectral_rules", "isodata_kmeans", "obia_like"],
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
        """Keep only pixels inside the STAC footprint (tilted scene support)."""
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

        # Coarse grid then nearest upsample (same approach as scene tiles)
        step = 4 if min(h, w) >= 128 else 2
        ys = np.linspace(north, south, h, endpoint=False) + (south - north) / (2 * h)
        xs = np.linspace(west, east, w, endpoint=False) + (east - west) / (2 * w)
        mask_small = np.zeros(((h + step - 1) // step, (w + step - 1) // step), dtype=bool)
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
        # Enhanced vegetation index — more stable for sparse crops / arid fields
        evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0 + eps)
        evi = np.clip(evi, -1.0, 1.0)
        savi = 1.5 * (nir - red) / (nir + red + 0.5 + eps)
        # McFeeters NDWI and Xu MNDWI (better water in urban scenes)
        ndwi = (green - nir) / (green + nir + eps)
        mndwi = (green - swir1) / (green + swir1 + eps)
        ndsi = (green - swir1) / (green + swir1 + eps)
        ndbi = (swir1 - nir) / (swir1 + nir + eps)
        # Built-up index emphasizing SWIR2 contrast
        bu = ndbi - ndvi
        # Bare soil index — separates fallow / bare fields from sparse vegetation
        bsi = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue) + eps)
        brightness = (blue + green + red) / 3.0
        # Simple shadow cue
        shadow = (brightness < 0.08) & (nir < 0.12)

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
            "brightness": brightness,
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
        """Scene-adaptive cutoffs so one tile's cropland/urban mix doesn't break rules."""
        ndvi = f["ndvi"]
        evi = f["evi"]
        mndwi = f["mndwi"]
        ndsi = f["ndsi"]
        ndbi = f["ndbi"]
        bsi = f["bsi"]
        bright = f["brightness"]

        ndvi_p50 = self._pct(ndvi, valid, 50, 0.22)
        ndvi_p60 = self._pct(ndvi, valid, 60, 0.28)
        ndvi_p35 = self._pct(ndvi, valid, 35, 0.15)
        evi_p55 = self._pct(evi, valid, 55, 0.18)
        mndwi_p85 = self._pct(mndwi, valid, 85, 0.02)
        mndwi_p90 = self._pct(mndwi, valid, 90, 0.05)
        ndsi_p70 = self._pct(ndsi, valid, 70, 0.10)
        ndsi_p85 = self._pct(ndsi, valid, 85, 0.25)
        ndsi_p95 = self._pct(ndsi, valid, 95, 0.35)
        ndbi_p65 = self._pct(ndbi, valid, 65, -0.02)
        bsi_p60 = self._pct(bsi, valid, 60, 0.05)
        bright_p85 = self._pct(bright, valid, 85, 0.35)

        # Agricultural / arid scenes: median NDVI is modest — lower veg cut so
        # cropland is not collapsed into soil/built-up.
        arid_ag = ndvi_p50 < 0.28 and ndsi_p85 < 0.25

        # If the scene itself looks snowy (high NDSI body), use a softer snow cut.
        # Lowland scenes keep a strict cut so clouds are not labeled snow.
        snowy_scene = ndsi_p70 > 0.18 or ndsi_p85 > 0.30
        if snowy_scene:
            snow_ndsi = float(np.clip(max(0.22, min(0.45, ndsi_p70 * 0.90)), 0.20, 0.48))
            snow_bright = float(np.clip(max(0.18, bright_p85 * 0.55), 0.16, 0.40))
        else:
            snow_ndsi = float(np.clip(max(0.40, min(0.70, ndsi_p95 * 0.92)), 0.38, 0.75))
            snow_bright = float(np.clip(max(0.28, bright_p85 * 0.85), 0.25, 0.55))

        if arid_ag:
            veg_ndvi = float(np.clip(max(0.14, min(0.28, ndvi_p60 * 0.78)), 0.12, 0.30))
            soil_ndvi_max = float(np.clip(max(0.08, min(0.20, ndvi_p35)), 0.06, 0.22))
            water_mndwi = float(
                np.clip(max(0.04, min(0.18, mndwi_p85 * 0.65)), 0.03, 0.22)
            )
        else:
            veg_ndvi = float(np.clip(max(0.18, min(0.38, ndvi_p60 * 0.88)), 0.16, 0.40))
            soil_ndvi_max = float(np.clip(max(0.10, min(0.26, ndvi_p35)), 0.08, 0.28))
            water_mndwi = float(
                np.clip(max(0.06, min(0.24, mndwi_p90 * 0.55)), 0.05, 0.28)
            )

        return {
            "veg_ndvi": veg_ndvi,
            "veg_evi": float(np.clip(max(0.10, min(0.35, evi_p55 * 0.90)), 0.08, 0.38)),
            "soil_ndvi_max": soil_ndvi_max,
            "water_mndwi": water_mndwi,
            "snow_ndsi": snow_ndsi,
            "snow_bright": snow_bright,
            "snowy_scene": 1.0 if snowy_scene else 0.0,
            "arid_ag": 1.0 if arid_ag else 0.0,
            "urban_ndbi": float(np.clip(ndbi_p65 - 0.01, -0.08, 0.18)),
            "bare_bsi": float(np.clip(bsi_p60, -0.05, 0.35)),
            "cloud_bright": float(np.clip(bright_p85 + 0.05, 0.32, 0.60)),
        }

    def _cloud_mask(
        self, f: dict[str, np.ndarray], valid: np.ndarray
    ) -> np.ndarray:
        """Conservative bright-cloud mask (not used as a land-cover class)."""
        bright = f["brightness"]
        blue = f["blue"]
        nir = f["nir"]
        swir1 = f["swir1"]
        ndvi = f["ndvi"]
        ndsi = f["ndsi"]
        # Bright, blue-rich, low vegetation, SWIR not as dark as deep water
        cloud = (
            valid
            & (bright > 0.34)
            & (blue > 0.28)
            & (ndvi < 0.18)
            & (swir1 > 0.08)
            & (nir > 0.20)
            # Exclude clear snow (high NDSI + very low SWIR)
            & ~((ndsi > 0.45) & (swir1 < 0.12))
        )
        return cloud

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
        mndwi, ndwi = f["mndwi"], f["ndwi"]
        ndsi, ndbi, bu, bsi = f["ndsi"], f["ndbi"], f["bu"], f["bsi"]
        bright, nir, swir1 = f["brightness"], f["nir"], f["swir1"]
        shadow = f["shadow"] > 0.5
        land = valid & ~cloud

        # Water: MNDWI primary, NDWI support, dark NIR, not bright cloud.
        # Extra dark-water / canal branch catches narrow rivers with modest MNDWI.
        water = (
            land
            & (mndwi > t["water_mndwi"])
            & (ndvi < 0.18)
            & (nir < 0.20)
            & (bright < 0.38)
            & (swir1 < 0.22)
        )
        water |= (
            land
            & (mndwi > max(0.0, t["water_mndwi"] - 0.05))
            & (ndwi > -0.08)
            & (ndvi < 0.14)
            & (nir < 0.15)
            & (bright < 0.30)
            & (swir1 < 0.15)
        )
        water |= (
            land
            & (mndwi > t["water_mndwi"] + 0.04)
            & (ndwi > -0.02)
            & (ndvi < 0.20)
            & (nir < 0.22)
        )
        # Very dark open water / canals even when MNDWI is muted
        water |= (
            land
            & (nir < 0.08)
            & (swir1 < 0.08)
            & (bright < 0.18)
            & (ndvi < 0.10)
            & (mndwi > -0.05)
        )

        # Snow: high NDSI, bright visible, dark SWIR, low NDVI — and not cloud
        snow = (
            land
            & ~water
            & (ndsi > t["snow_ndsi"])
            & (bright > t["snow_bright"])
            & (swir1 < 0.16)
            & (ndvi < 0.15)
            & (f["blue"] > 0.22)
        )

        # Vegetation: NDVI primary, with EVI/SAVI support for sparse crops
        veg = (
            land
            & ~water
            & ~snow
            & (mndwi < t["water_mndwi"] + 0.06)
            & (
                (ndvi > t["veg_ndvi"])
                | ((evi > t["veg_evi"]) & (ndvi > t["soil_ndvi_max"] + 0.02))
                | ((savi > t["veg_ndvi"] * 0.85) & (ndvi > t["soil_ndvi_max"]))
            )
        )
        # Do not call bare soil "vegetation" just because NDVI is noisy
        veg &= ~((bsi > t["bare_bsi"] + 0.08) & (ndvi < t["veg_ndvi"] + 0.05))

        # Soil / built-up: low-moderate NDVI, elevated NDBI/BU/BSI, or bare bright land
        soil = land & ~water & ~snow & ~veg & (
            (ndvi < t["soil_ndvi_max"])
            | ((ndbi > t["urban_ndbi"]) & (ndvi < t["veg_ndvi"]))
            | ((bu > 0.0) & (ndvi < t["veg_ndvi"]))
            | ((bsi > t["bare_bsi"]) & (ndvi < t["veg_ndvi"]))
        )
        # Remaining land defaults to soil/built-up (not vegetation)
        leftover = land & ~water & ~snow & ~veg & ~soil
        soil |= leftover

        # Shadows over land → soil (not water), unless MNDWI is decisive
        shadow_land = land & shadow & ~water
        soil |= shadow_land
        veg &= ~shadow_land

        # Clouds: map to soil/built-up visually (impervious/bright) rather than snow/water
        out[soil] = SOIL
        out[veg] = VEGETATION
        out[snow] = SNOW
        out[water] = WATER
        out[cloud & valid] = SOIL

        # Confidence from how strongly indices exceed thresholds
        conf[water] = np.clip((mndwi[water] - t["water_mndwi"]) / 0.25 + 0.45, 0.35, 1)
        conf[snow] = np.clip((ndsi[snow] - t["snow_ndsi"]) / 0.25 + 0.40, 0.30, 1)
        conf[veg] = np.clip(
            np.maximum(ndvi[veg] - t["veg_ndvi"], evi[veg] - t["veg_evi"]) / 0.35 + 0.40,
            0.30,
            1,
        )
        conf[soil] = np.clip(
            0.35
            + np.maximum(0, -ndvi[soil]) * 0.5
            + np.maximum(0, ndbi[soil]) * 0.8
            + np.maximum(0, bsi[soil]) * 0.4,
            0.25,
            0.85,
        )
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

        # Train on non-cloud land/water pixels
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
            "ndsi",
            "ndbi",
            "bu",
            "bsi",
            "brightness",
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

        # Over-cluster (ISODATA-style) then map many clusters → 4 semantic classes
        n_clusters = int(np.clip(round(math.sqrt(max(n, 256)) / 2.6), 10, 18))
        km = MiniBatchKMeans(
            n_clusters=n_clusters,
            random_state=42,
            batch_size=8192,
            n_init=5,
            max_iter=140,
        )
        km.fit(train_z)

        all_samples = stack[valid]
        labels = km.predict(scaler.transform(all_samples))
        centers = scaler.inverse_transform(km.cluster_centers_)

        # Feature indices in keys
        i_ndvi, i_evi, i_mndwi = 5, 6, 7
        i_ndsi, i_ndbi, i_bu, i_bsi, i_bright = 8, 9, 10, 11, 12
        i_nir, i_swir = 3, 4

        mapping: dict[int, int] = {}
        strength: dict[int, float] = {}
        for cid in range(n_clusters):
            ndvi_c = float(centers[cid, i_ndvi])
            evi_c = float(centers[cid, i_evi])
            mndwi_c = float(centers[cid, i_mndwi])
            ndsi_c = float(centers[cid, i_ndsi])
            ndbi_c = float(centers[cid, i_ndbi])
            bu_c = float(centers[cid, i_bu])
            bsi_c = float(centers[cid, i_bsi])
            bright_c = float(centers[cid, i_bright])
            nir_c = float(centers[cid, i_nir])
            swir_c = float(centers[cid, i_swir])

            scores = {
                WATER: (
                    2.8 * mndwi_c
                    - 1.2 * ndvi_c
                    - 0.8 * nir_c
                    - 0.5 * swir_c
                    + (0.4 if bright_c < 0.25 else -0.3)
                ),
                SNOW: (
                    2.6 * ndsi_c
                    + 1.1 * bright_c
                    - 1.4 * swir_c
                    - 1.0 * max(ndvi_c, 0)
                    - (0.8 if bright_c < 0.25 else 0)
                ),
                VEGETATION: (
                    2.4 * ndvi_c
                    + 1.2 * evi_c
                    - 1.0 * max(mndwi_c, 0)
                    - 0.5 * max(ndbi_c, 0)
                    - 0.4 * max(bsi_c, 0)
                ),
                SOIL: (
                    1.5 * ndbi_c
                    + 1.1 * bu_c
                    + 1.0 * bsi_c
                    - 1.8 * ndvi_c
                    - 0.6 * max(mndwi_c, 0)
                    + 0.3
                ),
            }
            # Suppress snow unless NDSI is truly high (prevents cloud→snow)
            if ndsi_c < t["snow_ndsi"] - 0.05 or swir_c > 0.18:
                scores[SNOW] -= 2.5
            # Suppress water unless MNDWI supports it
            if mndwi_c < t["water_mndwi"] - 0.05 or nir_c > 0.25:
                scores[WATER] -= 1.8

            best = max(scores, key=scores.get)
            mapping[cid] = best
            ordered = sorted(scores.values(), reverse=True)
            strength[cid] = float(
                np.clip((ordered[0] - ordered[1]) / (abs(ordered[0]) + 0.5) + 0.35, 0.2, 1.0)
            )

        mapped = np.array([mapping[int(x)] for x in labels], dtype=np.uint8)
        conf_vals = np.array([strength[int(x)] for x in labels], dtype=np.float64)
        out[valid] = mapped
        conf[valid] = conf_vals

        # Cloud pixels → soil/built-up
        out[cloud & valid] = SOIL
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
        """Object-based refinement with spectral object overrides."""
        ndvi_s = self._smooth(f["ndvi"], radius=1.5)
        mndwi_s = self._smooth(f["mndwi"], radius=1.5)
        ndsi_s = self._smooth(f["ndsi"], radius=1.5)
        bright_s = self._smooth(f["brightness"], radius=1.5)
        ndbi_s = self._smooth(f["ndbi"], radius=1.5)

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
                out[mask] = SOIL
                continue
            vals = seed_map[mask]
            vals = vals[vals != NODATA]
            if vals.size == 0:
                continue
            majority = int(np.argmax(np.bincount(vals, minlength=4)))
            out[mask] = majority

            mean_mndwi = float(np.nanmean(mndwi_s[mask]))
            mean_ndvi = float(np.nanmean(ndvi_s[mask]))
            mean_ndsi = float(np.nanmean(ndsi_s[mask]))
            mean_bright = float(np.nanmean(bright_s[mask]))
            mean_ndbi = float(np.nanmean(ndbi_s[mask]))
            mean_nir = float(np.nanmean(f["nir"][mask]))

            if (
                mean_mndwi > t["water_mndwi"] + 0.03
                and mean_ndvi < 0.18
                and mean_nir < 0.20
                and mean_bright < 0.38
            ):
                out[mask] = WATER
            elif (
                mean_ndsi > t["snow_ndsi"]
                and mean_bright > t["snow_bright"]
                and mean_ndvi < 0.15
                and float(np.nanmean(f["swir1"][mask])) < 0.14
            ):
                out[mask] = SNOW
            elif mean_ndvi > t["veg_ndvi"] + 0.03 and mean_mndwi < t["water_mndwi"]:
                out[mask] = VEGETATION
            elif mean_ndvi < t["soil_ndvi_max"] or (
                mean_ndbi > t["urban_ndbi"] and mean_ndvi < t["veg_ndvi"]
            ):
                out[mask] = SOIL

        out[~valid] = NODATA
        out[cloud & valid] = SOIL
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
        scores = np.zeros((4, h, w), dtype=np.float64)
        for class_map, conf, weight in members:
            for cid in range(4):
                hit = (class_map == cid) & valid
                scores[cid][hit] += weight * conf[hit]

        # Spectral prior boost (helps break ties toward physically plausible class)
        scores[WATER] += 0.60 * np.clip(
            (f["mndwi"] - t["water_mndwi"]) / 0.2, 0, 1
        ) * valid
        scores[VEGETATION] += 0.50 * np.clip(
            np.maximum(
                (f["ndvi"] - t["veg_ndvi"]) / 0.3,
                (f["evi"] - t["veg_evi"]) / 0.3,
            ),
            0,
            1,
        ) * valid
        scores[SOIL] += 0.40 * np.clip(
            np.maximum(
                (t["veg_ndvi"] - f["ndvi"]) / 0.3,
                (f["bsi"] - t["bare_bsi"]) / 0.25,
            ),
            0,
            1,
        ) * valid
        scores[SNOW] += 0.50 * np.clip(
            (f["ndsi"] - t["snow_ndsi"]) / 0.2, 0, 1
        ) * valid
        # Strong penalty: clouds are not snow/water
        scores[SNOW][cloud] = -1
        scores[WATER][cloud] = -1

        winner = np.argmax(scores, axis=0).astype(np.uint8)
        out = np.full((h, w), NODATA, dtype=np.uint8)
        out[valid] = winner[valid]
        out[cloud & valid] = SOIL

        # Agreement = top two members match on class
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
        """Drop weak snow false-positives in lowland scenes; keep snow in snowy scenes."""
        out = class_map.copy()
        snow = (out == SNOW) & valid
        if not snow.any():
            return out
        strong = snow & (f["ndsi"] > t["snow_ndsi"]) & (f["swir1"] < 0.18) & (
            f["brightness"] > t["snow_bright"] * 0.85
        )
        if t.get("snowy_scene", 0) >= 0.5:
            # Alpine / snowy tiles: keep moderate NDSI snow, only drop obvious clouds
            weak = snow & ((f["swir1"] > 0.22) | (f["ndsi"] < t["snow_ndsi"] - 0.08))
            out[weak] = SOIL
            return out

        weak = snow & ~strong
        out[weak] = SOIL
        # If overall strong snow < 0.3% of scene, drop all snow (lowland false positives)
        if strong.sum() < 0.003 * max(int(valid.sum()), 1):
            out[snow] = SOIL
        return out

    def _refine_water_bodies(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        """Recover thin canals / dark water missed by the amalgam; drop noisy speckles."""
        out = class_map.copy()
        mndwi, ndwi, ndvi = f["mndwi"], f["ndwi"], f["ndvi"]
        nir, swir1, bright = f["nir"], f["swir1"], f["brightness"]

        recover = (
            valid
            & (out != WATER)
            & (out != SNOW)
            & (mndwi > t["water_mndwi"] - 0.02)
            & (ndvi < 0.16)
            & (nir < 0.16)
            & (swir1 < 0.16)
            & (bright < 0.32)
            & ((ndwi > -0.05) | (nir < 0.10))
        )
        out[recover] = WATER

        # Soft morphological close on water to reconnect thin rivers/canals
        water = ((out == WATER) & valid).astype(np.uint8) * 255
        if water.any():
            img = Image.fromarray(water, mode="L")
            closed = img.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
            closed_arr = np.array(closed, dtype=np.uint8) > 127
            add = closed_arr & valid & (out != SNOW) & (ndvi < 0.18) & (nir < 0.20)
            out[add] = WATER

            # Drop isolated 1-pixel water speckles that look like noise
            opened = (
                Image.fromarray(((out == WATER) & valid).astype(np.uint8) * 255, mode="L")
                .filter(ImageFilter.MinFilter(3))
                .filter(ImageFilter.MaxFilter(3))
            )
            keep = np.array(opened, dtype=np.uint8) > 127
            speckles = (out == WATER) & valid & ~keep
            # Only reassign speckles that are not spectrally strong water
            weak = speckles & (mndwi < t["water_mndwi"] + 0.08)
            out[weak] = np.where(
                f["ndvi"][weak] > t["veg_ndvi"], VEGETATION, SOIL
            ).astype(np.uint8)
        return out

    def _refine_urban_soil(
        self,
        class_map: np.ndarray,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        t: dict[str, float],
    ) -> np.ndarray:
        """Pull bright built-up / bare cores toward soil; protect dense vegetation."""
        out = class_map.copy()
        ndvi, ndbi, bsi = f["ndvi"], f["ndbi"], f["bsi"]
        bright, bu = f["brightness"], f["bu"]

        # Bright, high-NDBI cores mislabeled as vegetation → soil/built-up
        urban_core = (
            valid
            & (out == VEGETATION)
            & (ndvi < t["veg_ndvi"] + 0.06)
            & (
                ((ndbi > t["urban_ndbi"] + 0.02) & (bright > 0.22))
                | ((bsi > t["bare_bsi"] + 0.06) & (bu > 0.0))
            )
        )
        out[urban_core] = SOIL

        # Dense green that was labeled soil → vegetation
        green_fill = (
            valid
            & (out == SOIL)
            & (ndvi > t["veg_ndvi"] + 0.04)
            & (f["evi"] > t["veg_evi"])
            & (ndbi < t["urban_ndbi"] + 0.05)
            & (f["mndwi"] < t["water_mndwi"])
        )
        out[green_fill] = VEGETATION
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
        alpha = {SNOW: 235, SOIL: 215, VEGETATION: 215, WATER: 225}
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
            max=3,
            unit="class",
            label="Land cover (4 classes)",
            formula="Snow / Soil(Built-up) / Vegetation / Water",
            colormap="lulc4",
            stops=[
                ColormapStop(value=float(cid), color=meta["color"])
                for cid, meta in CLASS_META.items()
            ],
        )
