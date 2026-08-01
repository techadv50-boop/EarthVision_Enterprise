"""Satellite family helpers and accurate band codes for composites / indices."""

from __future__ import annotations

from typing import Any

# Families that can run optical multispectral RGB / index tools in this app
OPTICAL_SWIR_FAMILY = (
    "SENTINEL-2",
    "LANDSAT-8",
    "LANDSAT-9",
    "LANDSAT-7",
    "MODIS",
)

# LST uses Landsat TIRS in our pipeline
THERMAL_FAMILY = ("LANDSAT-8", "LANDSAT-9")


def normalize_satellite_family(collection: str | None) -> str:
    """Map catalog collection ids → capability family."""
    c = (collection or "").upper().replace("_", "-")
    if not c:
        return "UNKNOWN"
    if c.startswith("S2") or "SENTINEL-2" in c:
        return "SENTINEL-2"
    if c.startswith("S1") or "SENTINEL-1" in c:
        return "SENTINEL-1"
    if "SENTINEL-3" in c or c.startswith("S3"):
        return "SENTINEL-3"
    if "SENTINEL-5" in c or "S5P" in c:
        return "SENTINEL-5P"
    if "LANDSAT-8" in c or c in {"LC08", "L8"}:
        return "LANDSAT-8"
    if "LANDSAT-9" in c or c in {"LC09", "L9"}:
        return "LANDSAT-9"
    if "LANDSAT-7" in c or c in {"LE07", "L7"}:
        return "LANDSAT-7"
    if "LANDSAT" in c:
        return "LANDSAT-8"
    if c in {"MODIS", "TERRAAQUA", "TERRA", "AQUA"} or "MODIS" in c:
        return "MODIS"
    if "SMOS" in c:
        return "SMOS"
    return c


def family_label(family: str) -> str:
    return {
        "SENTINEL-2": "Sentinel-2",
        "SENTINEL-1": "Sentinel-1",
        "SENTINEL-3": "Sentinel-3",
        "SENTINEL-5P": "Sentinel-5P",
        "LANDSAT-8": "Landsat-8",
        "LANDSAT-9": "Landsat-9",
        "LANDSAT-7": "Landsat-7",
        "MODIS": "MODIS",
        "SMOS": "SMOS",
    }.get(family, family)


