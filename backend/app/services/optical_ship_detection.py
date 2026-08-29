"""Optical ship / open-sea object detection for Landsat / Sentinel-2.

Ported from GEE "Ship Detection — NIR VERSION (OPTIMIZED)" with higher recall:

  1. Clip / mask to water AOI *before* threshold & morphology.
  2. Sensitive NIR threshold (~0.04–0.07 from AOI water floor; was 0.10).
  3. Soft wake band near hard cores / elongated streaks.
  4. Morph outline (dilate−erode) on the detection mask.
  5. Connected-pixel contacts for Locate; no shapefile on run.
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

# Open-sea sensitive defaults (0.10 missed faint hulls/wakes in Persian Gulf AOIs)
DEFAULT_NIR_THRESHOLD = 0.055
# Adaptive clamp — never as high as the old 0.10 miss-rate, never noise-floor
NIR_THR_MIN = 0.040
NIR_THR_MAX = 0.070
MIN_COMPONENT_PIXELS = 1
MAX_AREA_M2 = 40_000
MAX_FEATURES = 500
ABS_CLOUD_HI = 0.85
OUTLINE_RADIUS_PX = 2


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


def _nominal_scale_m(collection: str | None) -> float:
    c = (collection or "").upper()
    if "LANDSAT" in c or c.startswith("L8") or c.startswith("L9") or c.startswith("L7"):
        return 30.0
    return 10.0


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


def _erode(mask: np.ndarray, iters: int = 1) -> np.ndarray:
    out = mask.astype(bool)
    for _ in range(max(1, iters)):
        p = np.pad(out, 1, mode="constant", constant_values=False)
        out = (
            p[0:-2, 0:-2]
            & p[0:-2, 1:-1]
            & p[0:-2, 2:]
            & p[1:-1, 0:-2]
            & p[1:-1, 1:-1]
            & p[1:-1, 2:]
            & p[2:, 0:-2]
            & p[2:, 1:-1]
            & p[2:, 2:]
        )
    return out


def _morph_outline(ship_mask: np.ndarray, radius: int = OUTLINE_RADIUS_PX) -> np.ndarray:
    """GEE: dilated − eroded → thick raster ring (radius 2 px)."""
    if not ship_mask.any():
        return np.zeros_like(ship_mask, dtype=bool)
    r = max(1, int(radius))
    dilated = _dilate(ship_mask, iters=r)
    eroded = _erode(ship_mask, iters=r)
    outline = dilated & ~eroded
    if not outline.any():
        outline = dilated & ~ship_mask
        if not outline.any():
            outline = dilated
    return outline


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected components (GEE eightConnected: true)."""
    h, w = mask.shape
    labeled = np.zeros((h, w), dtype=np.int32)
    lab = 0
    neighbors = (
        (0, 1),
        (0, -1),
        (1, 0),
        (-1, 0),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    )
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or labeled[y, x]:
                continue
            lab += 1
            q: deque[tuple[int, int]] = deque([(y, x)])
            labeled[y, x] = lab
            while q:
                cy, cx = q.popleft()
                for dy, dx in neighbors:
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


def _crop_to_mask(
    nir: np.ndarray,
    mask: np.ndarray,
    bounds: list[float],
    pad: int = 4,
) -> tuple[np.ndarray, np.ndarray, list[float], tuple[int, int, int, int]] | None:
    """OPT: work only on AOI bbox pixels (GEE clip to processRegion)."""
    ys, xs = np.where(mask)
    if ys.size == 0:
        return None
    h, w = nir.shape
    r0 = max(0, int(ys.min()) - pad)
    r1 = min(h, int(ys.max()) + 1 + pad)
    c0 = max(0, int(xs.min()) - pad)
    c1 = min(w, int(xs.max()) + 1 + pad)
    west, south, east, north = (float(v) for v in bounds)
    # Row 0 = north edge
    north_c = north - r0 / h * (north - south)
    south_c = north - r1 / h * (north - south)
    west_c = west + c0 / w * (east - west)
    east_c = west + c1 / w * (east - west)
    return (
        nir[r0:r1, c0:c1].copy(),
        mask[r0:r1, c0:c1].copy(),
        [west_c, south_c, east_c, north_c],
        (r0, r1, c0, c1),
    )


