"""Optical false-color composite plugin (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderComposite (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

COMPOSITE_PRESETS = {
  "false_color_infrared": {
    "label": "False Color Infrared (NIR-R-G)",
    "SENTINEL-2": {
      "codes": "B08-B04-B03",
      "formula": "R=NIR(B08), G=Red(B04), B=Green(B03)"
    },
    "LANDSAT-8": {
      "codes": "B5-B4-B3",
      "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"
    },
    "LANDSAT-9": {
      "codes": "B5-B4-B3",
      "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"
    },
    "LANDSAT-7": {
      "codes": "B4-B3-B2",
      "formula": "R=NIR(B4), G=Red(B3), B=Green(B2)"
    },
    "MODIS": {
      "codes": "B02-B01-B04",
      "formula": "R=NIR(B02), G=Red(B01), B=Green(B04)"
    }
  },
  "false_color_agriculture": {
    "label": "Agriculture (SWIR1-NIR-Blue)",
    "SENTINEL-2": {
      "codes": "B11-B08-B02",
      "formula": "R=SWIR1(B11), G=NIR(B08), B=Blue(B02)"
    },
    "LANDSAT-8": {
      "codes": "B6-B5-B2",
      "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"
    },
    "LANDSAT-9": {
      "codes": "B6-B5-B2",
      "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"
    },
    "LANDSAT-7": {
      "codes": "B5-B4-B1",
      "formula": "R=SWIR1(B5), G=NIR(B4), B=Blue(B1)"
    },
    "MODIS": {
      "codes": "B06-B02-B03",
      "formula": "R=SWIR1(B06), G=NIR(B02), B=Blue(B03)"
    }
  },
  "false_color_urban": {
    "label": "Urban / Buildup (SWIR2-SWIR1-Red)",
    "SENTINEL-2": {
      "codes": "B12-B11-B04",
      "formula": "R=SWIR2(B12), G=SWIR1(B11), B=Red(B04)"
    },
    "LANDSAT-8": {
      "codes": "B7-B6-B4",
      "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"
    },
    "LANDSAT-9": {
      "codes": "B7-B6-B4",
      "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"
    },
    "LANDSAT-7": {
      "codes": "B7-B5-B3",
      "formula": "R=SWIR2(B7), G=SWIR1(B5), B=Red(B3)"
    },
    "MODIS": {
      "codes": "B07-B06-B01",
      "formula": "R=SWIR2(B07), G=SWIR1(B06), B=Red(B01)"
    }
  },
  "swir_composite": {
    "label": "Shortwave Infrared (SWIR2-NIR-Red)",
    "SENTINEL-2": {
      "codes": "B12-B08-B04",
      "formula": "R=SWIR2(B12), G=NIR(B08), B=Red(B04)"
    },
    "LANDSAT-8": {
      "codes": "B7-B5-B4",
      "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"
    },
    "LANDSAT-9": {
      "codes": "B7-B5-B4",
      "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"
    },
    "LANDSAT-7": {
      "codes": "B7-B4-B3",
      "formula": "R=SWIR2(B7), G=NIR(B4), B=Red(B3)"
    },
    "MODIS": {
      "codes": "B07-B02-B01",
      "formula": "R=SWIR2(B07), G=NIR(B02), B=Red(B01)"
    }
  }
}


def render(payload=None):
    payload = payload or {}
    preset = str(payload.get("preset") or "false_color_infrared")
    family = str(payload.get("family") or "").upper() or None
    block = COMPOSITE_PRESETS.get(preset) or COMPOSITE_PRESETS["false_color_infrared"]
    recipe = block.get(family) if family else None
    return {
        "plugin_id": "optical_false_color",
        "version": PACK_VERSION,
        "kind": "optical_false_color",
        "message": "False-color optical composites for Landsat 7/8/9 and Sentinel-2.",
        "optical_only": True,
        "default_preset": "false_color_infrared",
        "presets": COMPOSITE_PRESETS,
        "active_recipe": recipe,
        "export": {"geotiff": True, "map_jpeg_dpi": [300, 600]},
        "note": "Call host.renderComposite({preset}). Map presentation is Host-owned (processed_preview).",
    }
