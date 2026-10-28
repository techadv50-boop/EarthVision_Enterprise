"""NDBI (Optical) plugin backend (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderIndex (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

INDEX_RECIPES = {
  "NDBI": {
    "formula": "(SWIR - NIR) / (SWIR + NIR)",
    "SENTINEL-2": "B11 + B08",
    "LANDSAT-8": "B6 + B5",
    "LANDSAT-9": "B6 + B5",
    "LANDSAT-7": "B5 + B4",
    "MODIS": "B06 + B02",
    "cmap": "ylorbr"
  }
}


def render(payload=None):
    payload = payload or {}
    index = str(payload.get("index") or "NDBI").upper()
    family = str(payload.get("family") or "").upper() or None
    block = INDEX_RECIPES.get(index) or INDEX_RECIPES["NDBI"]
    bands = block.get(family) if family else None
    return {
        "plugin_id": "optical_ndbi",
        "version": PACK_VERSION,
        "kind": "optical_ndbi",
        "message": "Normalized Difference Built-up Index for Sentinel-2 and Landsat 7/8/9.",
        "optical_only": True,
        "default_index": "NDBI",
        "indices": INDEX_RECIPES,
        "active_bands": bands,
        "export": {"geotiff": True, "map_jpeg_dpi": [300, 600]},
        "note": "Call host.renderIndex({index}). Map presentation is Host-owned (processed_preview).",
    }
