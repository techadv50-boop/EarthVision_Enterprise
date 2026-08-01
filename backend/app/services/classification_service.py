"""Ensemble unsupervised land-cover classification (4 classes).

Produces a categorical map with:
  snow (white), soil/built-up (light orange), vegetation (light green), water (blue)

Amalgam of:
  1) Spectral index rules (NDVI / NDWI / NDSI / NDBI)
  2) K-means on multi-band + index feature space
  3) OBIA-like object refinement (smooth + majority / region consensus)
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

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
    SOIL: {"name": "soil", "label": "Soil (Built-up)", "color": "#FFB366"},  # light orange
    VEGETATION: {"name": "vegetation", "label": "Vegetation", "color": "#A8E6A1"},  # light green
    WATER: {"name": "water", "label": "Water", "color": "#3B82F6"},  # blue
}


class ClassificationService:
    def classify(self, request: ClassificationRequest) -> ClassificationResponse:
        bands, bounds = self._load_bands(request.scene_id, request.bbox, request.size)
        features, valid = self._build_features(bands)
        if valid.sum() < 64:
            raise ValidationError(
                "Not enough valid pixels to classify — show a Sentinel-2 or Landsat scene first"
            )

        rule_map = self._classify_spectral_rules(features, valid)
        kmeans_map = self._classify_kmeans(features, valid)
        obia_map = self._classify_obia_like(features, valid, seed_map=kmeans_map)

        amalgam, agreement = self._amalgam_vote(
            [rule_map, kmeans_map, obia_map], valid
        )
        amalgam = self._majority_filter(amalgam, valid, iterations=2)

        stats, total_km2 = self._area_stats(amalgam, valid, bounds)
        overlay = self._class_map_to_png(amalgam, valid)
        legend = self._legend()

        return ClassificationResponse(
            scene_id=request.scene_id,
            algorithm="amalgam(spectral_rules + kmeans + OBIA-like)",
            classes=stats,
            total_area_km2=total_km2,
            valid_pixels=int(valid.sum()),
            bounds=[float(x) for x in bounds],
            overlay_base64=base64.b64encode(overlay).decode("ascii"),
            legend=legend,
            formula=(
                "Ensemble unsupervised LULC: spectral rules (NDVI/NDWI/NDSI/NDBI) ⊕ "
                "K-means feature clustering ⊕ OBIA-like object majority → amalgam vote"
            ),
            message=(
                f"Classified into 4 classes · agreement {agreement:.0f}% · "
                f"total {total_km2:.2f} km²"
            ),
            agreement_percent=round(float(agreement), 1),
            metadata={
                "members": ["spectral_rules", "kmeans", "obia_like"],
                "colors": {m["name"]: m["color"] for m in CLASS_META.values()},
            },
        )

    def results_csv(self, result: ClassificationResponse) -> str:
        rows = [
            "class_id,name,label,color,pixels,percent,area_km2",
        ]
        for c in result.classes:
            rows.append(
                f"{c.class_id},{c.name},{c.label},{c.color},{c.pixels},"
                f"{c.percent:.4f},{c.area_km2:.6f}"
            )
        rows.append(f",,,TOTAL,,,{result.total_area_km2:.6f}")
        rows.append(f"algorithm,,,{result.algorithm},,,")
        rows.append(f"agreement_percent,,,{result.agreement_percent},,,")
        rows.append(f"valid_pixels,,,{result.valid_pixels},,,")
        rows.append(
            f"bounds,,,{' '.join(str(x) for x in result.bounds)},,,"
        )
        return "\n".join(rows) + "\n"

    # ------------------------------------------------------------------ load
    def _load_bands(
        self, scene_id: str, bbox: list[float] | None, size: int
    ) -> tuple[dict[str, np.ndarray], list[float]]:
        from app.services.scene_imagery_service import SceneImageryService

        imagery = SceneImageryService()
        bands, bounds, _fp, _layer = imagery.load_analysis_bands(
            scene_id, size=size, bounds=bbox
        )
        if not bands:
            raise ValidationError("No optical bands available for classification")
        return bands, [float(x) for x in bounds]

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
        swir = self._pick(bands, "swir", "swir16", "swir2", "swir22")

        ref = next(v for v in (red, green, blue, nir) if v is not None)
        h, w = ref.shape
        if blue is None:
            blue = np.zeros((h, w), dtype=np.float64)
        if green is None:
            green = np.zeros((h, w), dtype=np.float64)
        if red is None:
            red = np.zeros((h, w), dtype=np.float64)
        if nir is None:
            nir = green.copy()
        if swir is None:
            swir = red.copy()

        def _norm(a: np.ndarray) -> np.ndarray:
            out = a.astype(np.float64)
            finite = np.isfinite(out)
            if finite.any() and float(np.nanmax(out[finite])) > 1.5:
                out = out / 10000.0
            return np.clip(out, 0, 1)

        blue, green, red, nir, swir = map(_norm, (blue, green, red, nir, swir))
        valid = (
            np.isfinite(blue)
            & np.isfinite(green)
            & np.isfinite(red)
            & np.isfinite(nir)
            & np.isfinite(swir)
            & ((red + green + blue + nir) > 0.01)
        )

        eps = 1e-6
        ndvi = (nir - red) / (nir + red + eps)
        ndwi = (green - nir) / (green + nir + eps)
        ndsi = (green - swir) / (green + swir + eps)
        ndbi = (swir - nir) / (swir + nir + eps)
        brightness = (blue + green + red) / 3.0

        return {
            "blue": blue,
            "green": green,
            "red": red,
            "nir": nir,
            "swir": swir,
            "ndvi": ndvi,
            "ndwi": ndwi,
            "ndsi": ndsi,
            "ndbi": ndbi,
            "brightness": brightness,
        }, valid

    # --------------------------------------------------------- classifiers
    def _classify_spectral_rules(
        self, f: dict[str, np.ndarray], valid: np.ndarray
    ) -> np.ndarray:
        """Hard spectral decision tree tuned for S2/Landsat reflectance."""
        h, w = valid.shape
        out = np.full((h, w), NODATA, dtype=np.uint8)
        ndvi, ndwi, ndsi, ndbi = f["ndvi"], f["ndwi"], f["ndsi"], f["ndbi"]
        bright = f["brightness"]

        # Priority: water → snow → vegetation → soil/built-up
        # Water: high NDWI, low NDVI, avoid bright cloud tops
        water = valid & (ndwi > 0.12) & (ndvi < 0.12) & (bright < 0.40)
        snow = valid & ~water & (ndsi > 0.40) & (bright > 0.30) & (ndvi < 0.15)
        veg = valid & ~water & ~snow & (ndvi > 0.22)
        soil = valid & ~water & ~snow & ~veg

        # Bright urban roofs / bare soil: high NDBI or moderate brightness, low NDVI
        soil |= valid & ~water & ~snow & (ndbi > 0.0) & (ndvi < 0.22)

        out[soil] = SOIL
        out[veg] = VEGETATION
        out[snow] = SNOW
        out[water] = WATER
        return out

    def _classify_kmeans(
        self, f: dict[str, np.ndarray], valid: np.ndarray
    ) -> np.ndarray:
        from sklearn.cluster import MiniBatchKMeans

        h, w = valid.shape
        out = np.full((h, w), NODATA, dtype=np.uint8)
        keys = ["blue", "green", "red", "nir", "swir", "ndvi", "ndwi", "ndsi", "ndbi"]
        stack = np.stack([f[k] for k in keys], axis=-1)
        samples = stack[valid]
        if samples.shape[0] < 64:
            return out

        # Subsample for speed on large grids
        rng = np.random.default_rng(42)
        n = samples.shape[0]
        idx = rng.choice(n, size=min(n, 40000), replace=False)
        train = samples[idx]

        km = MiniBatchKMeans(
            n_clusters=4,
            random_state=42,
            batch_size=4096,
            n_init=3,
            max_iter=80,
        )
        km.fit(train)
        labels = km.predict(samples)

        # Map each cluster → land-cover class using cluster mean indices
        centers = km.cluster_centers_
        # feature order: blue,green,red,nir,swir,ndvi,ndwi,ndsi,ndbi
        mapping: dict[int, int] = {}
        for cid in range(4):
            ndvi_c = float(centers[cid, 5])
            ndwi_c = float(centers[cid, 6])
            ndsi_c = float(centers[cid, 7])
            ndbi_c = float(centers[cid, 8])
            bright_c = float(np.mean(centers[cid, 0:3]))
            scores = {
                WATER: ndwi_c * 2.0 - ndvi_c,
                SNOW: ndsi_c * 2.0 + bright_c - max(ndvi_c, 0),
                VEGETATION: ndvi_c * 2.5 - max(ndwi_c, 0),
                SOIL: ndbi_c * 1.5 - ndvi_c + 0.2,
            }
            mapping[cid] = max(scores, key=scores.get)

        # Ensure all 4 classes are represented when possible
        used = set(mapping.values())
        missing = [c for c in (WATER, SNOW, VEGETATION, SOIL) if c not in used]
        if missing:
            # Remap lowest-confidence cluster ids
            for miss in missing:
                for cid, cls in list(mapping.items()):
                    if list(mapping.values()).count(cls) > 1:
                        mapping[cid] = miss
                        break

        mapped = np.array([mapping[int(x)] for x in labels], dtype=np.uint8)
        out[valid] = mapped
        return out

    def _classify_obia_like(
        self,
        f: dict[str, np.ndarray],
        valid: np.ndarray,
        seed_map: np.ndarray,
    ) -> np.ndarray:
        """Object-based refinement: smooth features, segment, majority label per object."""
        h, w = valid.shape
        # Smooth NDVI / NDWI / brightness as a cheap segmentation cue
        ndvi_s = self._smooth(f["ndvi"], radius=2)
        ndwi_s = self._smooth(f["ndwi"], radius=2)
        bright_s = self._smooth(f["brightness"], radius=2)

        # Quantize into coarse objects (superpixel-like bins)
        ndvi_q = np.digitize(ndvi_s, bins=[-0.2, 0.1, 0.3, 0.5, 0.7])
        ndwi_q = np.digitize(ndwi_s, bins=[-0.2, 0.0, 0.15, 0.35])
        bright_q = np.digitize(bright_s, bins=[0.1, 0.2, 0.35, 0.5])
        object_id = (ndvi_q * 100 + ndwi_q * 10 + bright_q).astype(np.int32)
        object_id[~valid] = -1

        out = seed_map.copy()
        for oid in np.unique(object_id):
            if oid < 0:
                continue
            mask = object_id == oid
            vals = seed_map[mask]
            vals = vals[vals != NODATA]
            if vals.size == 0:
                continue
            # Majority class inside the object
            counts = np.bincount(vals, minlength=4)
            majority = int(np.argmax(counts))
            out[mask] = majority

            # Spectral override for confident water/snow objects
            if float(np.nanmean(ndwi_s[mask])) > 0.2:
                out[mask] = WATER
            elif float(np.nanmean(f["ndsi"][mask])) > 0.4 and float(
                np.nanmean(bright_s[mask])
            ) > 0.28:
                out[mask] = SNOW
            elif float(np.nanmean(ndvi_s[mask])) > 0.35:
                out[mask] = VEGETATION

        out[~valid] = NODATA
        return out

    def _amalgam_vote(
        self, maps: list[np.ndarray], valid: np.ndarray
    ) -> tuple[np.ndarray, float]:
        """Pixel-wise majority vote across classifier members (vectorized)."""
        h, w = valid.shape
        stack = np.stack(maps, axis=0)  # (M,H,W)
        out = np.full((h, w), NODATA, dtype=np.uint8)
        counts = np.zeros((4, h, w), dtype=np.int16)
        for m in range(stack.shape[0]):
            layer = stack[m]
            for cid in range(4):
                counts[cid] += (layer == cid) & valid
        winner = np.argmax(counts, axis=0).astype(np.uint8)
        has_vote = counts.max(axis=0) > 0
        out[has_vote] = winner[has_vote]
        out[~valid] = NODATA
        total = int(valid.sum())
        agree = int(((counts.max(axis=0) >= 2) & valid).sum())
        pct = (100.0 * agree / total) if total else 0.0
        return out, pct

    def _majority_filter(
        self, class_map: np.ndarray, valid: np.ndarray, iterations: int = 1
    ) -> np.ndarray:
        out = class_map.copy()
        for _ in range(iterations):
            img = Image.fromarray(out, mode="L")
            # Mode filter approximates 3×3 majority for categorical data
            filtered = img.filter(ImageFilter.ModeFilter(size=3))
            arr = np.array(filtered, dtype=np.uint8)
            arr[~valid] = NODATA
            # Don't let ModeFilter invent classes from nodata borders
            arr[out == NODATA] = NODATA
            out = arr
        return out

    def _smooth(self, arr: np.ndarray, radius: int = 2) -> np.ndarray:
        img = Image.fromarray(arr.astype(np.float32), mode="F")
        # Box blur via repeated min filter isn't ideal; use GaussianBlur on 8-bit scale
        scaled = np.clip((arr + 1.0) * 0.5, 0, 1)
        u8 = Image.fromarray((scaled * 255).astype(np.uint8), mode="L")
        blurred = u8.filter(ImageFilter.GaussianBlur(radius=radius))
        back = (np.array(blurred, dtype=np.float64) / 255.0) * 2.0 - 1.0
        return back

    # -------------------------------------------------------------- areas
    def _pixel_area_km2(self, bounds: list[float], shape: tuple[int, int]) -> float:
        west, south, east, north = bounds
        h, w = shape
        if h <= 0 or w <= 0:
            return 0.0
        mid_lat = (south + north) / 2.0
        # Approximate geodesic pixel size
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
        for cid, meta in CLASS_META.items():
            r, g, b = self._hex_to_rgb(meta["color"])
            mask = (class_map == cid) & valid
            rgba[mask, 0] = r
            rgba[mask, 1] = g
            rgba[mask, 2] = b
            rgba[mask, 3] = 220 if cid != SNOW else 200
        # Snow: keep white but slightly opaque so basemap doesn't wash it out
        snow_mask = (class_map == SNOW) & valid
        rgba[snow_mask, 3] = 230
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