def _estimate_pixel_area_m2(bounds: list[float], shape: tuple[int, int], collection: str | None) -> float:
    west, south, east, north = (float(v) for v in bounds)
    h, w = shape
    if h < 1 or w < 1 or east <= west or north <= south:
        s = _nominal_scale_m(collection)
        return s * s
    mid_lat = 0.5 * (south + north)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * max(0.2, float(np.cos(np.deg2rad(mid_lat))))
    px_w = (east - west) / w * m_per_deg_lon
    px_h = (north - south) / h * m_per_deg_lat
    area = abs(px_w * px_h)
    nom = _nominal_scale_m(collection) ** 2
    return float(np.clip(area, nom * 0.25, nom * 64.0))


def _optimum_nir_threshold(nir: np.ndarray, search: np.ndarray) -> float:
    """Sensitive open-sea threshold from AOI water floor (optimum recall).

    Water NIR is typically ~0.02–0.04; ships/wakes sit above that. Using a fixed
    0.10 dropped many visible contacts. We set thr ≈ water_p80 + margin, clamped
    to a sensitive band so faint hulls are kept without lighting the whole AOI.
    """
    vals = nir[search & np.isfinite(nir)]
    if vals.size < 32:
        return float(DEFAULT_NIR_THRESHOLD)
    water_p80 = float(np.nanpercentile(vals, 80))
    water_med = float(np.nanmedian(vals))
    # Small margin above the water high-end; keep sensitive on clear open sea
    margin = max(0.012, 0.45 * max(water_p80 - water_med, 0.008))
    thr = water_p80 + margin
    return float(np.clip(thr, NIR_THR_MIN, NIR_THR_MAX))


def _scale_nir_reflectance(nir: np.ndarray, collection: str | None = None) -> np.ndarray:
    """Normalize Sentinel-2 / Landsat surface-reflectance NIR to 0–1.

    Sentinel-2 SR uses DN / 10000. Landsat Collection-2 Level-2 SR uses
    DN * 0.0000275 - 0.2. Keeping the collection-specific conversion here
    makes the server detector use the same reflectance basis as the GEE app.
    """
    nir_f = nir.astype(np.float64)
    c = (collection or "").upper().replace("_", "-")
    finite_sample = nir_f[np.isfinite(nir_f)]
    if not finite_sample.size:
        return nir_f

    p99 = float(np.nanpercentile(finite_sample, 99))
    if "LANDSAT" in c or c.startswith(("L7", "L8", "L9")):
        # Raw Landsat C2 L2 SR DN. If the loader already returned reflectance,
        # values are normally <= 1.5 and are left untouched.
        if p99 > 1.5:
            nir_f = nir_f * 0.0000275 - 0.2
    elif "SENTINEL-2" in c or c.startswith("S2") or "L2A" in c:
        # Sentinel-2 SR DN -> reflectance.
        if p99 > 1.5:
            nir_f = nir_f / 10000.0
    elif p99 > 1.5:
        # Conservative generic fallback for unknown optical SR arrays.
        nir_f = nir_f / 10000.0
    return nir_f


