"""Optical NIR ship detection for Landsat / Sentinel-2 only.

Workflow (AI Tools → Ship Detection):
  1. Require an optical Landsat or Sentinel-2 scene (off until selected).
  2. Load NIR (primary) plus green/blue/red/SCL for masks.
  3. Mask out water (McFeeters NDWI) and clouds (SCL / bright-blue ratio).
  4. Score remaining pixels for ship-like NIR signatures:
     metal decks (bright NIR peaks) and chimney/exhaust plumes (local NIR anomalies).
  5. Vectorize connected components → polygons + centroid points (GeoJSON / shapefile).
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from loguru import logger

from app.core.exceptions import ValidationError

OPTICAL_SHIP_TASKS = frozenset(
    {
        "ship_detection",
        "ship_detection_optical",
    }
)

NIR_METAL_LO = 0.12
NIR_METAL_HI = 0.75
CFAR_K = 2.2
MIN_COMPONENT_PIXELS = 3
MAX_FEATURES = 200


def collection_is_optical_landsat_or_s2(collection: str | None) -> bool:
    c = (collection or "").upper().replace("_", "-")
    if not c:
        return False
    if "SENTINEL-1" in c or c.startswith("S1"):
        return False
    if "SENTINEL-3" in c or c.startswith("S3"):
        return False
    if "SENTINEL-5" in c or "S5P" in c:
        return False
    if "SMOS" in c or "MODIS" in c:
        return False
    if "SENTINEL-2" in c or c.startswith("S2") or "L2A" in c:
        return True
    if "LANDSAT" in c or c.startswith("L8") or c.startswith("L9") or c.startswith("L7"):
        return True
    return False


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
        out[~np.isfinite(out)] = np.nan
    return out


def _ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    return np.clip(_safe_div(green - nir, green + nir), -1.0, 1.0)


def _cloud_mask(
    blue: np.ndarray | None,
    nir: np.ndarray,
    scl: np.ndarray | None,
) -> np.ndarray:
    cloud = np.zeros(nir.shape, dtype=bool)
    if scl is not None:
        cloud |= np.isin(scl.astype(np.int16), [8, 9, 10, 3])
    if blue is not None:
        bright = (blue > 0.22) & (nir > 0.22) & (blue > nir * 0.85)
        cloud |= bright
    cloud |= nir > 0.55
    return cloud


def _water_mask(green: np.ndarray | None, nir: np.ndarray) -> np.ndarray:
    if green is None:
        return nir < 0.04
    ndwi = _ndwi(green, nir)
    return np.nan_to_num(ndwi, nan=-1.0) > 0.15


def _box_filter(arr: np.ndarray, size: int) -> np.ndarray:
    """Separable box mean via cumulative sums (odd size)."""
    k = max(3, int(size) | 1)
    r = k // 2
    a = np.pad(arr.astype(np.float64), ((r, r), (r, r)), mode="edge")
    # Integral image
    c = np.pad(a, ((1, 0), (1, 0)), mode="constant")
    c = np.cumsum(np.cumsum(c, axis=0), axis=1)
    h, w = arr.shape
    out = (
        c[k : k + h, k : k + w]
        - c[0:h, k : k + w]
        - c[k : k + h, 0:w]
        + c[0:h, 0:w]
    )
    return out / float(k * k)


def _local_cfar(nir: np.ndarray, valid: np.ndarray, radius: int = 5) -> np.ndarray:
    """(x − μ) / σ over a local window; NaN outside valid."""
    x = np.nan_to_num(nir, nan=0.0).astype(np.float64)
    w = valid.astype(np.float64)
    size = max(3, int(radius) * 2 + 1)
    sum_x = _box_filter(x * w, size)
    sum_w = _box_filter(w, size)
    sum_x2 = _box_filter((x * x) * w, size)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu = np.where(sum_w > 1e-3, sum_x / np.maximum(sum_w, 1e-6), 0.0)
        var = np.where(
            sum_w > 1e-3,
            np.maximum(sum_x2 / np.maximum(sum_w, 1e-6) - mu * mu, 0.0),
            0.0,
        )
    sigma = np.sqrt(np.maximum(var, 1e-8))
    score = (x - mu) / sigma
    return np.where(valid, score, np.nan)


def _dilate(mask: np.ndarray, iters: int = 1) -> np.ndarray:
    """Binary dilation with a 3×3 structuring element."""
    out = mask.astype(bool)
    for _ in range(max(1, iters)):
        p = np.pad(out, 1, mode="constant", constant_values=False)
        out = (
            p[0:-2, 0:-2]
            | p[0:-2, 1:-1]
            | p[0:-2, 2:]
            | p[1:-1, 0:-2]
            | p[1:-1, 1:-1]
            | p[1:-1, 2:]
            | p[2:, 0:-2]
            | p[2:, 1:-1]
            | p[2:, 2:]
        )
    return out


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labeling (pure NumPy / BFS)."""
    h, w = mask.shape
    labeled = np.zeros((h, w), dtype=np.int32)
    lab = 0
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or labeled[y, x]:
                continue
            lab += 1
            q: deque[tuple[int, int]] = deque([(y, x)])
            labeled[y, x] = lab
            while q:
                cy, cx = q.popleft()
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labeled[ny, nx]:
                        labeled[ny, nx] = lab
                        q.append((ny, nx))
    return labeled, lab