# Accurate RGB band codes per sensor (R-G-B product order)
# Landsat-8 OLI / Landsat-9 OLI-2: same C2 L2 numbering —
#   B2 Blue, B3 Green, B4 Red, B5 NIR, B6 SWIR1, B7 SWIR2, ST_B10 thermal
# Landsat-7 ETM+: B1 Blue, B2 Green, B3 Red, B4 NIR, B5 SWIR1, B7 SWIR2
# Sentinel-2: B02 Blue, B03 Green, B04 Red, B08 NIR, B11 SWIR1, B12 SWIR2
# MODIS 09A1: B01 Red, B02 NIR, B03 Blue, B04 Green, B06 SWIR1, B07 SWIR2
#
# USGS Collection-2 Level-2 scale factors (identical for L8 and L9):
#   SR:  ρ = DN × 0.0000275 − 0.2
#   ST:  Kelvin = DN × 0.00341802 + 149.0
# Sentinel-2 L2A BOA (ESA PB ≥ 04.00 / Earth Search):
#   ρ = DN × 0.0001 − 0.1   (SCL masks cloud/shadow/snow for indices)
COMPOSITE_BAND_CODES: dict[str, dict[str, dict[str, str]]] = {
    "true_color": {
        "SENTINEL-2": {
            "codes": "B04-B03-B02",
            "formula": "R=Red(B04), G=Green(B03), B=Blue(B02) — natural color",
        },
        "LANDSAT-8": {
            "codes": "B4-B3-B2",
            "formula": "R=Red(B4), G=Green(B3), B=Blue(B2) — natural color",
        },
        "LANDSAT-9": {
            "codes": "B4-B3-B2",
            "formula": "R=Red(B4), G=Green(B3), B=Blue(B2) — natural color",
        },
        "LANDSAT-7": {
            "codes": "B3-B2-B1",
            "formula": "R=Red(B3), G=Green(B2), B=Blue(B1) — natural color",
        },
        "MODIS": {
            "codes": "B01-B04-B03",
            "formula": "R=Red(B01), G=Green(B04), B=Blue(B03) — natural color",
        },
    },
    "false_color_infrared": {
        "SENTINEL-2": {
            "codes": "B08-B04-B03",
            "formula": "R=NIR(B08), G=Red(B04), B=Green(B03) — veg bright red",
        },
        "LANDSAT-8": {
            "codes": "B5-B4-B3",
            "formula": "R=NIR(B5), G=Red(B4), B=Green(B3) — veg bright red",
        },
        "LANDSAT-9": {
            "codes": "B5-B4-B3",
            "formula": "R=NIR(B5), G=Red(B4), B=Green(B3) — veg bright red",
        },
        "LANDSAT-7": {
            "codes": "B4-B3-B2",
            "formula": "R=NIR(B4), G=Red(B3), B=Green(B2) — veg bright red",
        },
        "MODIS": {
            "codes": "B02-B01-B04",
            "formula": "R=NIR(B02), G=Red(B01), B=Green(B04) — veg bright red",
        },
    },
    "false_color_agriculture": {
        "SENTINEL-2": {
            "codes": "B11-B08-B02",
            "formula": "R=SWIR1(B11), G=NIR(B08), B=Blue(B02) — crops & soils",
        },
        "LANDSAT-8": {
            "codes": "B6-B5-B2",
            "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2) — crops & soils",
        },
        "LANDSAT-9": {
            "codes": "B6-B5-B2",
            "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2) — crops & soils",
        },
        "LANDSAT-7": {
            "codes": "B5-B4-B1",
            "formula": "R=SWIR1(B5), G=NIR(B4), B=Blue(B1) — crops & soils",
        },
        "MODIS": {
            "codes": "B06-B02-B03",
            "formula": "R=SWIR1(B06), G=NIR(B02), B=Blue(B03) — crops & soils",
        },
    },
    "false_color_urban": {
        "SENTINEL-2": {
            "codes": "B11-B08-B04",
            "formula": "R=SWIR1(B11), G=NIR(B08), B=Red(B04) — built-up bright",
        },
        "LANDSAT-8": {
            "codes": "B6-B5-B4",
            "formula": "R=SWIR1(B6), G=NIR(B5), B=Red(B4) — built-up bright",
        },
        "LANDSAT-9": {
            "codes": "B6-B5-B4",
            "formula": "R=SWIR1(B6), G=NIR(B5), B=Red(B4) — built-up bright",
        },
        "LANDSAT-7": {
            "codes": "B5-B4-B3",
            "formula": "R=SWIR1(B5), G=NIR(B4), B=Red(B3) — built-up bright",
        },
        "MODIS": {
            "codes": "B06-B02-B01",
            "formula": "R=SWIR1(B06), G=NIR(B02), B=Red(B01) — built-up bright",
        },
    },
    "swir_composite": {
        "SENTINEL-2": {
            "codes": "B12-B11-B04",
            "formula": "R=SWIR2(B12), G=SWIR1(B11), B=Red(B04) — moisture & geology",
        },
        "LANDSAT-8": {
            "codes": "B7-B6-B4",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4) — moisture & geology",
        },
        "LANDSAT-9": {
            "codes": "B7-B6-B4",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4) — moisture & geology",
        },
        "LANDSAT-7": {
            "codes": "B7-B5-B3",
            "formula": "R=SWIR2(B7), G=SWIR1(B5), B=Red(B3) — moisture & geology",
        },
        "MODIS": {
            "codes": "B07-B06-B01",
            "formula": "R=SWIR2(B07), G=SWIR1(B06), B=Red(B01) — moisture & geology",
        },
    },
    "geology": {
        "SENTINEL-2": {
            "codes": "B12-B11-B02",
            "formula": "R=SWIR2(B12), G=SWIR1(B11), B=Blue(B02) — rock & soil types",
        },
        "LANDSAT-8": {
            "codes": "B7-B6-B2",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Blue(B2) — rock & soil types",
        },
        "LANDSAT-9": {
            "codes": "B7-B6-B2",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Blue(B2) — rock & soil types",
        },
        "LANDSAT-7": {
            "codes": "B7-B5-B1",
            "formula": "R=SWIR2(B7), G=SWIR1(B5), B=Blue(B1) — rock & soil types",
        },
        "MODIS": {
            "codes": "B07-B06-B03",
            "formula": "R=SWIR2(B07), G=SWIR1(B06), B=Blue(B03) — rock & soil types",
        },
    },
    "atmospheric_penetration": {
        "SENTINEL-2": {
            "codes": "B12-B11-B08",
            "formula": "R=SWIR2(B12), G=SWIR1(B11), B=NIR(B08) — haze penetration",
        },
        "LANDSAT-8": {
            "codes": "B7-B6-B5",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=NIR(B5) — haze penetration",
        },
        "LANDSAT-9": {
            "codes": "B7-B6-B5",
            "formula": "R=SWIR2(B7), G=SWIR1(B6), B=NIR(B5) — haze penetration",
        },
        "LANDSAT-7": {
            "codes": "B7-B5-B4",
            "formula": "R=SWIR2(B7), G=SWIR1(B5), B=NIR(B4) — haze penetration",
        },
        "MODIS": {
            "codes": "B07-B06-B02",
            "formula": "R=SWIR2(B07), G=SWIR1(B06), B=NIR(B02) — haze penetration",
        },
    },
    "land_water": {
        "SENTINEL-2": {
            "codes": "B08-B11-B04",
            "formula": "R=NIR(B08), G=SWIR1(B11), B=Red(B04) — water dark, land bright",
        },
        "LANDSAT-8": {
            "codes": "B5-B6-B4",
            "formula": "R=NIR(B5), G=SWIR1(B6), B=Red(B4) — water dark, land bright",
        },
        "LANDSAT-9": {
            "codes": "B5-B6-B4",
            "formula": "R=NIR(B5), G=SWIR1(B6), B=Red(B4) — water dark, land bright",
        },
        "LANDSAT-7": {
            "codes": "B4-B5-B3",
            "formula": "R=NIR(B4), G=SWIR1(B5), B=Red(B3) — water dark, land bright",
        },
        "MODIS": {
            "codes": "B02-B06-B01",
            "formula": "R=NIR(B02), G=SWIR1(B06), B=Red(B01) — water dark, land bright",
        },
    },
    "vegetation_health": {
        "SENTINEL-2": {
            "codes": "B08-B11-B03",
            "formula": "R=NIR(B08), G=SWIR1(B11), B=Green(B03) — healthy veg bright",
        },
        "LANDSAT-8": {
            "codes": "B5-B6-B3",
            "formula": "R=NIR(B5), G=SWIR1(B6), B=Green(B3) — healthy veg bright",
        },
        "LANDSAT-9": {
            "codes": "B5-B6-B3",
            "formula": "R=NIR(B5), G=SWIR1(B6), B=Green(B3) — healthy veg bright",
        },
        "LANDSAT-7": {
            "codes": "B4-B5-B2",
            "formula": "R=NIR(B4), G=SWIR1(B5), B=Green(B2) — healthy veg bright",
        },
        "MODIS": {
            "codes": "B02-B06-B04",
            "formula": "R=NIR(B02), G=SWIR1(B06), B=Green(B04) — healthy veg bright",
        },
    },
    "burn_severity": {
        "SENTINEL-2": {
            "codes": "B12-B08-B03",
            "formula": "R=SWIR2(B12), G=NIR(B08), B=Green(B03) — burns magenta/red",
        },
        "LANDSAT-8": {
            "codes": "B7-B5-B3",
            "formula": "R=SWIR2(B7), G=NIR(B5), B=Green(B3) — burns magenta/red",
        },
        "LANDSAT-9": {
            "codes": "B7-B5-B3",
            "formula": "R=SWIR2(B7), G=NIR(B5), B=Green(B3) — burns magenta/red",
        },
        "LANDSAT-7": {
            "codes": "B7-B4-B2",
            "formula": "R=SWIR2(B7), G=NIR(B4), B=Green(B2) — burns magenta/red",
        },
        "MODIS": {
            "codes": "B07-B02-B04",
            "formula": "R=SWIR2(B07), G=NIR(B02), B=Green(B04) — burns magenta/red",
        },
    },
}

