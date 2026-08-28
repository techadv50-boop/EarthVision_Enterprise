"""Optical ship / open-sea object detection for Landsat / Sentinel-2.

User rule (open sea):
  Water NIR/VIS reflectance stays in a narrow range. Anything brighter
  than that water range — including ship hulls and wakes — is an object.

Workflow:
  1. Require Landsat / Sentinel-2 + drawn water-body AOI.
  2. Estimate water reflectance stats inside the AOI (NIR + VIS).
  3. Flag pixels above the water range (objects) and wake-like streaks.
  4. Vectorize → numbered contacts (points + footprints) + red outline overlay.
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

MIN_COMPONENT_PIXELS = 2
MAX_FEATURES = 300
MAX_OBJECT_PIXELS = 20_000
# Absolute ceiling — above this over open water is almost always cloud sheet
ABS_CLOUD_HI = 0.90


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


def _dilate(mask: np.ndarray, iters: int = 1) -> np.ndarray:
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


def _box_filter(arr: np.ndarray, size: int) -> np.ndarray:
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


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
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


def _peak_reflectance(
    red: np.ndarray | None,
    green: np.ndarray | None,
    blue: np.ndarray | None,
    nir: np.ndarray,
) -> np.ndarray:
    """Per-pixel peak of NIR+VIS — water is low; hulls/wakes are higher."""
    layers = [nir.astype(np.float64)]
    for band in (red, green, blue):
        if band is not None:
            layers.append(band.astype(np.float64))
    return np.nanmax(np.stack(layers, axis=0), axis=0)


def _water_seed(green: np.ndarray | None, nir: np.ndarray, search: np.ndarray) -> np.ndarray:
    """Conservative water seed used only to estimate the water reflectance range.

    Intentionally excludes bright hulls/wakes so they cannot raise the water ceiling.
    """
    nir_f = nir.astype(np.float64)
    if green is None:
        seed = search & np.isfinite(nir_f) & (nir_f < 0.05)
    else:
        ndwi = _ndwi(green.astype(np.float64), nir_f)
        seed = (
            search
            & np.isfinite(nir_f)
            & (np.nan_to_num(ndwi, nan=-1.0) > 0.08)
            & (nir_f < 0.08)
        )
    # Prefer the darker majority of the AOI if NDWI seed is tiny
    if int(seed.sum()) < 64:
        vals = nir_f[search & np.isfinite(nir_f)]
        if vals.size:
            thr = float(np.nanpercentile(vals, 50))
            seed = search & np.isfinite(nir_f) & (nir_f <= thr)
    return seed


def _large_cloud_sheets(
    scl: np.ndarray | None,
    water_seed: np.ndarray,
    peak: np.ndarray,
) -> np.ndarray:
    """Only huge bright sheets count as cloud — never compact ship/wake blobs."""
    cloud = np.zeros(peak.shape, dtype=bool)
    if scl is not None:
        scl_cloud = np.isin(scl.astype(np.int16), [8, 9, 10])
        labeled, nlab = _label_components(scl_cloud)
        for lab in range(1, nlab + 1):
            ys, xs = np.where(labeled == lab)
            n = int(ys.size)
            # Compact SCL "cloud" over water is usually a ship — keep it
            if n < 4000:
                continue
            cloud[ys, xs] = True
    # Extremely bright vast glare
    very_bright = peak >= ABS_CLOUD_HI
    labeled, nlab = _label_components(very_bright)
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        if int(ys.size) >= 5000:
            cloud[ys, xs] = True
    # Don't erase water seed itself
    cloud &= ~water_seed
    return cloud


def _wake_mask(
    peak: np.ndarray,
    nir: np.ndarray,
    object_core: np.ndarray,
    water_peak_hi: float,
    water_nir_hi: float,
    search: np.ndarray,
) -> np.ndarray:
    """Ship wake / foam: elongated brightening above the water range near a hull."""
    soft_hi_p = water_peak_hi + max(0.004, 0.15 * max(water_peak_hi, 0.02))
    soft_hi_n = water_nir_hi + max(0.004, 0.15 * max(water_nir_hi, 0.02))
    soft = search & ~object_core & (
        ((peak > soft_hi_p) | (nir > soft_hi_n)) & (peak < ABS_CLOUD_HI)
    )
    if not soft.any():
        return np.zeros_like(object_core)

    near_hull = _dilate(object_core, iters=12) if object_core.any() else soft
    # Prefer soft pixels attached to / near a brighter hull
    wake_near = soft & near_hull

    labeled, nlab = _label_components(soft)
    keep = np.zeros_like(soft)
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        n = int(ys.size)
        if n < 2 or n > MAX_OBJECT_PIXELS:
            continue
        hspan = int(ys.max() - ys.min()) + 1
        wspan = int(xs.max() - xs.min()) + 1
        aspect = max(hspan, wspan) / max(1, min(hspan, wspan))
        # Wakes are elongated streaks; also keep any soft patch touching a hull
        touches_hull = bool(near_hull[ys, xs].any()) if object_core.any() else True
        if touches_hull or aspect >= 2.0:
            keep[ys, xs] = True
    return wake_near | keep


def detect_ships_optical_nir(
    bands: dict[str, np.ndarray],
    bounds: list[float],
    *,
    confidence_min: float = 0.08,
    collection: str | None = None,
    aoi_polygon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect open-sea objects as reflectance above the water range (+ wakes)."""
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
    peak = _peak_reflectance(red, green, blue, nir_f)

    aoi_mask = _aoi_mask(nir_f.shape, bounds, aoi_polygon)
    search = finite.copy()
    if aoi_mask is not None:
        search &= aoi_mask

    if int(search.sum()) < 16:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "formula": "water-range anomaly · wake — empty AOI",
            "message": "Water AOI has no usable pixels for ship detection",
        }

    water_seed = _water_seed(green, nir_f, search)
    if int(water_seed.sum()) < 16:
        # Fallback: darkest 55% of AOI (by NIR) as water
        vals = nir_f[search]
        thr = float(np.nanpercentile(vals, 55))
        water_seed = search & (nir_f <= thr)

    water_nir = nir_f[water_seed]
    water_peak = peak[water_seed]
    # Tight water range: open-sea water sits in a narrow NIR/VIS band.
    # Use a mid-high percentile so bright hulls never inflate the water ceiling.
    water_nir_hi = float(np.nanpercentile(water_nir, 85))
    water_peak_hi = float(np.nanpercentile(water_peak, 85))
    water_nir_med = float(np.nanmedian(water_nir))
    water_peak_med = float(np.nanmedian(water_peak))
    # Small margin — anything clearly different from water is an object
    spread = max(water_nir_hi - water_nir_med, water_peak_hi - water_peak_med, 0.005)
    margin = max(0.005, 0.25 * spread)
    nir_thr = water_nir_hi + margin
    peak_thr = water_peak_hi + margin

    cloud = _large_cloud_sheets(scl, water_seed, peak)
    usable = search & ~cloud

    # PRIMARY RULE (user): NIR (and VIS peak) above the water reflectance range
    above_nir = usable & (nir_f >= nir_thr)
    above_peak = usable & (peak >= peak_thr)
    # Strong decks: well above water median even if water_hi was slightly high
    strong = usable & (
        (nir_f >= water_nir_med + 3.0 * margin) | (peak >= water_peak_med + 3.0 * margin)
    )
    object_core = above_nir | above_peak | strong

    # SECONDARY: wakes / foam trails (elongated soft brightening near hulls)
    wakes = _wake_mask(peak, nir_f, object_core, water_peak_hi, water_nir_hi, usable)

    ship_mask = object_core | wakes
    if aoi_mask is not None:
        ship_mask &= aoi_mask

    # Size filter — keep compact objects; drop vast dim haze sheets only
    labeled_pre, n_pre = _label_components(ship_mask)
    keep = np.zeros_like(ship_mask)
    for lab in range(1, n_pre + 1):
        ys, xs = np.where(labeled_pre == lab)
        n = int(ys.size)
        if n < MIN_COMPONENT_PIXELS or n > MAX_OBJECT_PIXELS:
            continue
        mean_p = float(np.nanmean(peak[ys, xs]))
        if n > 10_000 and mean_p < peak_thr + 0.04:
            continue
        keep[ys, xs] = True
    ship_mask = keep

    if int(ship_mask.sum()) > MAX_FEATURES * 120:
        thr = float(np.nanpercentile(peak[ship_mask], 35))
        ship_mask &= peak >= thr

    labeled, nlab = _label_components(ship_mask)
    west, south, east, north = (float(v) for v in bounds)
    h, w = nir_f.shape
    features: list[dict[str, Any]] = []
    contact_n = 0

    # Rank by how far above water (NIR excess preferred — user rule)
    comps: list[tuple[float, int, np.ndarray, np.ndarray]] = []
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        if ys.size < MIN_COMPONENT_PIXELS:
            continue
        score = float(
            max(np.nanmax(nir_f[ys, xs]) - water_nir_med, np.nanmax(peak[ys, xs]) - water_peak_med)
        )
        comps.append((score, lab, ys, xs))
    comps.sort(key=lambda t: -t[0])

    for score, _lab, ys, xs in comps:
        excess = max(0.0, score)
        conf01 = float(np.clip(0.20 + excess / max(0.06, 0.28), 0.1, 0.99))
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

        pad_r, pad_c = 0.75, 0.75
        ring = [
            rc_to_lonlat(r0 - pad_r, c0 - pad_c),
            rc_to_lonlat(r0 - pad_r, c1 + pad_c),
            rc_to_lonlat(r1 + pad_r, c1 + pad_c),
            rc_to_lonlat(r1 + pad_r, c0 - pad_c),
            rc_to_lonlat(r0 - pad_r, c0 - pad_c),
        ]
        mean_nir = float(np.nanmean(nir_f[ys, xs]))
        mean_p = float(np.nanmean(peak[ys, xs]))
        max_nir = float(np.nanmax(nir_f[ys, xs]))
        hspan = int(ys.max() - ys.min()) + 1
        wspan = int(xs.max() - xs.min()) + 1
        aspect = max(hspan, wspan) / max(1, min(hspan, wspan))
        cue = (
            "wake"
            if aspect >= 2.5 and max_nir < nir_thr + 0.05
            else "above_water_nir"
        )
        contact_n += 1
        props = {
            "class": "ship",
            "label": f"Ship {contact_n}",
            "contact_id": contact_n,
            "confidence": round(conf01, 3),
            "nir_mean": round(mean_nir, 4),
            "nir_max": round(max_nir, 4),
            "brightness": round(mean_p, 4),
            "water_nir_hi": round(water_nir_hi, 4),
            "nir_thr": round(nir_thr, 4),
            "pixels": int(ys.size),
            "cue": cue,
            "band": "NIR+VIS",
            "lon": round(lon, 6),
            "lat": round(lat, 6),
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

    overlay = _ship_overlay_rgba(ship_mask)
    n_ships = contact_n
    logger.info(
        "Ship detect water-range: water_nir_hi={:.4f} nir_thr={:.4f} contacts={}",
        water_nir_hi,
        nir_thr,
        n_ships,
    )
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": n_ships,
        "overlay": overlay,
        "formula": (
            f"open-sea water NIR/VIS range (NIR hi≈{water_nir_hi:.3f}) · "
            f"highlight NIR>{nir_thr:.3f} / peak>{peak_thr:.3f} + wakes · red outline"
        ),
        "message": (
            f"{n_ships} object(s) above water reflectance range "
            f"(+ wakes) inside water AOI"
        ),
    }


def _ship_overlay_rgba(ship_mask: np.ndarray) -> np.ndarray:
    """Light red fill on anomaly pixels + strong red outline (hull stays readable)."""
    h, w = ship_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if not ship_mask.any():
        return rgba
    # Soft fill so every above-water / wake pixel is visibly highlighted
    rgba[ship_mask, 0] = 255
    rgba[ship_mask, 1] = 40
    rgba[ship_mask, 2] = 40
    rgba[ship_mask, 3] = 70
    outline = _dilate(ship_mask, iters=1) & ~ship_mask
    if not outline.any():
        outline = _dilate(ship_mask, iters=2) & ~ship_mask
    rgba[outline, 0] = 255
    rgba[outline, 1] = 0
    rgba[outline, 2] = 0
    rgba[outline, 3] = 245
    return rgba
