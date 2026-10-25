"""Frozen Host geospatial capability profile (ENVI / ERDAS / ArcGIS-class baseline).

Plugins must NOT vendor competing GDAL/numpy/opencv stacks. They declare
``requires_host_capabilities`` in tool-meta and call Host SDK / Host services.
This module is the single source of truth for what the Host Shell guarantees.
"""

from __future__ import annotations

from typing import Any

# Bump ONLY when adding a new frozen capability family (never for one plugin).
HOST_GEO_PROFILE_ID = "sateye-rs-2026.10"
HOST_GEO_PROFILE_VERSION = "1.0.0"

# Stable capability tokens — append-only. Do not rename or remove.
HOST_CAPABILITIES: dict[str, dict[str, Any]] = {
    # --- Core numeric / I/O (always) ---
    "host.math.numpy": {
        "family": "math",
        "summary": "Array math for band algebra and rasters",
        "libs": ["numpy"],
    },
    "host.math.scipy": {
        "family": "math",
        "summary": "Scientific filters, ND-image, signal helpers",
        "libs": ["scipy"],
    },
    "host.raster.pillow": {
        "family": "raster",
        "summary": "PNG overlay encode, light sharpen/denoise",
        "libs": ["pillow"],
    },
    "host.raster.rasterio": {
        "family": "raster",
        "summary": "COG/GeoTIFF read, warp, mask, write",
        "libs": ["rasterio", "gdal"],
    },
    "host.raster.geotiff_export": {
        "family": "raster",
        "summary": "Host GeoTIFF download for presented layers",
        "libs": ["rasterio", "numpy", "pillow"],
    },
    "host.vision.skimage": {
        "family": "vision",
        "summary": "Morphology, edge, segmentation primitives",
        "libs": ["scikit-image"],
    },
    "host.vision.opencv": {
        "family": "vision",
        "summary": "Headless CV filters / contours for RS products",
        "libs": ["opencv-python-headless"],
    },
    "host.ml.sklearn": {
        "family": "ml",
        "summary": "Classical ML (RF/SVM) training demos and classify helpers",
        "libs": ["scikit-learn"],
    },
    "host.cube.xarray": {
        "family": "cube",
        "summary": "Multi-band / multi-date array cubes",
        "libs": ["xarray", "rioxarray"],
    },
    # --- Vector ---
    "host.vector.shapely": {
        "family": "vector",
        "summary": "Geometry ops (buffer, intersect, union, …)",
        "libs": ["shapely"],
    },
    "host.vector.pyproj": {
        "family": "vector",
        "summary": "CRS transforms / metric projections",
        "libs": ["pyproj"],
    },
    "host.vector.shapefile": {
        "family": "vector",
        "summary": "ESRI Shapefile zip import/export",
        "libs": ["pyshp"],
    },
    "host.vector.geopandas": {
        "family": "vector",
        "summary": "Tabular vector joins, GeoDataFrame IO",
        "libs": ["geopandas", "pyogrio"],
    },
    # --- Map presentation (Host Shell FE) ---
    "host.map.prefer_scene_tiles": {
        "family": "map",
        "summary": "Sharp XYZ presentation for natural/visual products",
        "libs": [],
    },
    "host.map.processed_preview": {
        "family": "map",
        "summary": "Soft PNG preview + swipe compare",
        "libs": [],
    },
    "host.map.vector_geojson": {
        "family": "map",
        "summary": "Vector GeoJSON on map over scene tiles",
        "libs": [],
    },
    # --- Domain analytics already on Host ---
    "host.analytics.composites": {
        "family": "analytics",
        "summary": "True/false color and thematic RGB composites",
        "libs": ["numpy", "rasterio", "pillow"],
    },
    "host.analytics.indices": {
        "family": "analytics",
        "summary": "Spectral indices (NDVI, NDWI, NBR, …)",
        "libs": ["numpy", "rasterio"],
    },
    "host.analytics.change": {
        "family": "analytics",
        "summary": "Bi-temporal index / change products",
        "libs": ["numpy", "rasterio"],
    },
    "host.analytics.classify": {
        "family": "analytics",
        "summary": "Land-cover classify overlays",
        "libs": ["numpy", "scikit-learn", "pillow"],
    },
    "host.analytics.detection": {
        "family": "analytics",
        "summary": "Object/spectral detection + GeoJSON hits",
        "libs": ["numpy", "pillow"],
    },
    "host.analytics.terrain": {
        "family": "analytics",
        "summary": "DEM derivatives (slope, hillshade, viewshed, …)",
        "libs": ["numpy"],
    },
    "host.analytics.gis": {
        "family": "analytics",
        "summary": "Measure, buffer, overlay GIS ops",
        "libs": ["shapely", "pyproj", "pyshp"],
    },
}