# Internal reflectance keys required for each composite
COMPOSITE_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "true_color": ("red", "green", "blue"),
    "false_color_infrared": ("nir", "red", "green"),
    "false_color_agriculture": ("swir", "nir", "blue"),
    "false_color_urban": ("swir", "nir", "red"),
    "swir_composite": ("swir2", "swir", "red"),
    "geology": ("swir2", "swir", "blue"),
    "atmospheric_penetration": ("swir2", "swir", "nir"),
    "land_water": ("nir", "swir", "red"),
    "vegetation_health": ("nir", "swir", "green"),
    "burn_severity": ("swir2", "nir", "green"),
}

INDEX_APPLICABLE: dict[str, tuple[str, ...]] = {
    "NDVI": OPTICAL_SWIR_FAMILY,
    "NDWI": OPTICAL_SWIR_FAMILY,
    "SAVI": OPTICAL_SWIR_FAMILY,
    "EVI": OPTICAL_SWIR_FAMILY,
    "NDBI": OPTICAL_SWIR_FAMILY,
    "BSI": OPTICAL_SWIR_FAMILY,
    "NDMI": OPTICAL_SWIR_FAMILY,
    "NBR": OPTICAL_SWIR_FAMILY,
    "LST": THERMAL_FAMILY,
}

INDEX_BAND_NOTES: dict[str, dict[str, str]] = {
    "NDVI": {
        "SENTINEL-2": "B08 + B04",
        "LANDSAT-8": "B5 + B4",
        "LANDSAT-9": "B5 + B4",
        "LANDSAT-7": "B4 + B3",
        "MODIS": "B02 + B01",
    },
    "NDWI": {
        "SENTINEL-2": "B03 + B08",
        "LANDSAT-8": "B3 + B5",
        "LANDSAT-9": "B3 + B5",
        "LANDSAT-7": "B2 + B4",
        "MODIS": "B04 + B02",
    },
    "NDBI": {
        "SENTINEL-2": "B11 + B08",
        "LANDSAT-8": "B6 + B5",
        "LANDSAT-9": "B6 + B5",
        "LANDSAT-7": "B5 + B4",
        "MODIS": "B06 + B02",
    },
    "SAVI": {
        "SENTINEL-2": "B08 + B04",
        "LANDSAT-8": "B5 + B4",
        "LANDSAT-9": "B5 + B4",
        "LANDSAT-7": "B4 + B3",
        "MODIS": "B02 + B01",
    },
    "BSI": {
        "SENTINEL-2": "B11 + B04 + B08 + B03",
        "LANDSAT-8": "B6 + B4 + B5 + B3",
        "LANDSAT-9": "B6 + B4 + B5 + B3",
        "LANDSAT-7": "B5 + B3 + B4 + B2",
        "MODIS": "B06 + B01 + B02 + B04",
    },
    "EVI": {
        "SENTINEL-2": "B08 + B04 + B02",
        "LANDSAT-8": "B5 + B4 + B2",
        "LANDSAT-9": "B5 + B4 + B2",
        "LANDSAT-7": "B4 + B3 + B1",
        "MODIS": "B02 + B01 + B03",
    },
    "NDMI": {
        "SENTINEL-2": "B08 + B11",
        "LANDSAT-8": "B5 + B6",
        "LANDSAT-9": "B5 + B6",
        "LANDSAT-7": "B4 + B5",
        "MODIS": "B02 + B06",
    },
    "NBR": {
        "SENTINEL-2": "B08 + B12",
        "LANDSAT-8": "B5 + B7",
        "LANDSAT-9": "B5 + B7",
        "LANDSAT-7": "B4 + B7",
        "MODIS": "B02 + B07",
    },
    "LST": {
        "LANDSAT-8": "ST_B10 / TIRS (C2 L2 → °C)",
        "LANDSAT-9": "ST_B10 / TIRS-2 (C2 L2 → °C)",
    },
}


