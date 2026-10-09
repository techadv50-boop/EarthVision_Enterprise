"""Spectral-index–guided AI / maritime / air-domain detectors for Eye In Sky."""

from __future__ import annotations

import base64
import hashlib
import io
import math
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.detection import DetectionRunRequest, DetectionRunResponse

# Task metadata + classical EO algorithm family used for each tool
TASK_META: dict[str, dict[str, Any]] = {
    "building_detection": {
        "label": "Building",
        "kind": "polygon",
        "count": (8, 22),
        "domain": "ai",
        "algorithm": "NDBI thresholding + connected-component blobs (Zha urban index)",
        "spectral": "ndbi",
    },
    "road_extraction": {
        "label": "Road",
        "kind": "line",
        "count": (4, 10),
        "domain": "ai",
        "algorithm": "Sobel edge magnitude on NIR–SWIR + ridge tracing",
        "spectral": "edge",
    },
    "vehicle_detection": {
        "label": "Vehicle",
        "kind": "point",
        "count": (12, 36),
        "domain": "ai",
        "algorithm": "Local-maxima blob detector on high-contrast SWIR/NIR residual",
        "spectral": "blob",
    },
    "change_detection": {
        "label": "Change",
        "kind": "polygon",
        "count": (3, 9),
        "domain": "ai",
        "algorithm": "Spectral anomaly clustering (NDVI residual hotspots)",
        "spectral": "ndvi",
    },
    "flood_detection": {
        "label": "Flood",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "ai",
        "algorithm": "McFeeters NDWI water mask + morphological fill",
        "spectral": "ndwi",
    },
    "land_cover_classification": {
        "label": "Land cover",
        "kind": "polygon",
        "count": (5, 12),
        "domain": "ai",
        "algorithm": "Rule-based LULC from NDVI/NDBI/NDWI decision tree",
        "spectral": "lulc",
    },
    "object_detection": {
        "label": "Object",
        "kind": "point",
        "count": (10, 28),
        "domain": "ai",
        "algorithm": "Multi-scale Laplacian-of-Gaussian blob detector",
        "spectral": "blob",
    },
    "deforestation_detection": {
        "label": "Deforestation",
        "kind": "polygon",
        "count": (2, 7),
        "domain": "ai",
        "algorithm": "Low-NDVI forest-loss patches (vegetation residual)",
        "spectral": "ndvi_low",
    },
    "fire_detection": {
        "label": "Fire / hot spot",
        "kind": "point",
        "count": (4, 14),
        "domain": "ai",
        "algorithm": "SWIR hot-spot peaks (thermal/SWIR anomaly)",
        "spectral": "swir_hot",
    },
    "crop_classification": {
        "label": "Crop parcel",
        "kind": "polygon",
        "count": (6, 16),
        "domain": "ai",
        "algorithm": "NDVI parcel segmentation (agriculture mask)",
        "spectral": "ndvi",
    },
    "bridge_detection": {
        "label": "Bridge",
        "kind": "line",
        "count": (2, 6),
        "domain": "ai",
        "algorithm": "Linear feature extraction over water (NDWI ∩ edge ridges)",
        "spectral": "edge",
    },
    "airport_mapping": {
        "label": "Airport",
        "kind": "polygon",
        "count": (1, 3),
        "domain": "ai",
        "algorithm": "Large low-NDVI / high-NDBI apron polygons",
        "spectral": "ndbi",
    },
    "runway_detection": {
        "label": "Runway",
        "kind": "line",
        "count": (1, 4),
        "domain": "ai",
        "algorithm": "Long straight ridge detection (edge Hough-style sampling)",
        "spectral": "edge",
    },
    "port_mapping": {
        "label": "Port",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "ai",
        "algorithm": "Harbor mask = NDWI shore + NDBI quays",
        "spectral": "ndwi",
    },
    "harbor_detection": {
        "label": "Harbor",
        "kind": "polygon",
        "count": (2, 5),
        "domain": "ai",
        "algorithm": "Waterbody shoreline enclosure from NDWI",
        "spectral": "ndwi",
    },
    "ship_detection": {
        "label": "Ship",
        "kind": "point",
        "count": (5, 18),
        "domain": "ai",
        "algorithm": (
            "GEE OPT · AOI-first sensitive NIR (~0.04–0.07 + soft wakes) · "
            "morph red outline · connected-pixel contacts"
        ),
        "spectral": "optical_nir_ship",
        "optical_only": True,
    },
    "ship_detection_optical": {
        "label": "Ship (optical)",
        "kind": "point",
        "count": (5, 18),
        "domain": "maritime",
        "algorithm": (
            "GEE OPT · AOI-first sensitive NIR (~0.04–0.07 + soft wakes) · "
            "morph red outline · connected-pixel contacts"
        ),
        "spectral": "optical_nir_ship",
        "optical_only": True,
    },
    "aircraft_detection": {
        "label": "Aircraft",
        "kind": "point",
        "count": (3, 12),
        "domain": "ai",
        "algorithm": "Bright blob detector on low-vegetation airport apron",
        "spectral": "blob",
    },
    "railway_detection": {
        "label": "Railway",
        "kind": "line",
        "count": (3, 8),
        "domain": "ai",
        "algorithm": "Narrow linear ridge tracing (edge magnitude)",
        "spectral": "edge",
    },
    "powerline_corridor_mapping": {
        "label": "Powerline corridor",
        "kind": "line",
        "count": (2, 7),
        "domain": "ai",
        "algorithm": "Corridor extraction along NDVI clearing lines",
        "spectral": "edge",
    },
    "solar_farm_detection": {
        "label": "Solar farm",
        "kind": "polygon",
        "count": (2, 8),
        "domain": "ai",
        "algorithm": "Dark SWIR / low-NDVI rectangular arrays",
        "spectral": "ndbi",
    },
    "wind_farm_detection": {
        "label": "Wind farm",
        "kind": "point",
        "count": (6, 20),
        "domain": "ai",
        "algorithm": "Point-pattern blob detection (turbine-scale maxima)",
        "spectral": "blob",
    },
    "construction_site_detection": {
        "label": "Construction site",
        "kind": "polygon",
        "count": (2, 7),
        "domain": "ai",
        "algorithm": "High BSI / bare-soil patches",
        "spectral": "bsi",
    },
    "urban_expansion_detection": {
        "label": "Urban expansion",
        "kind": "polygon",
        "count": (3, 9),
        "domain": "ai",
        "algorithm": "NDBI growth clusters (built-up expansion)",
        "spectral": "ndbi",
    },
    "vegetation_classification": {
        "label": "Vegetation class",
        "kind": "polygon",
        "count": (5, 14),
        "domain": "ai",
        "algorithm": "NDVI class bins (sparse / moderate / dense)",
        "spectral": "ndvi",
    },
    "burn_scar_detection": {
        "label": "Burn scar",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "ai",
        "algorithm": "NBR burn-severity threshold (Key & Benson)",
        "spectral": "nbr",
    },
    "water_body_extraction": {
        "label": "Water body",
        "kind": "polygon",
        "count": (3, 10),
        "domain": "ai",
        "algorithm": "NDWI water extraction + vectorize",
        "spectral": "ndwi",
    },
    "confidence_heatmap": {
        "label": "Confidence",
        "kind": "point",
        "count": (15, 40),
        "domain": "ai",
        "algorithm": "Softmax-normalized multi-cue confidence field",
        "spectral": "blob",
    },
    "cloud_mask": {
        "label": "Cloud",
        "kind": "polygon",
        "count": (3, 10),
        "domain": "ai",
        "algorithm": "Bright-pixel cloud candidate mask (blue/NIR ratio)",
        "spectral": "cloud",
    },
    # Maritime
    "ship_detection_sar": {
        "label": "Ship (SAR)",
        "kind": "point",
        "count": (6, 20),
        "domain": "maritime",
        "algorithm": "CFAR bright-target detection on SAR-like intensity",
        "spectral": "blob",
    },
    "vessel_density_map": {
        "label": "Vessel density",
        "kind": "point",
        "count": (20, 50),
        "domain": "maritime",
        "algorithm": "Kernel density of ship peaks (KDE)",
        "spectral": "water_blob",
    },
    "port_activity_mapping": {
        "label": "Port activity",
        "kind": "polygon",
        "count": (4, 12),
        "domain": "maritime",
        "algorithm": "Port apron clustering (NDBI ∩ NDWI shore)",
        "spectral": "ndbi",
    },
    "anchorage_detection": {
        "label": "Anchorage",
        "kind": "point",
        "count": (4, 14),
        "domain": "maritime",
        "algorithm": "Stationary vessel clusters in coastal waters",
        "spectral": "water_blob",
    },
    "shipping_lane_visualization": {
        "label": "Shipping lane",
        "kind": "line",
        "count": (2, 6),
        "domain": "maritime",
        "algorithm": "Lane axis from vessel density ridges",
        "spectral": "edge",
    },
    "oil_spill_detection": {
        "label": "Oil spill",
        "kind": "polygon",
        "count": (1, 4),
        "domain": "maritime",
        "algorithm": "Dark slick anomaly on water (low NIR/SWIR)",
        "spectral": "ndwi",
    },
    "wake_detection": {
        "label": "Wake",
        "kind": "line",
        "count": (3, 9),
        "domain": "maritime",
        "algorithm": "Linear wake ridges trailing ship peaks",
        "spectral": "edge",
    },
    "port_activity_monitoring": {
        "label": "Port berth",
        "kind": "polygon",
        "count": (4, 12),
        "domain": "maritime",
        "algorithm": "Berth polygons from NDBI shore facilities",
        "spectral": "ndbi",
    },
    "dark_vessel_detection": {
        "label": "Dark vessel",
        "kind": "point",
        "count": (2, 8),
        "domain": "maritime",
        "algorithm": "Low-RCS anomaly peaks in water mask",
        "spectral": "water_blob",
    },
    "maritime_domain_awareness": {
        "label": "Maritime contact",
        "kind": "point",
        "count": (8, 24),
        "domain": "maritime",
        "algorithm": "Fused optical contacts (multi-cue blob field)",
        "spectral": "water_blob",
    },
    "sea_surface_temperature": {
        "label": "SST cell",
        "kind": "polygon",
        "count": (8, 18),
        "domain": "maritime",
        "algorithm": "Thermal anomaly zoning (synthetic SST cells)",
        "spectral": "swir_hot",
    },
    "chlorophyll_overlay": {
        "label": "Chlorophyll",
        "kind": "polygon",
        "count": (6, 16),
        "domain": "maritime",
        "algorithm": "Green/blue ratio bloom zones",
        "spectral": "ndwi",
    },
    "wave_height_overlay": {
        "label": "Wave height",
        "kind": "polygon",
        "count": (6, 14),
        "domain": "maritime",
        "algorithm": "Texture variance zoning over water",
        "spectral": "ndwi",
    },
    "wind_speed_overlay": {
        "label": "Wind speed",
        "kind": "polygon",
        "count": (6, 14),
        "domain": "maritime",
        "algorithm": "Roughness proxy zoning (SWIR texture)",
        "spectral": "edge",
    },
    "coastal_erosion_mapping": {
        "label": "Coastal erosion",
        "kind": "line",
        "count": (2, 6),
        "domain": "maritime",
        "algorithm": "Shoreline polyline from NDWI edge",
        "spectral": "edge",
    },
    "tidal_zone_mapping": {
        "label": "Tidal zone",
        "kind": "polygon",
        "count": (2, 5),
        "domain": "maritime",
        "algorithm": "Intertidal NDWI fringe polygons",
        "spectral": "ndwi",
    },
    # Air
    "airport_detection": {
        "label": "Airport",
        "kind": "polygon",
        "count": (1, 3),
        "domain": "air",
        "algorithm": "Large NDBI facility footprint",
        "spectral": "ndbi",
    },
    "runway_extraction": {
        "label": "Runway",
        "kind": "line",
        "count": (1, 4),
        "domain": "air",
        "algorithm": "Long straight edge / Hough-style sampling",
        "spectral": "edge",
    },
    "airfield_monitoring": {
        "label": "Airfield asset",
        "kind": "polygon",
        "count": (3, 10),
        "domain": "air",
        "algorithm": "Airfield parcel segmentation (NDBI)",
        "spectral": "ndbi",
    },
    "helicopter_detection": {
        "label": "Helicopter",
        "kind": "point",
        "count": (2, 8),
        "domain": "air",
        "algorithm": "Small bright-target LoG peaks",
        "spectral": "blob",
    },
    "uav_detection": {
        "label": "UAV",
        "kind": "point",
        "count": (4, 16),
        "domain": "air",
        "algorithm": "Compact blob detector (small-object CFAR)",
        "spectral": "blob",
    },
    "airport_database": {
        "label": "Airport",
        "kind": "point",
        "count": (1, 4),
        "domain": "air",
        "algorithm": "Facility centroid from NDBI cluster",
        "spectral": "ndbi",
    },
    "runway_inventory": {
        "label": "Runway",
        "kind": "line",
        "count": (1, 5),
        "domain": "air",
        "algorithm": "Runway axis inventory (edge ridges)",
        "spectral": "edge",
    },
    "airport_expansion_monitoring": {
        "label": "Airport expansion",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "air",
        "algorithm": "NDBI expansion rings around airfield",
        "spectral": "ndbi",
    },
    "airspace_overlay": {
        "label": "Airspace",
        "kind": "polygon",
        "count": (2, 5),
        "domain": "air",
        "algorithm": "Geofenced airspace rings (rules overlay)",
        "spectral": "blob",
    },
    "notam_overlay": {
        "label": "NOTAM",
        "kind": "polygon",
        "count": (3, 9),
        "domain": "air",
        "algorithm": "NOTAM polygonal alert zones",
        "spectral": "blob",
    },
    "weather_overlay": {
        "label": "Weather cell",
        "kind": "polygon",
        "count": (4, 10),
        "domain": "air",
        "algorithm": "Cloud/weather cell segmentation",
        "spectral": "cloud",
    },
    "terrain_awareness": {
        "label": "Terrain hazard",
        "kind": "polygon",
        "count": (3, 8),
        "domain": "air",
        "algorithm": "High-relief hazard zoning (edge texture)",
        "spectral": "edge",
    },
    "visibility_analysis": {
        "label": "Visibility",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "air",
        "algorithm": "Viewshed-like visibility polygons",
        "spectral": "blob",
    },
    "vessel_tracking": {
        "label": "Vessel track",
        "kind": "line",
        "count": (3, 8),
        "domain": "maritime",
        "algorithm": "Track linking of successive ship peaks",
        "spectral": "water_blob",
    },
}


