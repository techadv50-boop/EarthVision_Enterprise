"""Imagery resolution bands for tools and satellite categorization.

Tools declare which resolution bands (and optionally which satellites) they apply to
at upload/placement time. Admins tag each satellite with a resolution category so
providers can be segregated in admin UI.
"""

from __future__ import annotations

from typing import Iterable

# Stable keys stored in DB / API. Labels match admin-facing copy.
RESOLUTION_BANDS: tuple[tuple[str, str], ...] = (
    ("lte_1m", "≤1m"),
    ("lte_2m", "≤2m"),
    ("lte_3m", "≤3m"),
    ("lte_5m", "≤5m"),
    ("lte_10m", "≤10m"),
    ("lte_15m", "≤15m"),
    ("lte_30m", "≤30m"),
    ("lt_30m", "<30m"),
    ("gt_30m", ">30m"),
)

RESOLUTION_BAND_KEYS: frozenset[str] = frozenset(k for k, _ in RESOLUTION_BANDS)
RESOLUTION_BAND_LABELS: dict[str, str] = dict(RESOLUTION_BANDS)

# Default resolution category for built-in free EO catalogs.
BUILTIN_RESOLUTION_CATEGORY: dict[str, str] = {
    "SENTINEL-2": "lte_10m",
    "SENTINEL-1": "lte_10m",
    "SENTINEL-3": "gt_30m",
    "SENTINEL-5P": "gt_30m",
    "LANDSAT-9": "lte_30m",
    "LANDSAT-8": "lte_30m",
    "LANDSAT-7": "lte_30m",
    "MODIS": "gt_30m",
    "TERRA": "gt_30m",
    "AQUA": "gt_30m",
    "SMOS": "gt_30m",
}

# Bands that imply commercial / domain (high-res) toolbox eligibility.
HIGH_RESOLUTION_BANDS: frozenset[str] = frozenset(
    {"lte_1m", "lte_2m", "lte_3m", "lte_5m"}
)


def resolution_band_options() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in RESOLUTION_BANDS]


def normalize_resolution_bands(values: Iterable[str] | None) -> list[str]:
    """Return unique valid band keys in canonical order. Empty list = unspecified."""
    if not values:
        return []
    wanted = {str(v).strip() for v in values if str(v).strip()}
    unknown = wanted - RESOLUTION_BAND_KEYS
    if unknown:
        raise ValueError(
            "unknown resolution band(s): "
            + ", ".join(sorted(unknown))
            + f"; allowed: {', '.join(k for k, _ in RESOLUTION_BANDS)}"
        )
    return [k for k, _ in RESOLUTION_BANDS if k in wanted]


def normalize_resolution_category(value: str | None) -> str | None:
    """Single category for a satellite; None/blank clears the tag."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned not in RESOLUTION_BAND_KEYS:
        raise ValueError(
            f"unknown resolution category '{cleaned}'; "
            f"allowed: {', '.join(k for k, _ in RESOLUTION_BANDS)}"
        )
    return cleaned


def normalize_satellite_names(values: Iterable[str] | None) -> list[str]:
    """Stable satellite keys (e.g. SENTINEL-2); empty = any tagged satellite."""
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = str(raw or "").strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name[:64])
    return out


def category_implies_high_resolution(category: str | None) -> bool:
    return bool(category and category in HIGH_RESOLUTION_BANDS)
