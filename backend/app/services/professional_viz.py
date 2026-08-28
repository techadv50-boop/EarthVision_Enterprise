"""Professional EO visualization — industry-standard stretch / tone-map recipes.

True Color references (in priority order used by SAT EYE):
  1. ESA Sentinel-2 L2A official TCI / visual asset (display-balanced RGB)
  2. Sentinel Hub «Highlight Optimized Natural Color» for L2A:
     https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/highlight_optimized_natural_color/
     rgb = cbrt(0.6 * ρ)  — natural look, no burnt highlights
  3. Soft land-percentile fallback for odd sensors

Avoid the older «L2A Optimized» evalscript here: with BOA ρ≈0–1 it oversaturates
vegetation (neon green) and blows urban highlights on Pakistan scenes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Highlight Optimized Natural Color (Sentinel Hub / Marko Repše) — L2A
HIGHLIGHT_GAIN = 0.6

# Soft false-color / thematic stretch defaults
FCC_P_LOW = 2.0
FCC_P_HIGH = 98.0
FCC_GAMMA = 1.25
FCC_SAT = 1.08

# Index visualization ranges (QGIS / ArcGIS Pro practice)
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

PROFESSIONAL_COMPOSITE_NOTES: dict[str, str] = {
    "true_color": (
        "S2 B04-B03-B02 / L8 B4-B3-B2 · prefer ESA TCI; else "
        "Highlight Optimized Natural Color cbrt(0.6·ρ)"
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
    """DN→ρ: scale when values look like ×10000 BOA (robust to dark windows)."""
    out = stacked.astype(np.float64, copy=True)
    finite = np.isfinite(out)
    if not finite.any():
        return out
    sample = out[finite]
    # Prefer p99 so a few bright clouds don't matter; also catch full DN grids
    p99 = float(np.percentile(sample, 99))
    mx = float(np.nanmax(sample))
    if p99 > 1.5 or mx > 1.5:
        out = out / 10000.0
    return np.clip(out, 0.0, 1.0)


def true_color_highlight_optimized(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
    gain: float = HIGHLIGHT_GAIN,
) -> np.ndarray:
    """Natural-color RGB from L2A BOA reflectance (Highlight Optimized).

    ``cbrt(gain * ρ)`` compresses bright clouds/roofs without neon vegetation.
    Returns float RGB in [0,1].
    """
    stacked = ensure_reflectance(np.stack([r, g, b], axis=-1))
    finite = np.all(np.isfinite(stacked), axis=2)
    # Match Sentinel Hub L2A script exactly (no extra saturation boost)
    lin = np.clip(gain * stacked, 0.0, None)
    out = np.cbrt(lin)
    out = np.clip(out, 0.0, 1.0)

    c = float(contrast) if contrast else 1.0
    bv = float(brightness) if brightness else 1.0
    # Only apply tiny user tweaks — keep defaults neutral
    if abs(c - 1.0) > 1e-3:
        out = (out - 0.5) * max(0.9, min(c, 1.15)) + 0.5
    if abs(bv - 1.0) > 1e-3:
        out = out * max(0.9, min(bv, 1.1))
    out = np.clip(out, 0.0, 1.0)
    out[~finite] = 0.0
    return out


# Back-compat alias used by older call sites / tests
def true_color_l2a_optimized(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
    sat: float = 1.0,
    gamma: float = 1.0,
) -> np.ndarray:
    """Deprecated name — routes to Highlight Optimized (natural, non-neon)."""
    del sat, gamma
    return true_color_highlight_optimized(
        r, g, b, brightness=brightness, contrast=contrast
    )


def prepare_tci_display(
    rgb: np.ndarray,
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
) -> np.ndarray:
    """ESA/USGS visual TCI is already display-balanced — keep it nearly as-is."""
    out = rgb.astype(np.float64, copy=True)
    if np.nanmax(out) > 1.5:
        out = out / 255.0
    out = np.clip(out, 0.0, 1.0)
    finite = np.all(np.isfinite(out), axis=2)
    c = float(contrast) if contrast else 1.0
    bv = float(brightness) if brightness else 1.0
    if abs(c - 1.0) > 1e-3:
        out = (out - 0.5) * max(0.9, min(c, 1.1)) + 0.5
    if abs(bv - 1.0) > 1e-3:
        out = out * max(0.9, min(bv, 1.1))
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
    """Per-channel land-masked percentile stretch + mild gamma (FCC / thematic)."""
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
        gpow = 1.0 / max(1.05, min(float(gamma), 2.0))
        out[..., i] = np.power(stretched, gpow)
        out[~finite, i] = 0.0

    mean = out.mean(axis=2, keepdims=True)
    out = np.clip(mean + (out - mean) * sat, 0.0, 1.0)
    out = (out - 0.5) * max(0.9, min(float(contrast), 1.2)) + 0.5
    out = out * max(0.9, min(float(brightness), 1.15))
    return np.clip(out, 0.0, 1.0)


def index_viz_range(index: str, physical: tuple[float, float]) -> tuple[float, float]:
    return INDEX_VIZ_RANGE.get(index.upper(), physical)


def tool_standard_summary() -> dict[str, Any]:
    return {
        "true_color": PROFESSIONAL_COMPOSITE_NOTES["true_color"],
        "composites": PROFESSIONAL_COMPOSITE_NOTES,
        "indices_viz_range": {k: list(v) for k, v in INDEX_VIZ_RANGE.items()},
        "references": [
            "ESA Sentinel-2 L2A TCI visual product",
            "Sentinel Hub Highlight Optimized Natural Color (cbrt 0.6·ρ)",
            "USGS Landsat band combinations (FCC NIR-R-G)",
            "QGIS/ArcGIS NDVI display 0–0.8 RdYlGn",
        ],
    }