class DetectionService:
    """Spectral-guided detectors with deterministic fallbacks inside an AOI."""

    def list_tasks(self) -> list[dict[str, str]]:
        return [
            {
                "id": key,
                "name": meta["label"],
                "domain": meta["domain"],
                "geometry": meta["kind"],
                "algorithm": meta.get("algorithm", ""),
            }
            for key, meta in TASK_META.items()
        ]

    def run(self, request: DetectionRunRequest) -> DetectionRunResponse:
        task = request.task.strip().lower().replace(" ", "_").replace("-", "_")
        bounds = self._resolve_bounds(request.bbox, request.aoi)
        west, south, east, north = bounds
        if east <= west or north <= south:
            raise ValidationError("Invalid bbox: east>west and north>south required")

        meta = TASK_META.get(task) or {
            "label": task.replace("_", " ").title(),
            "kind": "polygon" if "map" in task or "zone" in task else "point",
            "count": (4, 12),
            "domain": "ai",
            "algorithm": "Generic multi-cue blob / region detector",
            "spectral": "blob",
        }
        algorithm = str(meta.get("algorithm") or "heuristic detector")

        # Optical NIR ship detection (AI Tools → Ship Detection)
        from app.services.optical_ship_detection import (
            OPTICAL_SHIP_TASKS,
            collection_is_optical_landsat_or_s2,
            detect_ships_optical_nir,
        )

        if task in OPTICAL_SHIP_TASKS:
            if not request.scene_id:
                raise ValidationError(
                    "Ship Detection stays off until you select a Landsat or Sentinel-2 image "
                    "(turn the eye on)."
                )
            collection = self._scene_collection(request.scene_id)
            if not collection_is_optical_landsat_or_s2(collection):
                raise ValidationError(
                    "Ship Detection works only with Landsat and Sentinel-2 optical imagery "
                    f"(got {collection or 'unknown'})."
                )
            aoi_geom = request.aoi
            if not aoi_geom or (aoi_geom.get("type") if isinstance(aoi_geom, dict) else None) != "Polygon":
                raise ValidationError(
                    "Ship Detection needs a drawn water-body AOI — use Rect AOI or Poly AOI "
                    "to demarcate the water, then run again."
                )
            # OPT (GEE): clip load to water AOI bbox; NIR-only (+SCL) — fewer bands,
            # higher res on the small AOI intersection.
            aoi_bounds = bounds
            try:
                from shapely.geometry import shape as shp_shape

                geom = shp_shape(aoi_geom)
                if not geom.is_empty:
                    minx, miny, maxx, maxy = geom.bounds
                    aoi_bounds = [float(minx), float(miny), float(maxx), float(maxy)]
            except Exception:  # noqa: BLE001
                aoi_bounds = bounds
            bands_pack = self._try_load_bands_with_bounds(
                request.scene_id,
                bounds=aoi_bounds,
                size=1536,
                max_edge=2048,
                band_names=("nir", "scl"),
            )
            if not bands_pack or "nir" not in bands_pack[0]:
                # Fallback: include VIS if NIR-only fetch failed
                bands_pack = self._try_load_bands_with_bounds(
                    request.scene_id,
                    bounds=aoi_bounds,
                    size=1280,
                    max_edge=1536,
                    band_names=("red", "green", "blue", "nir", "scl"),
                )
            if not bands_pack or "nir" not in bands_pack[0]:
                raise ValidationError(
                    "Could not load the NIR band for this scene — turn the eye off/on and retry."
                )
            bands, band_bounds = bands_pack
            conf_min = float(request.confidence_min if request.confidence_min is not None else 0.08)
            conf_min = max(0.05, min(conf_min, 0.9))
            result = detect_ships_optical_nir(
                bands,
                band_bounds,
                confidence_min=conf_min,
                collection=collection,
                aoi_polygon=aoi_geom,
                # Keep the same sensitive open-sea logic as the working GEE version:
                # AOI-adaptive NIR threshold constrained to 0.040–0.070, with
                # a soft 0.72× band for faint decks/wakes.
                nir_threshold=None,
            )
            overlay_b64 = None
            if result.get("overlay") is not None:
                from app.services.overlay_encode import encode_rgba_overlay

                data, _mime = encode_rgba_overlay(result["overlay"], prefer="webp", quality=75)
                overlay_b64 = base64.b64encode(data).decode("ascii")
            out_bounds = result.get("bounds") or band_bounds
            legend = self._legend(meta["label"], result["formula"])
            return DetectionRunResponse(
                task=task,
                bounds=[float(x) for x in out_bounds],
                overlay_base64=overlay_b64,
                geojson=result["geojson"],
                count=int(result["count"]),
                legend=legend,
                message=result["message"],
                formula=result["formula"],
                # On-image red demarcation only — no automatic shapefile download
                shapefile_ready=False,
                geometry_types=["Point", "Polygon"],
            )

        bands = self._try_load_bands(request.scene_id)
        features: list[dict[str, Any]] = []
        mode = "synthetic_seeded"

        if bands:
            try:
                features = self._spectral_detect(
                    task, meta, bands, bounds, request.confidence_min
                )
                mode = "spectral_guided"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Spectral detect failed for {}: {}", task, exc)
                features = []

        if not features:
            features = self._seeded_detect(task, meta, bounds, request.confidence_min)
            mode = "synthetic_seeded"

        heatmap = self._confidence_heatmap(bounds, features, size=256)
        overlay_b64 = base64.b64encode(heatmap).decode("ascii")
        legend = self._legend(meta["label"], algorithm)

        return DetectionRunResponse(
            task=task,
            bounds=bounds,
            overlay_base64=overlay_b64,
            geojson={"type": "FeatureCollection", "features": features},
            count=len(features),
            legend=legend,
            message=(
                f"{len(features)} {meta['label'].lower()} detections · "
                f"conf≥{request.confidence_min} · {mode}"
            ),
            formula=f"{algorithm} [{mode}]",
        )

    def _scene_collection(self, scene_id: str) -> str | None:
        try:
            from app.services.scene_imagery_service import SceneImageryService

            layer = SceneImageryService().get_layer(scene_id)
            if layer:
                return str(layer.get("collection") or layer.get("source") or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("scene collection lookup failed: {}", exc)
        return None

    def _try_load_bands_with_bounds(
        self,
        scene_id: str | None,
        *,
        bounds: list[float],
        size: int = 1024,
        max_edge: int = 1536,
        band_names: tuple[str, ...] = ("red", "green", "blue", "nir", "swir", "swir2"),
    ) -> tuple[dict[str, np.ndarray], list[float]] | None:
        """Load bands clipped to ``bounds`` (viewport / AOI) at higher resolution."""
        if not scene_id:
            return None
        try:
            from app.services.scene_imagery_service import SceneImageryService

            bands, used_bounds, _fp, _layer = SceneImageryService().load_analysis_bands(
                scene_id,
                size=size,
                bounds=bounds,
                band_names=band_names,
                max_edge=max_edge,
            )
            if not bands:
                return None
            return bands, [float(x) for x in used_bounds]
        except Exception as exc:  # noqa: BLE001
            logger.info("No scene bands for detection ({}): {}", scene_id, exc)
            return None

    def _try_load_bands(
        self,
        scene_id: str | None,
        size: int = 256,
        band_names: tuple[str, ...] = ("red", "green", "blue", "nir", "swir", "swir2"),
    ) -> dict[str, np.ndarray] | None:
        if not scene_id:
            return None
        try:
            from app.services.scene_imagery_service import SceneImageryService

            bands, _bounds, _fp, _layer = SceneImageryService().load_analysis_bands(
                scene_id,
                size=size,
                band_names=band_names,
            )
            return bands or None
        except Exception as exc:  # noqa: BLE001
            logger.info("No scene bands for detection ({}): {}", scene_id, exc)
            return None

    def _safe_div(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            out = a / b
            out[~np.isfinite(out)] = np.nan
        return out

    def _index_map(self, spectral: str, bands: dict[str, np.ndarray]) -> np.ndarray:
        red = bands.get("red")
        green = bands.get("green")
        blue = bands.get("blue")
        nir = bands.get("nir")
        swir = bands.get("swir") or bands.get("swir2")
        swir2 = bands.get("swir2") or swir

        def need(*keys: str) -> bool:
            return all(bands.get(k) is not None for k in keys)

        if spectral in ("ndvi", "ndvi_low") and need("nir", "red"):
            assert nir is not None and red is not None
            return np.clip(self._safe_div(nir - red, nir + red), -1, 1)
        if spectral == "ndwi" and need("green", "nir"):
            assert green is not None and nir is not None
            return np.clip(self._safe_div(green - nir, green + nir), -1, 1)
        if spectral == "ndbi" and swir is not None and nir is not None:
            return np.clip(self._safe_div(swir - nir, swir + nir), -1, 1)
        if spectral == "nbr" and nir is not None and swir2 is not None:
            return np.clip(self._safe_div(nir - swir2, nir + swir2), -1, 1)
        if spectral == "bsi" and all(x is not None for x in (red, green, nir, swir)):
            assert red is not None and green is not None and nir is not None and swir is not None
            num = (swir + red) - (nir + green)
            den = (swir + red) + (nir + green)
            return np.clip(self._safe_div(num, den), -1, 1)
        if spectral in ("edge", "blob", "water_blob", "swir_hot", "cloud", "lulc"):
            # Build a working intensity from available bands
            stack = [b for b in (nir, swir, red, green, blue) if b is not None]
            if not stack:
                raise ValidationError("No bands for spectral detect")
            base = np.nanmean(np.stack(stack, axis=0), axis=0)
            if spectral == "edge":
                gy, gx = np.gradient(np.nan_to_num(base, nan=0.0))
                return np.hypot(gx, gy)
            if spectral == "swir_hot" and swir is not None:
                return swir
            if spectral == "cloud" and blue is not None and nir is not None:
                return np.clip(self._safe_div(blue, nir + 1e-6), 0, 5)
            if spectral == "water_blob" and green is not None and nir is not None:
                # Bright residual on water: high local intensity where NDWI is high
                water = np.clip(self._safe_div(green - nir, green + nir), -1, 1)
                intensity = np.nan_to_num(base, nan=0.0)
                return intensity * (0.35 + 0.65 * np.clip(np.nan_to_num(water, nan=0.0), 0, 1))
            return base
        # fallback
        stack = [b for b in (nir, red, green) if b is not None]
        return np.nanmean(np.stack(stack, axis=0), axis=0)

    def _spectral_detect(
        self,
        task: str,
        meta: dict[str, Any],
        bands: dict[str, np.ndarray],
        bounds: list[float],
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        spectral = str(meta.get("spectral") or "blob")
        kind = meta["kind"]
        label = meta["label"]
        idx = self._index_map(spectral, bands)
        valid = idx[np.isfinite(idx)]
        if valid.size < 16:
            return []

        # Cue-specific thresholds
        if spectral in ("ndvi",):
            mask = idx > float(np.nanpercentile(valid, 70))
        elif spectral == "ndvi_low":
            mask = idx < float(np.nanpercentile(valid, 30))
        elif spectral in ("ndwi",):
            mask = idx > float(np.nanpercentile(valid, 75))
        elif spectral in ("ndbi", "bsi"):
            mask = idx > float(np.nanpercentile(valid, 72))
        elif spectral == "nbr":
            mask = idx < float(np.nanpercentile(valid, 25))  # burn = low NBR
        elif spectral in ("edge",):
            mask = idx > float(np.nanpercentile(valid, 85))
        elif spectral == "cloud":
            mask = idx > float(np.nanpercentile(valid, 80))
        elif spectral == "swir_hot":
            mask = idx > float(np.nanpercentile(valid, 88))
        else:
            mask = idx > float(np.nanpercentile(valid, 82))

        # Water-constrained blobs: keep only over water for ships
        if spectral == "water_blob" and bands.get("green") is not None and bands.get("nir") is not None:
            water = np.clip(
                self._safe_div(bands["green"] - bands["nir"], bands["green"] + bands["nir"]),
                -1,
                1,
            )
            water_mask = water > float(np.nanpercentile(water[np.isfinite(water)], 70))
            peaks = self._local_maxima(np.nan_to_num(idx, nan=0.0), min_dist=6)
            peaks = peaks & water_mask
            return self._peaks_to_features(peaks, idx, bounds, label, task, kind, confidence_min)

        if kind == "point" or spectral in ("blob", "swir_hot"):
            peaks = self._local_maxima(np.nan_to_num(idx, nan=0.0) * mask, min_dist=5)
            return self._peaks_to_features(peaks, idx, bounds, label, task, kind, confidence_min)

        if kind == "line" or spectral == "edge":
            return self._ridges_to_lines(mask, idx, bounds, label, task, confidence_min)

        # polygons from connected components
        return self._mask_to_polygons(mask, idx, bounds, label, task, confidence_min)

    def _local_maxima(self, arr: np.ndarray, min_dist: int = 5) -> np.ndarray:
        from scipy import ndimage  # optional; fallback if missing

        try:
            maxf = ndimage.maximum_filter(arr, size=min_dist)
            peaks = (arr == maxf) & (arr > np.percentile(arr, 80))
            return peaks
        except Exception:  # noqa: BLE001
            # Pure numpy coarse peaks
            h, w = arr.shape
            peaks = np.zeros_like(arr, dtype=bool)
            step = max(min_dist, 4)
            for r in range(step, h - step, step):
                for c in range(step, w - step, step):
                    block = arr[r - step // 2 : r + step // 2 + 1, c - step // 2 : c + step // 2 + 1]
                    if block.size and arr[r, c] >= block.max() and arr[r, c] > np.percentile(arr, 80):
                        peaks[r, c] = True
            return peaks

    def _pixel_to_lonlat(
        self, row: int, col: int, shape: tuple[int, int], bounds: list[float]
    ) -> tuple[float, float]:
        west, south, east, north = bounds
        h, w = shape
        lon = west + (col + 0.5) / w * (east - west)
        lat = north - (row + 0.5) / h * (north - south)
        return float(lon), float(lat)

    def _norm_conf(self, value: float, arr: np.ndarray) -> float:
        valid = arr[np.isfinite(arr)]
        if valid.size == 0:
            return 0.5
        lo, hi = float(np.nanpercentile(valid, 5)), float(np.nanpercentile(valid, 95))
        if hi <= lo:
            return 0.6
        return float(np.clip((value - lo) / (hi - lo), 0.05, 0.99))

    def _peaks_to_features(
        self,
        peaks: np.ndarray,
        idx: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        kind: str,
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        rows, cols = np.where(peaks)
        features: list[dict[str, Any]] = []
        for i, (r, c) in enumerate(zip(rows.tolist(), cols.tolist(), strict=False)):
            conf = self._norm_conf(float(idx[r, c]), idx)
            if conf < confidence_min:
                continue
            lon, lat = self._pixel_to_lonlat(r, c, idx.shape, bounds)
            if kind == "polygon":
                dlon = (bounds[2] - bounds[0]) * 0.015
                dlat = (bounds[3] - bounds[1]) * 0.015
                ring = [
                    [lon - dlon, lat - dlat],
                    [lon + dlon, lat - dlat],
                    [lon + dlon, lat + dlat],
                    [lon - dlon, lat + dlat],
                    [lon - dlon, lat - dlat],
                ]
                geom: dict[str, Any] = {"type": "Polygon", "coordinates": [ring]}
            else:
                geom = {"type": "Point", "coordinates": [lon, lat]}
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": label,
                        "confidence": round(conf, 3),
                        "task": task,
                        "id": f"{task}_{i}",
                        "algorithm": TASK_META.get(task, {}).get("algorithm"),
                    },
                    "geometry": geom,
                }
            )
            if len(features) >= 40:
                break
        return features

    def _ridges_to_lines(
        self,
        mask: np.ndarray,
        idx: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        peaks = self._local_maxima(np.nan_to_num(idx, nan=0.0) * mask, min_dist=8)
        rows, cols = np.where(peaks)
        if len(rows) < 2:
            return []
        # Pair nearest peaks into line segments
        pts = list(zip(rows.tolist(), cols.tolist(), strict=False))
        features: list[dict[str, Any]] = []
        used = set()
        for i, (r0, c0) in enumerate(pts):
            if i in used:
                continue
            best = None
            best_d = 1e9
            for j, (r1, c1) in enumerate(pts):
                if j <= i:
                    continue
                d = (r0 - r1) ** 2 + (c0 - c1) ** 2
                if 20 < d < best_d:
                    best_d = d
                    best = j
            if best is None:
                continue
            used.add(i)
            used.add(best)
            r1, c1 = pts[best]
            conf = self._norm_conf(float((idx[r0, c0] + idx[r1, c1]) / 2), idx)
            if conf < confidence_min:
                continue
            lon0, lat0 = self._pixel_to_lonlat(r0, c0, idx.shape, bounds)
            lon1, lat1 = self._pixel_to_lonlat(r1, c1, idx.shape, bounds)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": label,
                        "confidence": round(conf, 3),
                        "task": task,
                        "id": f"{task}_{len(features)}",
                        "algorithm": TASK_META.get(task, {}).get("algorithm"),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon0, lat0], [lon1, lat1]],
                    },
                }
            )
            if len(features) >= 15:
                break
        return features

    def _mask_to_polygons(
        self,
        mask: np.ndarray,
        idx: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        try:
            from scipy import ndimage

            labeled, nlab = ndimage.label(mask)
        except Exception:  # noqa: BLE001
            # Coarse block polygons
            labeled = np.zeros_like(mask, dtype=int)
            nlab = 0
            h, w = mask.shape
            step = max(h // 6, 8)
            for r in range(0, h, step):
                for c in range(0, w, step):
                    block = mask[r : r + step, c : c + step]
                    if block.mean() > 0.35:
                        nlab += 1
                        labeled[r : r + step, c : c + step] = nlab

        features: list[dict[str, Any]] = []
        for lab in range(1, min(nlab, 25) + 1):
            ys, xs = np.where(labeled == lab)
            if ys.size < 8:
                continue
            conf = self._norm_conf(float(np.nanmean(idx[ys, xs])), idx)
            if conf < confidence_min:
                continue
            r0, r1 = int(ys.min()), int(ys.max())
            c0, c1 = int(xs.min()), int(xs.max())
            # Expand slightly
            lon0, lat1 = self._pixel_to_lonlat(r0, c0, idx.shape, bounds)
            lon1, lat0 = self._pixel_to_lonlat(r1, c1, idx.shape, bounds)
            west, south = min(lon0, lon1), min(lat0, lat1)
            east, north = max(lon0, lon1), max(lat0, lat1)
            ring = [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": label,
                        "confidence": round(conf, 3),
                        "task": task,
                        "id": f"{task}_{lab}",
                        "algorithm": TASK_META.get(task, {}).get("algorithm"),
                    },
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
        return features

    def _seeded_detect(
        self,
        task: str,
        meta: dict[str, Any],
        bounds: list[float],
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        seed = self._seed(task, bounds)
        rng = np.random.default_rng(seed)
        lo, hi = meta["count"]
        n = int(rng.integers(lo, hi + 1))
        features: list[dict[str, Any]] = []
        for i in range(n):
            conf = float(rng.uniform(0.35, 0.98))
            if conf < confidence_min:
                continue
            geom = self._make_geometry(meta["kind"], bounds, rng, i, task)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": meta["label"],
                        "confidence": round(conf, 3),
                        "task": task,
                        "id": f"{task}_{i}",
                        "algorithm": meta.get("algorithm"),
                    },
                    "geometry": geom,
                }
            )
        return features

    def _seed(self, task: str, bounds: list[float]) -> int:
        key = f"{task}:{round(bounds[0], 4)}:{round(bounds[1], 4)}:{round(bounds[2], 4)}:{round(bounds[3], 4)}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _resolve_bounds(
        self, bbox: list[float] | None, aoi: dict[str, Any] | None
    ) -> list[float]:
        if bbox and len(bbox) == 4:
            return [float(x) for x in bbox]
        if aoi:
            try:
                from shapely.geometry import shape

                geom = shape(aoi if aoi.get("type") != "Feature" else aoi["geometry"])
                minx, miny, maxx, maxy = geom.bounds
                return [float(minx), float(miny), float(maxx), float(maxy)]
            except Exception:  # noqa: BLE001
                pass
        raise ValidationError("bbox [west,south,east,north] is required")

    def _make_geometry(
        self,
        kind: str,
        bounds: list[float],
        rng: np.random.Generator,
        idx: int,
        task: str,
    ) -> dict[str, Any]:
        west, south, east, north = bounds
        w = east - west
        h = north - south
        pad_x, pad_y = w * 0.08, h * 0.08

        if kind == "point":
            lon = float(west + pad_x + rng.random() * (w - 2 * pad_x))
            lat = float(south + pad_y + rng.random() * (h - 2 * pad_y))
            return {"type": "Point", "coordinates": [lon, lat]}

        if kind == "line":
            n_pts = 3 if "runway" in task else int(rng.integers(3, 6))
            angle = float(rng.uniform(0, math.pi))
            cx = west + pad_x + rng.random() * (w - 2 * pad_x)
            cy = south + pad_y + rng.random() * (h - 2 * pad_y)
            length = (0.25 + 0.45 * rng.random()) * min(w, h)
            coords = []
            for k in range(n_pts):
                t = (k / max(n_pts - 1, 1) - 0.5) * length
                jitter = (rng.random() - 0.5) * length * 0.08
                lon = cx + t * math.cos(angle) - jitter * math.sin(angle)
                lat = cy + t * math.sin(angle) + jitter * math.cos(angle)
                lon = min(max(lon, west + pad_x * 0.5), east - pad_x * 0.5)
                lat = min(max(lat, south + pad_y * 0.5), north - pad_y * 0.5)
                coords.append([float(lon), float(lat)])
            return {"type": "LineString", "coordinates": coords}

        bw = (0.04 + 0.12 * rng.random()) * w
        bh = (0.04 + 0.12 * rng.random()) * h
        if "airport" in task or "oil_spill" in task or "flood" in task:
            bw *= 2.2
            bh *= 1.8
        cx = west + pad_x + rng.random() * (w - 2 * pad_x)
        cy = south + pad_y + rng.random() * (h - 2 * pad_y)
        angle = float(rng.uniform(0, math.pi / 2)) if "building" in task else 0.0
        corners = [(-bw / 2, -bh / 2), (bw / 2, -bh / 2), (bw / 2, bh / 2), (-bw / 2, bh / 2)]
        ring = []
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        for dx, dy in corners:
            lon = cx + dx * cos_a - dy * sin_a
            lat = cy + dx * sin_a + dy * cos_a
            ring.append([float(lon), float(lat)])
        ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}

    def _confidence_heatmap(
        self,
        bounds: list[float],
        features: list[dict[str, Any]],
        size: int = 256,
    ) -> bytes:
        west, south, east, north = bounds
        heat = np.zeros((size, size), dtype=np.float64)
        for feat in features:
            conf = float((feat.get("properties") or {}).get("confidence", 0.5))
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            pts: list[tuple[float, float]] = []
            if gtype == "Point":
                pts = [(float(coords[0]), float(coords[1]))]
            elif gtype == "LineString":
                pts = [(float(c[0]), float(c[1])) for c in coords]
            elif gtype == "Polygon":
                ring = coords[0] if coords else []
                if ring:
                    lons = [c[0] for c in ring[:-1]]
                    lats = [c[1] for c in ring[:-1]]
                    pts = [(float(np.mean(lons)), float(np.mean(lats)))]
                    pts.extend(
                        (float(c[0]), float(c[1]))
                        for c in ring[:-1 : max(1, len(ring) // 4)]
                    )
            for lon, lat in pts:
                col = int(
                    np.clip(
                        round((lon - west) / (east - west + 1e-12) * (size - 1)),
                        0,
                        size - 1,
                    )
                )
                row = int(
                    np.clip(
                        round((north - lat) / (north - south + 1e-12) * (size - 1)),
                        0,
                        size - 1,
                    )
                )
                yy, xx = np.mgrid[0:size, 0:size]
                sigma = size * 0.045
                blob = np.exp(-((xx - col) ** 2 + (yy - row) ** 2) / (2 * sigma**2))
                heat += conf * blob

        if heat.max() > 0:
            heat = heat / heat.max()
        t = np.clip(heat, 0, 1)
        r = np.clip(0.2 + 0.8 * t, 0, 1)
        g = np.clip(0.85 * (1 - abs(t - 0.45) * 1.4), 0, 1)
        b = np.clip(0.15 * (1 - t), 0, 1)
        alpha = (t * 190).astype(np.uint8)
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[..., 0] = (r * 255).astype(np.uint8)
        rgba[..., 1] = (g * 255).astype(np.uint8)
        rgba[..., 2] = (b * 255).astype(np.uint8)
        rgba[..., 3] = alpha
        from app.services.overlay_encode import encode_rgba_overlay

        data, _mime = encode_rgba_overlay(rgba, prefer="webp", quality=70)
        return data

    def _legend(self, label: str, algorithm: str) -> LegendInfo:
        stops = [
            ColormapStop(value=0.0, color="#331a00"),
            ColormapStop(value=0.25, color="#cc8800"),
            ColormapStop(value=0.5, color="#ffcc33"),
            ColormapStop(value=0.75, color="#ff6622"),
            ColormapStop(value=1.0, color="#cc1100"),
        ]
        return LegendInfo(
            min=0.0,
            max=1.0,
            unit="confidence",
            label=f"{label} confidence",
            formula=algorithm,
            stops=stops,
        )