def assert_landsat89_parity() -> None:
    """Guard: Landsat-9 OLI-2 must stay aligned with Landsat-8 OLI band codes."""
    for preset_id, fams in COMPOSITE_BAND_CODES.items():
        a, b = fams.get("LANDSAT-8"), fams.get("LANDSAT-9")
        if a != b:
            raise AssertionError(
                f"Composite '{preset_id}' Landsat-8/9 band codes drifted: {a} vs {b}"
            )
    for index_id, notes in INDEX_BAND_NOTES.items():
        # LST labels may mention TIRS vs TIRS-2; compare band identity via applicable set
        if index_id == "LST":
            continue
        if notes.get("LANDSAT-8") != notes.get("LANDSAT-9"):
            raise AssertionError(
                f"Index '{index_id}' Landsat-8/9 band notes drifted: "
                f"{notes.get('LANDSAT-8')} vs {notes.get('LANDSAT-9')}"
            )
    if set(INDEX_APPLICABLE.get("LST", ())) != {"LANDSAT-8", "LANDSAT-9"}:
        raise AssertionError("LST must apply to Landsat-8 and Landsat-9 only")


assert_landsat89_parity()


def composite_applicable_families(preset_id: str) -> list[str]:
    codes = COMPOSITE_BAND_CODES.get(preset_id) or {}
    return list(codes.keys())


def composite_for_family(preset_id: str, family: str) -> dict[str, str] | None:
    return (COMPOSITE_BAND_CODES.get(preset_id) or {}).get(family)


def index_applicable(index_id: str, family: str) -> bool:
    allowed = INDEX_APPLICABLE.get(index_id.upper())
    if not allowed:
        return False
    return family in allowed


def capability_summary(family: str) -> dict[str, Any]:
    return {
        "family": family,
        "label": family_label(family),
        "optical_swir": family in OPTICAL_SWIR_FAMILY,
        "thermal_lst": family in THERMAL_FAMILY,
        "composites": [
            pid for pid in COMPOSITE_BAND_CODES if family in COMPOSITE_BAND_CODES[pid]
        ],
        "indices": [iid for iid, fams in INDEX_APPLICABLE.items() if family in fams],
    }
