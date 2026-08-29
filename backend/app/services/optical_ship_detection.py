"""Optical ship / open-sea object detection for Landsat / Sentinel-2.

Ported from the GEE "Ship Detection — NIR VERSION (FAST EDITION)" logic:

  1. Require Landsat / Sentinel-2 + drawn water-body AOI (raster mask).
  2. Scale NIR to reflectance; keep only AOI pixels.
  3. Ship candidates: NIR >= threshold (default 0.10).
  4. Connected-component size filter (min pixels … ~40 000 m² max).
  5. On-image mark = morphological outline (dilate − erode), thick red ring.
  6. Centroids → numbered ship contacts (Locate list); no shapefile download.

Threshold can float slightly above the AOI water floor so turbid/shallow
water does not light up the whole AOI, while open-sea ships stay above 0.10.
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

# GEE defaults (FAST EDITION)
DEFAULT_NIR_THRESHOLD = 0.10
MIN_COMPONENT_PIXELS = 1
MAX_AREA_M2 = 40_000
MAX_FEATURES = 300
# Absolute ceiling — vast sheets above this are treated as cloud/glare
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
    return 10.0  # Sentinel-2 NIR


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
    """GEE-style thick raster ring: dilate(r) − erode(r)."""
    if not ship_mask.any():
        return np.zeros_like(ship_mask, dtype=bool)
    r = max(1, int(radius))
    dilated = _dilate(ship_mask, iters=r)
    eroded = _erode(ship_mask, iters=r)
    outline = dilated & ~eroded
    # Tiny 1-px ships: eroded empties → fall back to dilated ring around core
    if not outline.any():
        outline = dilated & ~ship_mask
        if not outline.any():
            outline = dilated
    return outline


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
                for dy, dx in (
                    (0, 1),
                    (0, -1),
                    (1, 0),
                    (-1, 0),
                    (1, 1),
                    (1, -1),
                    (-1, 1),
                    (-1, -1),
                ):
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


def _estimate_pixel_area_m2(bounds: list[float], shape: tuple[int, int], collection: str | None) -> float:
    """Approx ground area per array pixel; fall back to sensor nominal scale."""
    west, south, east, north = (float(v) for v in bounds)
    h, w = shape
    if h < 1 or w < 1 or east <= west or north <= south:
        s = _nominal_scale_m(collection)
        return s * s
    # metres per degree (rough mid-latitude)
    mid_lat = 0.5 * (south + north)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * max(0.2, float(np.cos(np.deg2rad(mid_lat))))
    px_w = (east - west) / w * m_per_deg_lon
    px_h = (north - south) / h * m_per_deg_lat
    area = abs(px_w * px_h)
    # Clamp to something sane vs sensor scale
    nom = _nominal_scale_m(collection) ** 2
    return float(np.clip(area, nom * 0.25, nom * 64.0))


def _resolve_nir_threshold(
    nir: np.ndarray,
    search: np.ndarray,
    base: float = DEFAULT_NIR_THRESHOLD,
) -> float:
    """GEE default 0.10; raise only if AOI water floor is unusually bright."""
    vals = nir[search & np.isfinite(nir)]
    if vals.size < 16:
        return float(base)
    # Water is the dark majority of an open-sea AOI
    water_hi = float(np.nanpercentile(vals, 80))
    # Keep GEE threshold on clear open sea; lift for turbid/sunglint water
    if water_hi + 0.02 > base:
        return float(min(0.35, water_hi + 0.025))
    return float(base)


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
    """GEE-style open-sea ship detect: NIR >= threshold inside water AOI."""
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
    nir_f = nir.astype(np.float64)
    # If DN-like (0–10000), scale like S2_SR / 10000
    finite_sample = nir_f[np.isfinite(nir_f)]
    if finite_sample.size and float(np.nanpercentile(finite_sample, 99)) > 1.5:
        nir_f = nir_f / 10000.0

    finite = np.isfinite(nir_f)
    aoi_mask = _aoi_mask(nir_f.shape, bounds, aoi_polygon)
    search = finite.copy()
    if aoi_mask is not None:
        search &= aoi_mask

    if int(search.sum()) < 8:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "overlay": None,
            "formula": "NIR ≥ threshold · AOI mask — empty AOI",
            "message": "Water AOI has no usable pixels for ship detection",
        }

    thr = float(nir_threshold) if nir_threshold is not None else _resolve_nir_threshold(nir_f, search)
    min_px = int(min_pixels) if min_pixels is not None else MIN_COMPONENT_PIXELS
    min_px = max(1, min_px)

    px_area = _estimate_pixel_area_m2(bounds, nir_f.shape, collection)
    nom = _nominal_scale_m(collection)
    # GEE: maxPixels = ceil(40000 / scale²) at native resolution.
    # Our AOI arrays are often downsampled (1 array px ≫ sensor px), so use the
    # larger of native max and area/px_area — otherwise real ships exceed max_px.
    max_px_native = int(np.ceil(MAX_AREA_M2 / (nom * nom)))
    max_px_area = int(np.ceil(MAX_AREA_M2 / max(px_area, 1.0)))
    max_px = max(min_px, max_px_native, max_px_area)
    # Hard cap so full-scene cloud sheets cannot explode contact count
    max_px = min(max_px, 5_000)

    # Drop only huge SCL cloud sheets — never compact bright decks
    cloud = np.zeros(nir_f.shape, dtype=bool)
    if scl is not None:
        scl_cloud = np.isin(scl.astype(np.int16), [8, 9, 10])
        labeled_c, n_c = _label_components(scl_cloud & search)
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

    # PRIMARY (GEE): NIR >= threshold inside AOI
    candidates = search & ~cloud & (nir_f >= thr)

    labeled, nlab = _label_components(candidates)
    ship_mask = np.zeros_like(candidates)
    comps: list[tuple[float, np.ndarray, np.ndarray]] = []
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        n = int(ys.size)
        if n < min_px or n > max_px:
            continue
        score = float(np.nanmax(nir_f[ys, xs]))
        comps.append((score, ys, xs))
        ship_mask[ys, xs] = True

    comps.sort(key=lambda t: -t[0])

    west, south, east, north = (float(v) for v in bounds)
    h, w = nir_f.shape
    features: list[dict[str, Any]] = []
    contact_n = 0

    for score, ys, xs in comps:
        # Confidence from how far above the NIR threshold (GEE has no score;
        # we keep a soft score for the contacts UI).
        excess = max(0.0, score - thr)
        conf01 = float(np.clip(0.35 + excess / 0.25, 0.15, 0.99))
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

    overlay = _ship_overlay_rgba(ship_mask)
    n_ships = contact_n
    logger.info(
        "Ship detect GEE-NIR: thr={:.3f} min_px={} max_px={} contacts={}",
        thr,
        min_px,
        max_px,
        n_ships,
    )
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": n_ships,
        "overlay": overlay,
        "formula": (
            f"NIR ≥ {thr:.3f} (AOI mask) · connected {min_px}–{max_px} px · "
            f"morph outline dilate−erode · red ring"
        ),
        "message": f"{n_ships} ship(s) with NIR ≥ {thr:.3f} inside water AOI",
    }


def _ship_overlay_rgba(ship_mask: np.ndarray) -> np.ndarray:
    """Thick red morphological outline only (GEE FAST EDITION display)."""
    h, w = ship_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if not ship_mask.any():
        return rgba
    outline = _morph_outline(ship_mask, radius=OUTLINE_RADIUS_PX)
    # Bright red ring ~90% opacity (matches GEE palette + 0.9 opacity)
    rgba[outline, 0] = 255
    rgba[outline, 1] = 0
    rgba[outline, 2] = 0
    rgba[outline, 3] = 230
    return rgba
