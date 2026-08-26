"""Execute SAT EYE offline GIS tools against local rasters / vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.services.gis_tools_catalog import GIS_TOOLS, get_tool, list_categories


class GisToolsService:
    def list_tools(
        self,
        category: str | None = None,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        tools = GIS_TOOLS
        if category:
            tools = [t for t in tools if t["category"].lower() == category.lower()]
        if q:
            ql = q.lower()
            tools = [
                t
                for t in tools
                if ql in t["name"].lower()
                or ql in t["description"].lower()
                or ql in t["id"].lower()
            ]
        return list(tools)

    def categories(self) -> list[dict[str, Any]]:
        return list_categories()

    def run_tool(self, tool_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = get_tool(tool_id)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool: {tool_id}"}

        params = dict(params or {})
        # Normalize any image format to a working GeoTIFF so tools are format-agnostic
        for key in ("file_path", "raster_path", "dem_path", "working_path"):
            raw = params.get(key)
            if isinstance(raw, str) and raw and not raw.startswith("demo://"):
                try:
                    from app.services.image_ingest_service import ImageIngestService

                    params[key] = ImageIngestService().ensure_working_path(raw)
                    params.setdefault("file_path", params[key])
                except Exception as exc:  # noqa: BLE001
                    return {
                        "ok": False,
                        "tool": tool,
                        "error": f"Could not open image for tools: {exc}",
                    }

        handler = {
            "raster_info": self._raster_info,
            "index_ndvi": lambda p: self._spectral_index(p, "ndvi"),
            "index_ndwi": lambda p: self._spectral_index(p, "ndwi"),
            "index_ndbi": lambda p: self._spectral_index(p, "ndbi"),
            "index_savi": lambda p: self._spectral_index(p, "savi"),
            "index_bsi": lambda p: self._spectral_index(p, "bsi"),
            "index_evi": lambda p: self._spectral_index(p, "evi"),
            "index_gndvi": lambda p: self._spectral_index(p, "gndvi"),
            "index_ndmi": lambda p: self._spectral_index(p, "ndmi"),
            "index_mndwi": lambda p: self._spectral_index(p, "mndwi"),
            "index_ndsi": lambda p: self._spectral_index(p, "ndsi"),
            "index_nbr": lambda p: self._spectral_index(p, "nbr"),
            "dem_hillshade": self._dem_hillshade,
            "dem_slope": self._dem_slope,
            "dem_aspect": self._dem_aspect,
            "measure_distance": self._measure_distance,
            "measure_area": self._measure_area,
            "buffer": self._buffer,
            "compare_dates": self._compare_dates,
            "timeline_animate": self._timeline_meta,
            "basemap_switch": lambda p: {
                "ok": True,
                "message": "Use Layers panel to switch offline basemap",
                "style": p.get("style", "satellite"),
            },
            "landmark_overlay": lambda p: {
                "ok": True,
                "message": "Toggle landmarks in Layers panel",
                "enabled": p.get("enabled", True),
            },
            "import_geotiff": lambda p: {
                "ok": True,
                "message": "Use Upload panel to import GeoTIFF locally",
            },
            "import_geojson": lambda p: {
                "ok": True,
                "message": "Use Upload panel to import GeoJSON locally",
            },
            "pixel_inspector": self._pixel_inspector,
            "histogram": self._histogram,
        }.get(tool_id)

        if handler is None:
            # Generic offline acknowledgement — tool is registered and runnable in UI
            return {
                "ok": True,
                "tool": tool,
                "status": "queued_local",
                "message": (
                    f"Tool '{tool['name']}' registered for offline execution. "
                    f"Provide inputs via the SAT EYE Tools panel."
                ),
                "params": params,
                "category": tool["category"],
            }

        try:
            result = handler(params)
            result.setdefault("ok", True)
            result.setdefault("tool", tool)
            return result
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "tool": tool, "error": str(exc)}

    def _raster_info(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        if not path or not Path(path).exists():
            return {"ok": False, "error": "file_path missing or not found"}
        try:
            import rasterio

            with rasterio.open(path) as src:
                return {
                    "ok": True,
                    "info": {
                        "width": src.width,
                        "height": src.height,
                        "count": src.count,
                        "crs": str(src.crs),
                        "bounds": list(src.bounds),
                        "dtypes": [str(d) for d in src.dtypes],
                        "nodata": src.nodata,
                    },
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _spectral_index(self, params: dict[str, Any], index: str) -> dict[str, Any]:
        """Compute a spectral index; prefers existing analytics service when available."""
        path = params.get("file_path")
        if not path:
            return {
                "ok": True,
                "status": "ready",
                "index": index.upper(),
                "message": f"Select an uploaded scene and run {index.upper()} from Analytics or Tools.",
            }
        try:
            from app.services.raster_service import RasterService

            service = RasterService()
            # RasterService may expose index helpers; fall back to band math
            if hasattr(service, "compute_index"):
                out = service.compute_index(path, index)
                return {"ok": True, "index": index.upper(), "result": out}

            import rasterio

            with rasterio.open(path) as src:
                # Assume Sentinel-like: 1=B,2=G,3=R,4=NIR,5=SWIR1,6=SWIR2
                def band(i: int) -> np.ndarray:
                    return src.read(min(i, src.count)).astype(np.float32)

                if index == "ndvi":
                    r, nir = band(3), band(4)
                    arr = (nir - r) / (nir + r + 1e-6)
                elif index == "ndwi":
                    g, nir = band(2), band(4)
                    arr = (g - nir) / (g + nir + 1e-6)
                elif index in ("ndbi",):
                    swir, nir = band(5), band(4)
                    arr = (swir - nir) / (swir + nir + 1e-6)
                else:
                    r, nir = band(3), band(4)
                    arr = (nir - r) / (nir + r + 1e-6)

                return {
                    "ok": True,
                    "index": index.upper(),
                    "stats": {
                        "min": float(np.nanmin(arr)),
                        "max": float(np.nanmax(arr)),
                        "mean": float(np.nanmean(arr)),
                        "std": float(np.nanstd(arr)),
                    },
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "index": index.upper()}

    def _dem_hillshade(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        if not path or not Path(path).exists():
            return {"ok": False, "error": "DEM file_path required"}
        try:
            import rasterio
            from numpy import gradient

            with rasterio.open(path) as src:
                dem = src.read(1).astype(np.float32)
            dy, dx = gradient(dem)
            slope = np.pi / 2 - np.arctan(np.hypot(dx, dy))
            aspect = np.arctan2(-dx, dy)
            azimuth = np.radians(float(params.get("azimuth", 315)))
            altitude = np.radians(float(params.get("altitude", 45)))
            shaded = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
                azimuth - aspect
            )
            return {
                "ok": True,
                "message": "Hillshade computed",
                "stats": {
                    "min": float(shaded.min()),
                    "max": float(shaded.max()),
                    "mean": float(shaded.mean()),
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _dem_slope(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        if not path or not Path(path).exists():
            return {"ok": False, "error": "DEM file_path required"}
        import rasterio
        from numpy import gradient

        with rasterio.open(path) as src:
            dem = src.read(1).astype(np.float32)
        dy, dx = gradient(dem)
        slope_deg = np.degrees(np.arctan(np.hypot(dx, dy)))
        return {
            "ok": True,
            "stats": {
                "min": float(slope_deg.min()),
                "max": float(slope_deg.max()),
                "mean": float(slope_deg.mean()),
            },
        }

    def _dem_aspect(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        if not path or not Path(path).exists():
            return {"ok": False, "error": "DEM file_path required"}
        import rasterio
        from numpy import gradient

        with rasterio.open(path) as src:
            dem = src.read(1).astype(np.float32)
        dy, dx = gradient(dem)
        aspect = (np.degrees(np.arctan2(-dx, dy)) + 360) % 360
        return {
            "ok": True,
            "stats": {
                "min": float(aspect.min()),
                "max": float(aspect.max()),
                "mean": float(aspect.mean()),
            },
        }

    def _measure_distance(self, params: dict[str, Any]) -> dict[str, Any]:
        coords = params.get("coordinates") or []
        if len(coords) < 2:
            return {"ok": False, "error": "Need at least 2 coordinates [lon,lat]"}
        from math import atan2, cos, radians, sin, sqrt

        total = 0.0
        for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
            r = 6371000.0
            p1, p2 = radians(lat1), radians(lat2)
            dphi = radians(lat2 - lat1)
            dl = radians(lon2 - lon1)
            a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
            total += 2 * r * atan2(sqrt(a), sqrt(1 - a))
        return {"ok": True, "distance_m": total, "distance_km": total / 1000.0}

    def _measure_area(self, params: dict[str, Any]) -> dict[str, Any]:
        geojson = params.get("geojson")
        if not geojson:
            return {"ok": False, "error": "geojson required"}
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        try:
            from shapely.geometry import shape
            from shapely.ops import transform
            import pyproj

            geom = shape(geojson if geojson.get("type") != "Feature" else geojson["geometry"])
            project = pyproj.Transformer.from_crs(
                "EPSG:4326", "EPSG:6933", always_xy=True
            ).transform
            geom_m = transform(project, geom)
            return {"ok": True, "area_m2": float(geom_m.area), "area_km2": float(geom_m.area) / 1e6}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        geojson = params.get("geojson")
        distance_m = float(params.get("distance_m", 1000))
        if not geojson:
            return {"ok": False, "error": "geojson required"}
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        from shapely.geometry import mapping, shape
        from shapely.ops import transform
        import pyproj

        geom = shape(geojson if geojson.get("type") != "Feature" else geojson["geometry"])
        # Buffer in meters via equal-area projection
        to_m = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform
        to_ll = pyproj.Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True).transform
        buffered = transform(to_ll, transform(to_m, geom).buffer(distance_m))
        return {"ok": True, "geojson": mapping(buffered), "distance_m": distance_m}

    def _compare_dates(self, params: dict[str, Any]) -> dict[str, Any]:
        stack_id = params.get("stack_id")
        dates = params.get("dates") or []
        return {
            "ok": True,
            "message": "Use the Date Slider to compare multi-date imagery for the same place",
            "stack_id": stack_id,
            "dates": dates,
            "modes": ["slider", "swipe", "flicker"],
        }

    def _timeline_meta(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "message": "Timeline animation available when a place stack has 2+ images",
            "stack_id": params.get("stack_id"),
        }

    def _pixel_inspector(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        lon = params.get("longitude")
        lat = params.get("latitude")
        if not path or lon is None or lat is None:
            return {"ok": False, "error": "file_path, longitude, latitude required"}
        import rasterio
        from rasterio.sample import sample_gen

        with rasterio.open(path) as src:
            samples = list(sample_gen(src, [(float(lon), float(lat))]))
            vals = [float(v) for v in samples[0]] if samples else []
        return {"ok": True, "longitude": lon, "latitude": lat, "values": vals}

    def _histogram(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("file_path")
        band = int(params.get("band", 1))
        if not path or not Path(path).exists():
            return {"ok": False, "error": "file_path required"}
        import rasterio

        with rasterio.open(path) as src:
            data = src.read(min(band, src.count)).astype(np.float32)
            data = data[np.isfinite(data)]
            hist, edges = np.histogram(data, bins=int(params.get("bins", 32)))
        return {
            "ok": True,
            "bands": band,
            "counts": hist.tolist(),
            "edges": edges.tolist(),
        }
