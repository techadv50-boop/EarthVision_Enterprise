"""NDWI (Optical) plugin backend (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderIndex (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

INDEX_RECIPES = {
  "NDWI": {
    "formula": "(GREEN - NIR) / (GREEN + NIR)",
    "SENTINEL-2": "B03 + B08",
    "LANDSAT-8": "B3 + B5",
    "LANDSAT-9": "B3 + B5",
    "LANDSAT-7": "B2 + B4",
    "MODIS": "B04 + B02",
    "cmap": "blues"
  }
}


def render(payload=None):
    payload = payload or {}
    index = str(payload.get("index") or "NDWI").upper()
    family = str(payload.get("family") or "").upper() or None
    block = INDEX_RECIPES.get(index) or INDEX_RECIPES["NDWI"]
    bands = block.get(family) if family else None
    return {
        "plugin_id": "optical_ndwi",
        "version": PACK_VERSION,
        "kind": "optical_ndwi",
        "message": "McFeeters NDWI water index for Sentinel-2 and Landsat 7/8/9.",
        "optical_only": True,
        "default_index": "NDWI",
        "indices": INDEX_RECIPES,
        "active_bands": bands,
        "export": {"geotiff": True, "map_jpeg_dpi": [300, 600]},
        "note": "Call host.renderIndex({index}). Map presentation is Host-owned (processed_preview).",
    }
