"""Map each SAT EYE toolbox tool to its professional EO / GIS standard."""

from __future__ import annotations

from typing import Any

from app.services.professional_viz import (
    INDEX_VIZ_RANGE,
    PROFESSIONAL_COMPOSITE_NOTES,
    tool_standard_summary,
)

# Image-processing tools → standard recipe
IMAGE_TOOL_STANDARDS: dict[str, dict[str, str]] = {
    "true_color": {
        "standard": PROFESSIONAL_COMPOSITE_NOTES["true_color"],
        "method": "l2a_optimized",
        "bands": "red,green,blue",
    },
    "false_color": {
        "standard": PROFESSIONAL_COMPOSITE_NOTES["false_color_infrared"],
        "method": "fcc_professional",
        "bands": "nir,red,green",
    },
    "unsupervised_classify": {
        "standard": "Ensemble ISODATA/k-means + spectral rules (3–8 LULC classes)",
        "method": "classification_ensemble",
        "bands": "blue,green,red,nir,swir",
    },
    "ndvi": {
        "standard": "Rouse/Tucker NDVI; display 0–0.8 RdYlGn (QGIS/ArcGIS)",
        "method": "index",
        "bands": "nir,red",
    },
    "ndwi": {
        "standard": "McFeeters 1996 NDWI; Blues ramp",
        "method": "index",
        "bands": "green,nir",
    },
    "ndbi": {
        "standard": "Zha et al. 2003 NDBI",
        "method": "index",
        "bands": "swir,nir",
    },
    "savi": {
        "standard": "Huete 1988 SAVI (L=0.5)",
        "method": "index",
        "bands": "nir,red",
    },
    "bsi": {
        "standard": "Bare Soil Index (Rikimaru)",
        "method": "index",
        "bands": "swir,red,nir,green",
    },
    "evi": {
        "standard": "Huete et al. 2002 / MODIS EVI",
        "method": "index",
        "bands": "nir,red,blue",
    },
    "ndmi": {
        "standard": "Gao 1996 NDMI (moisture)",
        "method": "index",
        "bands": "nir,swir",
    },
    "nbr": {
        "standard": "Key & Benson NBR (burn)",
        "method": "index",
        "bands": "nir,swir2",
    },
    "hist": {
        "standard": "Percentile stretch on true-color L2A Optimized base",
        "method": "stretch",
        "bands": "red,green,blue",
    },
    "brightness": {"standard": "Radiometric brightness adjust on L2A base", "method": "stretch", "bands": "rgb"},
    "contrast": {"standard": "Contrast enhance on L2A base", "method": "stretch", "bands": "rgb"},
    "gamma": {"standard": "Display gamma on L2A base", "method": "stretch", "bands": "rgb"},
    "sharpen": {"standard": "Edge-enhanced stretch (visual)", "method": "stretch", "bands": "rgb"},
    "denoise": {"standard": "Mild contrast denoise stretch", "method": "stretch", "bands": "rgb"},
    "cloud_mask": {
        "standard": "SCL / QA_PIXEL cloud mask visualization",
        "method": "detection",
        "bands": "scl,qa_pixel",
    },
    "mosaic": {"standard": "Multi-scene layer mosaic (client)", "method": "layer", "bands": "n/a"},
    "clip": {"standard": "OGC clip geometry", "method": "gis", "bands": "n/a"},
    "reproject": {"standard": "Display CRS Web Mercator EPSG:3857", "method": "display", "bands": "n/a"},
    "resample": {"standard": "Interactive grid ≤640px edge", "method": "display", "bands": "n/a"},
}

DETECTION_STANDARD = (
    "Spectral-index–guided classical EO detectors "
    "(NDVI/NDWI/NDBI/NBR/BSI + morphology) with confidence heatmap — "
    "professional cartographic overlay (legend, scale, north)"
)

CHANGE_STANDARD = (
    "Bi-temporal spectral-index differencing with significance threshold; "
    "index chosen by theme (NDVI forest, NDBI urban, NDWI water, NBR burn)"
)

TERRAIN_STANDARD = (
    "DEM-derived products (slope/aspect/hillshade/TRI/hydrology) with "
    "professional continuous colormaps and cartographic chrome"
)

GIS_STANDARD = "OGC-style vector geoprocessing (Shapely) with map overlay"

NAV_LAYER_MEASURE = "Map chrome / navigation / measurement — UI standard controls"


def catalog_tool_standards() -> dict[str, Any]:
    """Full tool→standard map for API consumers / QA."""
    summary = tool_standard_summary()
    return {
        "summary": summary,
        "index_viz_range": {k: list(v) for k, v in INDEX_VIZ_RANGE.items()},
        "composites": PROFESSIONAL_COMPOSITE_NOTES,
        "image_tools": IMAGE_TOOL_STANDARDS,
        "families": {
            "ai": DETECTION_STANDARD,
            "maritime": DETECTION_STANDARD,
            "aviation": DETECTION_STANDARD,
            "change": CHANGE_STANDARD,
            "terrain": TERRAIN_STANDARD,
            "gis": GIS_STANDARD,
            "navigation": NAV_LAYER_MEASURE,
            "layers": NAV_LAYER_MEASURE,
            "measure": NAV_LAYER_MEASURE,
        },
        "reliability": {
            "interactive_preview_max_px": 640,
            "request_timeout_s": 55,
            "overlay_format": "webp",
            "no_client_timeout_60000_raw": True,
        },
    }
