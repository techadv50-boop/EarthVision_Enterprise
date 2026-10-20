"""Optical True Color plugin backend (worker / synthetic metadata).

Imagery I/O and composite rendering are fulfilled by the Host Shell via
Host SDK 1.2 methods (host.getSceneContext, host.renderTrueColor, …).
This module only returns static capability / band-recipe metadata.
"""

PACK_VERSION = "1.0.0"

# OSINT band recipes (mirror COMPOSITE_BAND_CODES["true_color"])
TRUE_COLOR_BANDS = {
    "SENTINEL-2": {
        "codes": "B04-B03-B02",
        "formula": "R=Red(B04), G=Green(B03), B=Blue(B02) — natural color",
        "R": "B04",
        "G": "B03",
        "B": "B02",
    },
    "LANDSAT-8": {
        "codes": "B4-B3-B2",
        "formula": "R=Red(B4), G=Green(B3), B=Blue(B2) — natural color",
        "R": "B4",
        "G": "B3",
        "B": "B2",
    },
    "LANDSAT-9": {
        "codes": "B4-B3-B2",
        "formula": "R=Red(B4), G=Green(B3), B=Blue(B2) — natural color",
        "R": "B4",
        "G": "B3",
        "B": "B2",
    },
    "LANDSAT-7": {
        "codes": "B3-B2-B1",
        "formula": "R=Red(B3), G=Green(B2), B=Blue(B1) — natural color",
        "R": "B3",
        "G": "B2",
        "B": "B1",
    },
    "MODIS": {
        "codes": "B01-B04-B03",
        "formula": "R=Red(B01), G=Green(B04), B=Blue(B03) — natural color",
        "R": "B01",
        "G": "B04",
        "B": "B03",
    },
}


def render(payload=None):
    payload = payload or {}
    family = str(payload.get("family") or "").upper() or None
    recipe = TRUE_COLOR_BANDS.get(family) if family else None
    return {
        "plugin_id": "optical_true_color",
        "version": PACK_VERSION,
        "kind": "optical_true_color",
        "message": "True color RGB composite for optical satellites only.",
        "optical_only": True,
        "export": {"geotiff": True, "map_jpeg_dpi": [300, 600]},
        "band_recipes": TRUE_COLOR_BANDS,
        "active_recipe": recipe,
        "metrics": [
            {"label": "Preset", "value": "true_color"},
            {"label": "Method", "value": "percentile stretch RGB"},
        ],
        "note": "Host SDK fulfills scene, render, and export. No Leaflet in iframe.",
    }
