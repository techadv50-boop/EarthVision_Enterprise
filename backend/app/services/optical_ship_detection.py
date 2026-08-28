"""Optical ship detection for Landsat / Sentinel-2 only.

Workflow (AI Tools → Ship Detection):
  1. Require an optical Landsat or Sentinel-2 scene (off until selected).
  2. Load NIR + RGB (+ SCL) reflectance.
  3. Classify open water (NDWI). Clouds use SCL only — never treat bright
     decks / wakes over water as cloud (that was wiping real ships).
  4. Open-sea cue (user guidance): any non-water object in open sea has a
     distinct reflectance range vs surrounding water — detect bright /
     CFAR anomalies against a water background in VIS+NIR.
  5. Harbor cue: metal-deck NIR peaks adjacent to water.
  6. Vectorize → point centroids + polygon footprints (GeoJSON / shapefile).
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

# Open-sea / deck reflectance window (BOA ρ) — above dark water, below ice/cloud glare
OBJ_REFLECT_LO = 0.05
OBJ_REFLECT_HI = 0.85
NIR_METAL_LO = 0.08
NIR_METAL_HI = 0.80
CFAR_K = 1.6
MIN_COMPONENT_PIXELS = 2
MAX_FEATURES = 250
MAX_OBJECT_PIXELS = 12_000


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
    water: np.ndarray,
) -> np.ndarray:
    """Cloud mask that does NOT wipe bright ships.

    Sentinel-2 SCL frequently labels bright decks / wakes as class 8/9
    (cloud). Over open water, only large SCL cloud patches are trusted;
    compact bright blobs stay as ship candidates.
    """
    cloud = np.zeros(nir.shape, dtype=bool)
    if scl is not None:
        scl_cloud = np.isin(scl.astype(np.int16), [8, 9, 10, 3])
        labeled, nlab = _label_components(scl_cloud)
        keep = np.zeros_like(scl_cloud)
        water_d = _dilate(water, iters=2)
        for lab in range(1, nlab + 1):
            ys, xs = np.where(labeled == lab)
            n = int(ys.size)
            water_frac = float(water_d[ys, xs].mean()) if n else 0.0
            # Real cloud sheets over sea are large; ships are compact.
            if water_frac >= 0.4 and n < 2500:
                continue
            keep[ys, xs] = True
        cloud |= keep
    inland = ~_dilate(water, iters=3)
    if blue is not None:
        bright = (blue > 0.28) & (nir > 0.28) & (blue > nir * 0.9)
        cloud |= bright & inland
    cloud |= (nir > 0.65) & inland
    return cloud


def _water_mask(green: np.ndarray | None, nir: np.ndarray) -> np.ndarray:
    if green is None:
        return nir < 0.045
    ndwi = _ndwi(green, nir)
    # Slightly softer so ship decks (lower NDWI) fall out of water class
    return np.nan_to_num(ndwi, nan=-1.0) > 0.12


def _box_filter(arr: np.ndarray, size: int) -> np.ndarray:
    """Separable box mean via cumulative sums (odd size)."""
    k = max(3, int(size) | 1)
    r = k // 2
    a = np.pad(arr.astype(np.float64), ((r, r), (r, r)), mode="edge")
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


def _local_cfar(x_in: np.ndarray, valid: np.ndarray, radius: int = 7) -> np.ndarray:
    """(x − μ) / σ over a local window; NaN outside valid."""
    x = np.nan_to_num(x_in, nan=0.0).astype(np.float64)
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
    return np.where(valid | np.isfinite(x_in), score, np.nan)


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


def _aoi_mask(
    shape: tuple[int, int],
    bounds: list[float],
    aoi_polygon: dict[str, Any] | None,
) -> np.ndarray | None:
    """Boolean mask True inside a GeoJSON Polygon AOI (row/col grid over bounds)."""
    if not aoi_polygon or aoi_polygon.get("type") != "Polygon":
        return None
    coords = aoi_polygon.get("coordinates") or []
    if not coords or not coords[0]:
        return None
    try:
        from shapely.geometry import shape as shp_shape

        poly = shp_shape(aoi_polygon)
        if poly.is_empty:
            return None
    except Exception:  # noqa: BLE001
        return None

    west, south, east, north = (float(v) for v in bounds)
    h, w = shape
    if east <= west or north <= south or h < 1 or w < 1:
        return None
    xs = west + (np.arange(w, dtype=np.float64) + 0.5) / w * (east - west)
    ys = north - (np.arange(h, dtype=np.float64) + 0.5) / h * (north - south)
    lon, lat = np.meshgrid(xs, ys)
    try:
        from shapely import contains_xy

        mask = contains_xy(poly, lon, lat)
    except Exception:  # noqa: BLE001
        from shapely import vectorized

        mask = vectorized.contains(poly, lon, lat)
    mask = np.asarray(mask, dtype=bool)
    if 0 < int(mask.sum()) < 16:
        mask = _dilate(mask, iters=2)
    return mask


def _vis_brightness(
    red: np.ndarray | None,
    green: np.ndarray | None,
    blue: np.ndarray | None,
    nir: np.ndarray,
) -> np.ndarray:
    """VIS+NIR brightness used as open-sea object reflectance cue."""
    layers = [nir.astype(np.float64)]
    for band in (red, green, blue):
        if band is not None:
            layers.append(band.astype(np.float64))
    stacked = np.stack(layers, axis=0)
    return np.nanmean(stacked, axis=0)


def detect_ships_optical_nir(
    bands: dict[str, np.ndarray],
    bounds: list[float],
    *,
    confidence_min: float = 0.22,
    collection: str | None = None,
    aoi_polygon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run optical ship detection → GeoJSON + RGBA overlay.

    When ``aoi_polygon`` is provided (user-drawn water body), candidates
    outside that polygon are discarded and the search mask is clipped to it.
    """
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
    cloud = _cloud_mask(blue, nir_f, scl, water)
    aoi_mask = _aoi_mask(nir_f.shape, bounds, aoi_polygon)
    if aoi_mask is not None:
        finite = finite & aoi_mask
        # Treat outside-AOI as non-searchable (not water/cloud for CFAR bg either)
        water = water & aoi_mask
        cloud = cloud | ~aoi_mask

    bright = _vis_brightness(red, green, blue, nir_f)
    # CFAR background = water (open-sea contrast) + non-cloud
    water_bg = finite & water & ~cloud
    if int(water_bg.sum()) < 16:
        # Fall back to any non-cloud finite pixels
        water_bg = finite & ~cloud
    if int(water_bg.sum()) < 16:
        logger.info("Ship detect: too few background pixels")
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "formula": (
                "open-sea reflectance vs water · SCL cloud · "
                "VIS+NIR CFAR — no candidates"
            ),
            "message": "No usable water/NIR background for ship detection",
        }

    cfar_bright = _local_cfar(bright, water_bg, radius=9)
    cfar_nir = _local_cfar(nir_f, water_bg, radius=7)
    cfar = np.nanmax(np.stack([cfar_bright, cfar_nir], axis=0), axis=0)

    water_frac = _box_filter(water.astype(np.float64), size=15)
    near_water = _dilate(water, iters=6)
    sea_dom = water_frac >= 0.35  # open sea / harbor basins

    # --- Open-sea objects: reflectance above water, CFAR peak, sea context ---
    # Includes bright decks that NDWI still tags as water — use CFAR on brightness.
    open_sea = (
        finite
        & ~cloud
        & sea_dom
        & (bright >= OBJ_REFLECT_LO)
        & (bright <= OBJ_REFLECT_HI)
        & (cfar >= CFAR_K)
    )
    # Decks that fall out of water class but sit in the sea
    non_water_obj = (
        finite
        & ~water
        & ~cloud
        & near_water
        & (bright >= OBJ_REFLECT_LO)
        & (bright <= OBJ_REFLECT_HI)
        & (cfar >= (CFAR_K * 0.55))
    )
    if red is not None:
        ndvi = _safe_div(nir_f - red.astype(np.float64), nir_f + red.astype(np.float64))
        non_water_obj &= np.nan_to_num(ndvi, nan=0.0) < 0.55

    # Harbor / metal NIR cue (kept for piers)
    metal = (
        finite
        & ~water
        & ~cloud
        & near_water
        & (nir_f >= NIR_METAL_LO)
        & (nir_f <= NIR_METAL_HI)
        & (cfar_nir >= (CFAR_K * 0.5))
    )

    ship_mask = open_sea | non_water_obj | metal
    if aoi_mask is not None:
        ship_mask &= aoi_mask

    if int(ship_mask.sum()) > MAX_FEATURES * 80:
        thr = float(np.nanpercentile(cfar[ship_mask], 65))
        ship_mask &= cfar >= thr

    if int(ship_mask.sum()) == 0:
        # Soft fallback: top brightness CFAR peaks in open water
        cand = finite & ~cloud & sea_dom & np.isfinite(cfar) & (bright >= 0.04)
        if int(cand.sum()) > 0:
            thr = float(np.nanpercentile(cfar[cand], 97))
            ship_mask = cand & (cfar >= max(thr, 1.2))

    # Size filter — drop speckles and huge cloud/land blobs
    labeled_pre, n_pre = _label_components(ship_mask)
    keep = np.zeros_like(ship_mask)
    for lab in range(1, n_pre + 1):
        ys, xs = np.where(labeled_pre == lab)
        n = int(ys.size)
        if n < MIN_COMPONENT_PIXELS or n > MAX_OBJECT_PIXELS:
            continue
        # Ships are compact; reject very elongated thin cloud streaks unless bright
        hspan = int(ys.max() - ys.min()) + 1
        wspan = int(xs.max() - xs.min()) + 1
        aspect = max(hspan, wspan) / max(1, min(hspan, wspan))
        mean_b = float(np.nanmean(bright[ys, xs]))
        if aspect > 14 and mean_b < 0.25:
            continue
        keep[ys, xs] = True
    ship_mask = keep

    labeled, nlab = _label_components(ship_mask)
    west, south, east, north = (float(v) for v in bounds)
    h, w = nir_f.shape
    features: list[dict[str, Any]] = []

    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        if ys.size < MIN_COMPONENT_PIXELS:
            continue
        conf = float(np.nanmean(cfar[ys, xs]))
        conf01 = float(np.clip((conf - 0.3) / 3.2, 0.1, 0.99))
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

        # Tight footprint so red box frames the object without covering it
        pad_r = 0.75
        pad_c = 0.75
        ring = [
            rc_to_lonlat(r0 - pad_r, c0 - pad_c),
            rc_to_lonlat(r0 - pad_r, c1 + pad_c),
            rc_to_lonlat(r1 + pad_r, c1 + pad_c),
            rc_to_lonlat(r1 + pad_r, c0 - pad_c),
            rc_to_lonlat(r0 - pad_r, c0 - pad_c),
        ]
        mean_nir = float(np.nanmean(nir_f[ys, xs]))
        mean_b = float(np.nanmean(bright[ys, xs]))
        cue = "open_sea_reflectance" if float(np.nanmean(water_frac[ys, xs])) >= 0.5 else "metal_nir"
        props = {
            "class": "ship",
            "label": "Ship",
            "confidence": round(conf01, 3),
            "nir_mean": round(mean_nir, 4),
            "brightness": round(mean_b, 4),
            "cfar": round(conf, 3),
            "pixels": int(ys.size),
            "cue": cue,
            "band": "VIS+NIR",
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

    overlay = _ship_overlay_rgba(bright, ship_mask, water, cloud)
    n_ships = sum(1 for f in features if f["properties"].get("geom_role") == "centroid")
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": n_ships,
        "overlay": overlay,
        "formula": (
            "water-body AOI · open-sea object reflectance vs water (VIS+NIR CFAR) · "
            "SCL cloud · red on-image demarcation"
        ),
        "message": (
            f"{n_ships} ship candidate(s) inside water AOI "
            f"(marked in red on the image)"
        ),
    }


def _ship_overlay_rgba(
    bright: np.ndarray,
    ship_mask: np.ndarray,
    water: np.ndarray,
    cloud: np.ndarray,
) -> np.ndarray:
    """Transparent overlay: thin red outline only so the ship stays visible."""
    del water, cloud, bright  # imagery underneath stays visible
    h, w = ship_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if not ship_mask.any():
        return rgba
    # Very light red wash on ship pixels (object still readable)
    rgba[ship_mask, 0] = 255
    rgba[ship_mask, 1] = 40
    rgba[ship_mask, 2] = 40
    rgba[ship_mask, 3] = 70
    # Crisp red ring around the object
    outline = _dilate(ship_mask, iters=1) & ~ship_mask
    rgba[outline, 0] = 255
    rgba[outline, 1] = 0
    rgba[outline, 2] = 0
    rgba[outline, 3] = 230
    return rgba