def detect_ships_optical_nir(
    bands: dict[str, np.ndarray],
    bounds: list[float],
    *,
    confidence_min: float = 0.08,
    collection: str | None = None,
    aoi_polygon: dict[str, Any] | None = None,
    nir_threshold: float | None = None,
    min_pixels: int | None = None,
) -> dict[str, Any]:
    """GEE OPTIMIZED open-sea detect: AOI-first NIR ≥ threshold + morph outline."""
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

    scl = bands.get("scl")
    nir_full = _scale_nir_reflectance(nir, collection)
    finite = np.isfinite(nir_full)

    # OPT 1: AOI mask first (precomputed once per call, reused)
    aoi_mask = _aoi_mask(nir_full.shape, bounds, aoi_polygon)
    search_full = finite.copy()
    if aoi_mask is not None:
        search_full &= aoi_mask

    if int(search_full.sum()) < 8:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "bounds": list(bounds),
            "formula": "NIR ≥ threshold · AOI-first — empty AOI",
            "message": "Water AOI has no usable pixels for ship detection",
        }

    # OPT: crop to AOI bbox so morph/CC only touch the intersection
    cropped = _crop_to_mask(nir_full, search_full, bounds, pad=4)
    if cropped is None:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "bounds": list(bounds),
            "formula": "NIR ≥ threshold · AOI-first — empty AOI",
            "message": "Water AOI has no usable pixels for ship detection",
        }
    nir_f, search, work_bounds, (r0, r1, c0, c1) = cropped
    if nir_threshold is not None:
        thr = float(nir_threshold)
    else:
        thr = _optimum_nir_threshold(nir_f, search)
    # Soft band for wakes / faint decks just below the hard threshold
    thr_soft = max(NIR_THR_MIN * 0.90, thr * 0.72)
    min_px = max(1, int(min_pixels) if min_pixels is not None else MIN_COMPONENT_PIXELS)

    px_area = _estimate_pixel_area_m2(work_bounds, nir_f.shape, collection)
    nom = _nominal_scale_m(collection)
    max_px_native = int(np.ceil(MAX_AREA_M2 / (nom * nom)))
    max_px_area = int(np.ceil(MAX_AREA_M2 / max(px_area, 1.0)))
    max_px = min(5_000, max(min_px, max_px_native, max_px_area))

    # Huge cloud sheets only (never compact decks)
    cloud = np.zeros(nir_f.shape, dtype=bool)
    if scl is not None:
        scl_c = scl[r0:r1, c0:c1]
        scl_cloud = np.isin(scl_c.astype(np.int16), [8, 9, 10]) & search
        labeled_c, n_c = _label_components(scl_cloud)
        for lab in range(1, n_c + 1):
            ys, xs = np.where(labeled_c == lab)
            if int(ys.size) >= 4000:
                cloud[ys, xs] = True
    very_bright = search & (nir_f >= ABS_CLOUD_HI)
    labeled_b, n_b = _label_components(very_bright)
    for lab in range(1, n_b + 1):
        ys, xs = np.where(labeled_b == lab)
        if int(ys.size) >= 5000:
            cloud[ys, xs] = True

    usable = search & ~cloud
    # Hard cores (optimum thr) + soft wakes near cores / elongated soft streaks
    hard = usable & (nir_f >= thr)
    soft = usable & (nir_f >= thr_soft) & (nir_f < thr)
    near_hard = _dilate(hard, iters=6) if hard.any() else soft
    wake = soft & near_hard
    # Also keep elongated soft-only streaks (wakes detached a few pixels)
    if soft.any():
        labeled_s, n_s = _label_components(soft)
        for lab in range(1, n_s + 1):
            ys, xs = np.where(labeled_s == lab)
            n = int(ys.size)
            if n < 2 or n > max_px:
                continue
            hspan = int(ys.max() - ys.min()) + 1
            wspan = int(xs.max() - xs.min()) + 1
            aspect = max(hspan, wspan) / max(1, min(hspan, wspan))
            if aspect >= 2.0 or near_hard[ys, xs].any():
                wake[ys, xs] = True
    ship_mask_raw = hard | wake

    # OPT: morph outline on clipped threshold mask (not full scene)
    overlay = _ship_overlay_rgba(ship_mask_raw)

    # Contacts = connected cleanup (GEE reduceToVectors / export path), in-memory
    labeled, nlab = _label_components(ship_mask_raw)
    comps: list[tuple[float, np.ndarray, np.ndarray]] = []
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        n = int(ys.size)
        if n < min_px or n > max_px:
            continue
        comps.append((float(np.nanmax(nir_f[ys, xs])), ys, xs))
    comps.sort(key=lambda t: -t[0])

    west, south, east, north = (float(v) for v in work_bounds)
    h, w = nir_f.shape
    features: list[dict[str, Any]] = []
    contact_n = 0

    for score, ys, xs in comps:
        excess = max(0.0, score - thr_soft)
        # Generous scores so faint-but-real contacts stay in the Locate list
        conf01 = float(np.clip(0.28 + excess / 0.22, 0.12, 0.99))
        if conf01 < confidence_min:
            continue
        row_c = float(ys.mean())
        col_c = float(xs.mean())
        lon = west + (col_c + 0.5) / w * (east - west)
        lat = north - (row_c + 0.5) / h * (north - south)
        rr0, rr1 = int(ys.min()), int(ys.max())
        cc0, cc1 = int(xs.min()), int(xs.max())

        def rc_to_lonlat(rr: float, cc: float) -> list[float]:
            return [
                west + (cc + 0.5) / w * (east - west),
                north - (rr + 0.5) / h * (north - south),
            ]

        pad_r, pad_c = 0.75, 0.75
        ring = [
            rc_to_lonlat(rr0 - pad_r, cc0 - pad_c),
            rc_to_lonlat(rr0 - pad_r, cc1 + pad_c),
            rc_to_lonlat(rr1 + pad_r, cc1 + pad_c),
            rc_to_lonlat(rr1 + pad_r, cc0 - pad_c),
            rc_to_lonlat(rr0 - pad_r, cc0 - pad_c),
        ]
        mean_nir = float(np.nanmean(nir_f[ys, xs]))
        max_nir = float(np.nanmax(nir_f[ys, xs]))
        contact_n += 1
        props = {
            "class": "ship",
            "label": f"Ship {contact_n}",
            "contact_id": contact_n,
            "confidence": round(conf01, 3),
            "nir_mean": round(mean_nir, 4),
            "nir_max": round(max_nir, 4),
            "nir_threshold": round(thr, 4),
            "nir_soft": round(thr_soft, 4),
            "pixels": int(ys.size),
            "cue": "nir_ge_threshold",
            "band": "NIR",
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
        if contact_n >= MAX_FEATURES:
            break

    # Fast pixel-sum style count of threshold pixels (GEE status-bar idea)
    bright_px = int(ship_mask_raw.sum())
    n_ships = contact_n
    logger.info(
        "Ship detect GEE-NIR-OPT sensitive: thr={:.3f} soft={:.3f} bright_px={} contacts={} crop={}x{}",
        thr,
        thr_soft,
        bright_px,
        n_ships,
        h,
        w,
    )
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": n_ships,
        "overlay": overlay,
        "bounds": work_bounds,
        "formula": (
            f"GEE OPT · AOI-first · sensitive NIR ≥ {thr:.3f} "
            f"(soft≥{thr_soft:.3f} wakes) · "
            f"morph outline (dilate−erode r={OUTLINE_RADIUS_PX}) · "
            f"contacts {min_px}–{max_px} px"
        ),
        "message": (
            f"{n_ships} ship contact(s) · sensitive NIR ≥ {thr:.3f} "
            f"inside water AOI ({bright_px} bright px)"
        ),
    }


def _ship_overlay_rgba(ship_mask: np.ndarray) -> np.ndarray:
    """Thick red morphological outline @ ~90% opacity (GEE palette ff0000)."""
    h, w = ship_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if not ship_mask.any():
        return rgba
    outline = _morph_outline(ship_mask, radius=OUTLINE_RADIUS_PX)
    rgba[outline, 0] = 255
    rgba[outline, 1] = 0
    rgba[outline, 2] = 0
    rgba[outline, 3] = 230
    return rgba
