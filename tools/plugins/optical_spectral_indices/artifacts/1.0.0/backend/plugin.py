"""Spectral Indices (Optical) plugin backend (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderIndex (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

INDEX_RECIPES = {
  "SAVI": {
    "formula": "((NIR - RED) * (1 + L)) / (NIR + RED + L)",
    "SENTINEL-2": "B08 + B04",
    "LANDSAT-8": "B5 + B4",
    "LANDSAT-9": "B5 + B4",
    "LANDSAT-7": "B4 + B3",
    "MODIS": "B02 + B01",
    "cmap": "rdylgn"
  },
  "EVI": {
    "formula": "2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)",
    "SENTINEL-2": "B08 + B04 + B02",
    "LANDSAT-8": "B5 + B4 + B2",
    "LANDSAT-9": "B5 + B4 + B2",
    "LANDSAT-7": "B4 + B3 + B1",
    "MODIS": "B02 + B01 + B03",
    "cmap": "rdylgn"
  },
  "NDMI": {
    "formula": "(NIR - SWIR) / (NIR + SWIR)",
    "SENTINEL-2": "B08 + B11",
    "LANDSAT-8": "B5 + B6",
    "LANDSAT-9": "B5 + B6",
    "LANDSAT-7": "B4 + B5",
    "MODIS": "B02 + B06",
    "cmap": "brbg"
  },
  "NBR": {
    "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
    "SENTINEL-2": "B08 + B12",
    "LANDSAT-8": "B5 + B7",
    "LANDSAT-9": "B5 + B7",
    "LANDSAT-7": "B4 + B7",
    "MODIS": "B02 + B07",
    "cmap": "rdylgn"
  },
  "BSI": {
    "formula": "((SWIR + RED) - (NIR + GREEN)) / ((SWIR + RED) + (NIR + GREEN))",
    "SENTINEL-2": "B11 + B04 + B08 + B03",
    "LANDSAT-8": "B6 + B4 + B5 + B3",
    "LANDSAT-9": "B6 + B4 + B5 + B3",
    "LANDSAT-7": "B5 + B3 + B4 + B2",
    "MODIS": "B06 + B01 + B02 + B04",
    "cmap": "soil"
  }
}


def render(payload=None):
    payload = payload or {}
    index = str(payload.get("index") or "SAVI").upper()
    family = str(payload.get("family") or "").upper() or None
    block = INDEX_RECIPES.get(index) or INDEX_RECIPES["SAVI"]
    bands = block.get(family) if family else None
    return {
        "plugin_id": "optical_spectral_indices",
        "version": PACK_VERSION,
        "kind": "optical_spectral_indices",
        "message": "Additional optical indices (SAVI, EVI, NDMI, NBR, BSI) for Landsat 7/8/9 and Sentinel-2.",
        "optical_only": True,
        "default_index": "SAVI",
        "indices": INDEX_RECIPES,
        "active_bands": bands,
        "export": {"geotiff": True, "map_jpeg_dpi": [300, 600]},
        "note": "Call host.renderIndex({index}). Map presentation is Host-owned (processed_preview).",
    }
