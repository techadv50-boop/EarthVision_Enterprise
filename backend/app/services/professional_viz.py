"""Professional EO visualization — industry-standard stretch / tone-map recipes.

References (True Color):
  - Sentinel Hub «Sentinel-2 L2A True Color Optimized»
    https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/l2a_optimized/
    Highlight compression + γ=1.8 + sat=1.2 + sRGB encoding.
  - ESA EOPF / Copernicus: percentile (2–98) + gamma for TCI education materials.
  - USGS / QGIS practice for NDVI display: clip viz to ~0…0.8 with RdYlGn.

These helpers operate on surface/BOA reflectance grids (≈0–1).
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Sentinel Hub L2A Optimized constants
L2A_MAX_R = 3.0
L2A_MID_R = 0.13
L2A_SAT = 1.2
L2A_GAMMA = 1.8
L2A_G_OFF = 0.01

# Professional false-color / thematic stretch defaults
FCC_P_LOW = 2.0
FCC_P_HIGH = 98.0
FCC_GAMMA = 1.35
FCC_SAT = 1.15

# Index visualization ranges used by ArcGIS Pro / QGIS practice (not physical ±1)
INDEX_VIZ_RANGE: dict[str, tuple[float, float]] = {
    "NDVI": (0.0, 0.8),
    "SAVI": (0.0, 0.8),
    "EVI": (0.0, 0.8),
    "NDWI": (-0.2, 0.5),
    "NDBI": (-0.25, 0.45),
    "BSI": (-0.2, 0.5),
    "NDMI": (-0.4, 0.5),
    "NBR": (-0.5, 0.8),
    "LST": (-10.0, 55.0),
}

# USGS / ESA classic false-color band recipes (internal keys)
PROFESSIONAL_COMPOSITE_NOTES: dict[str, str] = {
    "true_color": (
        "S2 B04-B03-B02 / L8 B4-B3-B2 · Sentinel Hub L2A Optimized "
        "(highlight compress + γ1.8 + sRGB)"
    ),
    "false_color_infrared": (
        "Classic FCC: NIR-Red-Green (S2 B08-B04-B03 / L8 B5-B4-B3) — vegetation red"
    ),
    "false_color_agriculture": "SWIR1-NIR-Blue — crop / soil contrast (USGS agri combo)",
    "false_color_urban": "SWIR1-NIR-Red — built-up bright (pairs with NDBI)",
    "swir_composite": "SWIR2-SWIR1-Red — moisture & geology",
    "geology": "SWIR2-SWIR1-Blue — lithology",
    "atmospheric_penetration": "SWIR2-SWIR1-NIR — haze / smoke penetration",
    "land_water": "NIR-SWIR1-Red — water dark",
    "vegetation_health": "NIR-SWIR1-Green — veg stress",
    "burn_severity": "SWIR2-NIR-Green — burn scars (pairs with NBR)",
}


def _clip01(x: np.ndarray | float) -> np.ndarray | float:
    return np.clip(x, 0.0, 1.0)


def ensure_reflectance(stacked: np.ndarray) -> np.ndarray:
    """DN→ρ heuristic: values ≫1 treated as ×10000 scaled BOA."""
    out = stacked.astype(np.float64, copy=False)
    finite = np.isfinite(out)
    if finite.any() and float(np.nanmax(out)) > 1.5:
        out = out / 10000.0
    return np.clip(out, 0.0, 1.0)


def _l2a_adj(a: np.ndarray, tx: float = L2A_MID_R, ty: float = 1.0, max_c: float = L2A_MAX_R) -> np.ndarray:
    """Contrast enhance + highlight compress (Sentinel Hub L2A Optimized)."""
    ar = _clip01(a / max_c)
    num = ar * (ar * (tx / max_c + ty - 1.0) - ty)
    den = ar * (2.0 * tx / max_c - 1.0) - tx / max_c
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(den) < 1e-12, 0.0, num / den)
    return _clip01(out)


def _l2a_adj_gamma(b: np.ndarray, gamma: float = L2A_GAMMA) -> np.ndarray:
    g_off = L2A_G_OFF
    g_off_pow = g_off**gamma
    g_off_range = (1.0 + g_off) ** gamma - g_off_pow
    return ((np.power(b + g_off, gamma) - g_off_pow) / g_off_range).astype(np.float64)


def _srgb_encode(c: np.ndarray) -> np.ndarray:
    """Linear → sRGB transfer (IEC 61966-2-1)."""
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def _sat_enhance(r: np.ndarray, g: np.ndarray, b: np.ndarray, sat: float = L2A_SAT) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    avg = (r + g + b) / 3.0 * (1.0 - sat)
    return (
        _clip01(avg + r * sat),
        _clip01(avg + g * sat),
        _clip01(avg + b * sat),
    )


def true_color_l2a_optimized(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
    sat: float = L2A_SAT,
    gamma: float = L2A_GAMMA,
) -> np.ndarray:
    """Professional natural-color RGB from BOA reflectance (Sentinel Hub L2A Optimized).

    Returns float RGB in [0,1] ready for overlay encode.
    """
    stacked = ensure_reflectance(np.stack([r, g, b], axis=-1))
    finite = np.all(np.isfinite(stacked), axis=2)

    rr = _l2a_adj_gamma(_l2a_adj(stacked[..., 0]), gamma=gamma)
    gg = _l2a_adj_gamma(_l2a_adj(stacked[..., 1]), gamma=gamma)
    bb = _l2a_adj_gamma(_l2a_adj(stacked[..., 2]), gamma=gamma)
    rr, gg, bb = _sat_enhance(rr, gg, bb, sat=sat)

    out = np.stack([_srgb_encode(rr), _srgb_encode(gg), _srgb_encode(bb)], axis=-1)
    c = float(contrast) if contrast else 1.0
    bv = float(brightness) if brightness else 1.0
    if abs(c - 1.0) > 1e-3:
        out = (out - 0.5) * max(0.85, min(c, 1.25)) + 0.5
    if abs(bv - 1.0) > 1e-3:
        out = out * max(0.85, min(bv, 1.2))
    out = np.clip(out, 0.0, 1.0)
    out[~finite] = 0.0
    return out


def false_color_professional(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    *,
    p_low: float = FCC_P_LOW,
    p_high: float = FCC_P_HIGH,
    gamma: float = FCC_GAMMA,
    brightness: float = 1.0,
    contrast: float = 1.05,
    sat: float = FCC_SAT,
) -> np.ndarray:
    """Per-channel land-masked percentile stretch + mild gamma + sRGB (FCC / thematic)."""
    stacked = ensure_reflectance(np.stack([r, g, b], axis=-1))
    finite = np.all(np.isfinite(stacked), axis=2)
    bright = np.nanmean(stacked, axis=2)
    if finite.any():
        cloud_cut = float(np.percentile(bright[finite], 92))
        dark_cut = float(np.percentile(bright[finite], 2))
        land = finite & (bright >= dark_cut) & (bright <= cloud_cut)
        if land.sum() < max(64, int(0.05 * finite.sum())):
            land = finite
    else:
        land = finite

    out = np.zeros_like(stacked, dtype=np.float64)
    for i in range(3):
        ch = stacked[..., i]
        vals = ch[land]
        if vals.size == 0:
            vals = ch[finite]
        if vals.size == 0:
            continue
        lo = float(np.percentile(vals, p_low))
        hi = float(np.percentile(vals, p_high))
        if hi <= lo:
            hi = lo + 1e-6
        stretched = np.clip((ch - lo) / (hi - lo), 0.0, 1.0)
        # Display gamma (brighten midtones) then sRGB
        gpow = 1.0 / max(1.05, min(float(gamma), 2.2))
        lin = np.power(stretched, gpow)
        out[..., i] = _srgb_encode(lin)
        out[~finite, i] = 0.0

    mean = out.mean(axis=2, keepdims=True)
    out = np.clip(mean + (out - mean) * sat, 0.0, 1.0)
    out = (out - 0.5) * max(0.85, min(float(contrast), 1.3)) + 0.5
    out = out * max(0.85, min(float(brightness), 1.2))
    return np.clip(out, 0.0, 1.0)


def index_viz_range(index: str, physical: tuple[float, float]) -> tuple[float, float]:
    """Prefer professional display window; fall back to physical meta range."""
    return INDEX_VIZ_RANGE.get(index.upper(), physical)


def tool_standard_summary() -> dict[str, Any]:
    """Compact registry of professional standards used by SAT EYE tool families."""
    return {
        "true_color": PROFESSIONAL_COMPOSITE_NOTES["true_color"],
        "composites": PROFESSIONAL_COMPOSITE_NOTES,
        "indices_viz_range": {k: list(v) for k, v in INDEX_VIZ_RANGE.items()},
        "references": [
            "Sentinel Hub L2A True Color Optimized",
            "USGS Landsat band combinations (FCC NIR-R-G)",
            "QGIS/ArcGIS NDVI display 0–0.8 RdYlGn",
            "McFeeters 1996 NDWI · Huete 1988 SAVI · Key & Benson NBR",
        ],
    }