def detect_ships_optical_nir(
    bands: dict[str, np.ndarray],
    bounds: list[float],
    *,
    confidence_min: float = 0.45,
    collection: str | None = None,
) -> dict[str, Any]:
    """Run NIR optical ship detection → GeoJSON + RGBA overlay."""
    if collection is not None and not collection_is_optical_landsat_or_s2(collection):
        raise ValidationError(
            "Ship Detection (optical) works only with Landsat or Sentinel-2 imagery. "
            "Select an optical scene first."
        )

    nir = bands.get("nir")
    if nir is None:
        raise ValidationError(
            "NIR band is required for Ship Detection — turn the eye on a "
            "Sentinel-2 or Landsat scene and retry."
        )

    green = bands.get("green")
    blue = bands.get("blue")
    red = bands.get("red")
    scl = bands.get("scl")

    nir_f = nir.astype(np.float64)
    finite = np.isfinite(nir_f)
    water = _water_mask(green, nir_f)
    cloud = _cloud_mask(blue, nir_f, scl)

    # Background for CFAR includes water (dark contrast) but never clouds.
    # Ship labels themselves must NOT be water/cloud pixels.
    bg = finite & ~cloud
    if int(bg.sum()) < 16:
        logger.info("Ship detect: too few non-cloud NIR pixels")
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "formula": (
                "NIR ship cue · water(NDWI)+cloud(SCL) ignored · "
                "metal/smoke CFAR — no candidates"
            ),
            "message": "No ship-like NIR targets after water/cloud masking",
        }

    cfar = _local_cfar(nir_f, bg, radius=5)

    # Metal / deck-like NIR reflectance (not water-classed)
    metal = (
        finite
        & ~water
        & ~cloud
        & (nir_f >= NIR_METAL_LO)
        & (nir_f <= NIR_METAL_HI)
    )
    # Suppress dense vegetation inland; keep near-water metal even if NDVI-ish
    near_water = _dilate(water, iters=2)
    if red is not None:
        ndvi = _safe_div(nir_f - red.astype(np.float64), nir_f + red.astype(np.float64))
        metal &= near_water | (np.nan_to_num(ndvi, nan=0.0) < 0.55)

    # Chimney / exhaust: strong local NIR anomaly, not cloud/water
    smoke_like = finite & ~water & ~cloud & (cfar >= CFAR_K) & (nir_f >= 0.08)

    # Prefer targets near water (ships) — dilate water mask
    ship_mask = ((metal & (cfar >= (CFAR_K * 0.55))) | smoke_like) & (
        near_water | (cfar >= CFAR_K)
    )

    if int(ship_mask.sum()) > MAX_FEATURES * 40:
        thr = float(np.nanpercentile(cfar[ship_mask], 70))
        ship_mask &= cfar >= thr

    if int(ship_mask.sum()) == 0:
        # Fallback: brightest non-water/non-cloud NIR peaks (metal window)
        cand = metal & np.isfinite(cfar)
        if int(cand.sum()) > 0:
            thr = float(np.nanpercentile(cfar[cand], 95))
            ship_mask = cand & (cfar >= max(thr, 1.0))

    labeled, nlab = _label_components(ship_mask)
    west, south, east, north = (float(v) for v in bounds)
    h, w = nir_f.shape
    features: list[dict[str, Any]] = []

    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        if ys.size < MIN_COMPONENT_PIXELS:
            continue
        conf = float(np.nanmean(cfar[ys, xs]))
        # Map CFAR → confidence (CFAR≈1.8 → ~0.45 with default threshold)
        conf01 = float(np.clip((conf - 0.5) / 3.0, 0.05, 0.99))
        if conf01 < confidence_min:
            continue
        row_c = float(ys.mean())
        col_c = float(xs.mean())
        lon = west + (col_c + 0.5) / w * (east - west)
        lat = north - (row_c + 0.5) / h * (north - south)

        r0, r1 = int(ys.min()), int(ys.max())
        c0, c1 = int(xs.min()), int(xs.max())

        def rc_to_lonlat(rr: float, cc: float) -> list[float]:
            return [
                west + (cc + 0.5) / w * (east - west),
                north - (rr + 0.5) / h * (north - south),
            ]

        ring = [
            rc_to_lonlat(r0 - 0.5, c0 - 0.5),
            rc_to_lonlat(r0 - 0.5, c1 + 0.5),
            rc_to_lonlat(r1 + 0.5, c1 + 0.5),
            rc_to_lonlat(r1 + 0.5, c0 - 0.5),
            rc_to_lonlat(r0 - 0.5, c0 - 0.5),
        ]
        mean_nir = float(np.nanmean(nir_f[ys, xs]))
        props = {
            "class": "ship",
            "label": "Ship",
            "confidence": round(conf01, 3),
            "nir_mean": round(mean_nir, 4),
            "cfar": round(conf, 3),
            "pixels": int(ys.size),
            "cue": "metal_nir" if mean_nir >= NIR_METAL_LO else "smoke_nir",
            "band": "NIR",
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {**props, "geom_role": "centroid"},
            }
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {**props, "geom_role": "footprint"},
            }
        )
        if len(features) >= MAX_FEATURES * 2:
            break

    overlay = _ship_overlay_rgba(nir_f, ship_mask, water, cloud)
    n_ships = sum(1 for f in features if f["properties"].get("geom_role") == "centroid")
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": n_ships,
        "overlay": overlay,
        "formula": (
            "NIR optical ship detect · ignore water(NDWI)+cloud(SCL) · "
            "metal/smoke CFAR peaks → point+polygon"
        ),
        "message": (
            f"{n_ships} ship candidate(s) from NIR "
            f"(water/cloud ignored · metal & chimney-smoke cues)"
        ),
    }


def _ship_overlay_rgba(
    nir: np.ndarray,
    ship_mask: np.ndarray,
    water: np.ndarray,
    cloud: np.ndarray,
) -> np.ndarray:
    h, w = nir.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    ctx = np.clip(nir, 0, 0.4) / 0.4
    show = np.isfinite(nir) & ~water & ~cloud
    gray = (ctx * 140).astype(np.uint8)
    rgba[show, 0] = gray[show]
    rgba[show, 1] = gray[show]
    rgba[show, 2] = (gray[show] * 0.85).astype(np.uint8)
    rgba[show, 3] = 90
    rgba[ship_mask, 0] = 255
    rgba[ship_mask, 1] = 170
    rgba[ship_mask, 2] = 40
    rgba[ship_mask, 3] = 220
    return rgba