# ENVI / ERDAS / ArcGIS-class tool families this Host profile is built to support.
HOST_TOOL_FAMILIES: dict[str, list[str]] = {
    "radiometry_display": [
        "host.math.numpy",
        "host.raster.pillow",
        "host.raster.rasterio",
        "host.map.processed_preview",
    ],
    "band_math_indices": [
        "host.math.numpy",
        "host.math.scipy",
        "host.analytics.indices",
        "host.analytics.composites",
        "host.map.processed_preview",
        "host.map.prefer_scene_tiles",
    ],
    "filtering_morphology": [
        "host.math.scipy",
        "host.vision.skimage",
        "host.vision.opencv",
        "host.map.processed_preview",
    ],
    "classification": [
        "host.ml.sklearn",
        "host.analytics.classify",
        "host.map.processed_preview",
    ],
    "change_detection": [
        "host.analytics.change",
        "host.cube.xarray",
        "host.map.processed_preview",
    ],
    "object_detection": [
        "host.analytics.detection",
        "host.vision.opencv",
        "host.map.vector_geojson",
        "host.map.processed_preview",
    ],
    "terrain_dem": [
        "host.analytics.terrain",
        "host.map.processed_preview",
        "host.map.vector_geojson",
    ],
    "vector_gis": [
        "host.vector.shapely",
        "host.vector.pyproj",
        "host.vector.shapefile",
        "host.vector.geopandas",
        "host.map.vector_geojson",
        "host.analytics.gis",
    ],
    "raster_io_export": [
        "host.raster.rasterio",
        "host.raster.geotiff_export",
        "host.cube.xarray",
    ],
}


_LIB_IMPORT_NAME = {
    "pillow": "PIL",
    "scikit-image": "skimage",
    "scikit-learn": "sklearn",
    "opencv-python-headless": "cv2",
    "gdal": "osgeo.gdal",
}


def _probe_lib(name: str) -> bool:
    mod = _LIB_IMPORT_NAME.get(name, name)
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def probe_libraries() -> dict[str, bool]:
    libs = sorted(
        {
            lib
            for meta in HOST_CAPABILITIES.values()
            for lib in (meta.get("libs") or [])
            if lib and lib != "gdal"
        }
        | {"gdal"}
    )
    return {lib: _probe_lib(lib) for lib in libs}


def capability_status() -> dict[str, dict[str, Any]]:
    lib_ok = probe_libraries()
    out: dict[str, dict[str, Any]] = {}
    for cap_id, meta in HOST_CAPABILITIES.items():
        needed = list(meta.get("libs") or [])
        missing = [lib for lib in needed if not lib_ok.get(lib, False)]
        # gdal often available only via rasterio; treat rasterio success as enough for gdal token
        if "gdal" in missing and lib_ok.get("rasterio"):
            missing = [m for m in missing if m != "gdal"]
        out[cap_id] = {
            "summary": meta["summary"],
            "family": meta["family"],
            "libs": needed,
            "ready": len(missing) == 0,
            "missing_libs": missing,
        }
    return out


def host_capabilities_document() -> dict[str, Any]:
    """Public document for Admin health + host.getCapabilities."""
    caps = capability_status()
    ready = sorted(cid for cid, st in caps.items() if st["ready"])
    not_ready = sorted(cid for cid, st in caps.items() if not st["ready"])
    return {
        "profile_id": HOST_GEO_PROFILE_ID,
        "profile_version": HOST_GEO_PROFILE_VERSION,
        "approach": "host_shared_stack",
        "notes": (
            "Plugins stay thin (stdlib + crypto in worker). "
            "Raster/vector compute uses this Host-shared stack. "
            "Do not vendor GDAL/numpy/opencv inside plugin zips."
        ),
        "map_presentation_modes": [
            "prefer_scene_tiles",
            "processed_preview",
            "vector_geojson",
        ],
        "tool_families": HOST_TOOL_FAMILIES,
        "capabilities": caps,
        "ready": ready,
        "not_ready": not_ready,
        "all_ready": len(not_ready) == 0,
    }


def assert_capabilities(required: list[str] | None) -> list[str]:
    """Return missing capability ids (empty if ok)."""
    if not required:
        return []
    status = capability_status()
    missing: list[str] = []
    for cid in required:
        if cid not in status:
            missing.append(cid)
        elif not status[cid]["ready"]:
            missing.append(cid)
    return missing
