"""Task-specific EO detectors for Light Explorer (CV + ML / neural nets).

Each product uses a specialized algorithm family:
  • Buildings / urban: MLP neural net on spectral+texture → built-up mask + contours
  • Roads / runway / railway: Canny + Probabilistic Hough line extraction
  • Ships / vessels: two-parameter CFAR on water-masked intensity
  • Aircraft / vehicles: Difference-of-Gaussians blobs on apron / bright residual
  • Water / flood / oil: Otsu MNDWI/NDWI + morphological closing + contour polygons
  • Burn / fire: NBR / SWIR anomaly detection
  • LULC / vegetation / crops: RandomForest spectral–texture classifier (scikit-learn)
  • Bridges: linear Hough features spanning water mask
  • Solar / construction: albedo + BSI / regularity filters

Random seeded geometries are disabled for imagery tasks. Eye-On a scene is required.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import cv2
import numpy as np
from loguru import logger
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.detection import DetectionRunRequest, DetectionRunResponse

# Task catalog — algorithm strings match the real implementations below
TASK_META: dict[str, dict[str, Any]] = {
    "building_detection": {
        "label": "Building",
        "kind": "polygon",
        "domain": "ai",
        "detector": "buildings",
        "algorithm": "MLP neural net (spectral+texture) → built-up mask + MBI refine + contours",
        "needs_scene": True,
    },
    "road_extraction": {
        "label": "Road",
        "kind": "line",
        "domain": "ai",
        "detector": "roads",
        "algorithm": "Spectral road index + Canny + Probabilistic HoughLinesP",
        "needs_scene": True,
    },
    "vehicle_detection": {
        "label": "Vehicle",
        "kind": "point",
        "domain": "ai",
        "detector": "vehicles",
        "algorithm": "DoG blob detection on SWIR/NIR residual (vehicle-scale)",
        "needs_scene": True,
    },
    "change_detection": {
        "label": "Change",
        "kind": "polygon",
        "domain": "ai",
        "detector": "change",
        "algorithm": "Spectral anomaly clustering (NDVI residual hotspots)",
        "needs_scene": True,
    },
    "flood_detection": {
        "label": "Flood",
        "kind": "polygon",
        "domain": "ai",
        "detector": "flood",
        "algorithm": "Otsu MNDWI + morphological closing (McFeeters / Xu water)",
        "needs_scene": True,
    },
    "land_cover_classification": {
        "label": "Land cover",
        "kind": "polygon",
        "domain": "ai",
        "detector": "lulc",
        "algorithm": "RandomForest LULC on NDVI/NDBI/NDWI/BSI + texture (sklearn)",
        "needs_scene": True,
    },
    "object_detection": {
        "label": "Object",
        "kind": "point",
        "domain": "ai",
        "detector": "objects",
        "algorithm": "Multi-scale Difference-of-Gaussians blob detector",
        "needs_scene": True,
    },
    "deforestation_detection": {
        "label": "Deforestation",
        "kind": "polygon",
        "domain": "ai",
        "detector": "deforest",
        "algorithm": "Low-NDVI forest-loss patches with morphological clean-up",
        "needs_scene": True,
    },
    "fire_detection": {
        "label": "Fire / hot spot",
        "kind": "point",
        "domain": "ai",
        "detector": "fire",
        "algorithm": "SWIR / thermal hot-spot CFAR peaks",
        "needs_scene": True,
    },
    "crop_classification": {
        "label": "Crop parcel",
        "kind": "polygon",
        "domain": "ai",
        "detector": "crops",
        "algorithm": "NDVI agricultural mask + watershed parcel segmentation",
        "needs_scene": True,
    },
    "bridge_detection": {
        "label": "Bridge",
        "kind": "line",
        "domain": "ai",
        "detector": "bridges",
        "algorithm": "Hough lines spanning water mask (NDWI ∩ Canny)",
        "needs_scene": True,
    },
    "airport_mapping": {
        "label": "Airport",
        "kind": "polygon",
        "domain": "ai",
        "detector": "airport",
        "algorithm": "Large low-NDVI / high-NDBI apron + runway Hough fusion",
        "needs_scene": True,
    },
    "runway_detection": {
        "label": "Runway",
        "kind": "line",
        "domain": "ai",
        "detector": "runway",
        "algorithm": "Long straight Hough lines on bright low-NDVI pavement",
        "needs_scene": True,
    },
    "port_mapping": {
        "label": "Port",
        "kind": "polygon",
        "domain": "ai",
        "detector": "port",
        "algorithm": "Harbor = NDWI water + NDBI quay morphology",
        "needs_scene": True,
    },
    "harbor_detection": {
        "label": "Harbor",
        "kind": "polygon",
        "domain": "ai",
        "detector": "port",
        "algorithm": "Enclosed waterbody + quay NDBI from shoreline morphology",
        "needs_scene": True,
    },
    "ship_detection": {
        "label": "Ship",
        "kind": "point",
        "domain": "ai",
        "detector": "ships",
        "algorithm": "Two-parameter CFAR on water-masked optical intensity",
        "needs_scene": True,
    },
    "aircraft_detection": {
        "label": "Aircraft",
        "kind": "point",
        "domain": "ai",
        "detector": "aircraft",
        "algorithm": "DoG bright blobs on low-NDVI airport apron mask",
        "needs_scene": True,
    },
    "railway_detection": {
        "label": "Railway",
        "kind": "line",
        "domain": "ai",
        "detector": "railway",
        "algorithm": "Narrow linear Hough ridges on edge magnitude",
        "needs_scene": True,
    },
    "powerline_corridor_mapping": {
        "label": "Powerline corridor",
        "kind": "line",
        "domain": "ai",
        "detector": "corridor",
        "algorithm": "NDVI clearing corridors + Hough axis extraction",
        "needs_scene": True,
    },
    "solar_farm_detection": {
        "label": "Solar farm",
        "kind": "polygon",
        "domain": "ai",
        "detector": "solar",
        "algorithm": "Low-albedo / dark SWIR rectangular arrays + contour filter",
        "needs_scene": True,
    },
    "wind_farm_detection": {
        "label": "Wind farm",
        "kind": "point",
        "domain": "ai",
        "detector": "wind",
        "algorithm": "Regular-spacing DoG peaks (turbine-scale CFAR)",
        "needs_scene": True,
    },
    "construction_site_detection": {
        "label": "Construction site",
        "kind": "polygon",
        "domain": "ai",
        "detector": "construction",
        "algorithm": "High Bare-Soil Index (BSI) patches + morphology",
        "needs_scene": True,
    },
    "urban_expansion_detection": {
        "label": "Urban expansion",
        "kind": "polygon",
        "domain": "ai",
        "detector": "buildings",
        "algorithm": "MLP built-up neural net (NDBI/NDVI/texture) — urban clusters",
        "needs_scene": True,
    },
    "vegetation_classification": {
        "label": "Vegetation class",
        "kind": "polygon",
        "domain": "ai",
        "detector": "vegetation",
        "algorithm": "NDVI class bins (sparse / moderate / dense) + contours",
        "needs_scene": True,
    },
    "burn_scar_detection": {
        "label": "Burn scar",
        "kind": "polygon",
        "domain": "ai",
        "detector": "burn",
        "algorithm": "NBR burn-severity Otsu threshold (Key & Benson)",
        "needs_scene": True,
    },
    "water_body_extraction": {
        "label": "Water body",
        "kind": "polygon",
        "domain": "ai",
        "detector": "water",
        "algorithm": "Otsu MNDWI water extraction + contour vectorize",
        "needs_scene": True,
    },
    "confidence_heatmap": {
        "label": "Confidence",
        "kind": "point",
        "domain": "ai",
        "detector": "objects",
        "algorithm": "Multi-cue DoG confidence field (object candidates)",
        "needs_scene": True,
    },
    "cloud_mask": {
        "label": "Cloud",
        "kind": "polygon",
        "domain": "ai",
        "detector": "cloud",
        "algorithm": "Bright-pixel + blue/NIR ratio cloud mask (ACCAs-style)",
        "needs_scene": True,
    },
    # Maritime
    "ship_detection_sar": {
        "label": "Ship (SAR)",
        "kind": "point",
        "domain": "maritime",
        "detector": "ships_sar",
        "algorithm": "Two-parameter CFAR on SAR-like intensity (optical proxy if no SAR)",
        "needs_scene": True,
    },
    "ship_detection_optical": {
        "label": "Ship (optical)",
        "kind": "point",
        "domain": "maritime",
        "detector": "ships",
        "algorithm": "Two-parameter CFAR on NDWI water mask (optical)",
        "needs_scene": True,
    },
    "vessel_density_map": {
        "label": "Vessel density",
        "kind": "point",
        "domain": "maritime",
        "detector": "ships",
        "algorithm": "CFAR ship peaks + Gaussian KDE density field",
        "needs_scene": True,
    },
    "port_activity_mapping": {
        "label": "Port activity",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "port",
        "algorithm": "Port apron clustering (NDBI ∩ NDWI shore)",
        "needs_scene": True,
    },
    "anchorage_detection": {
        "label": "Anchorage",
        "kind": "point",
        "domain": "maritime",
        "detector": "ships",
        "algorithm": "CFAR vessel clusters in coastal waters",
        "needs_scene": True,
    },
    "shipping_lane_visualization": {
        "label": "Shipping lane",
        "kind": "line",
        "domain": "maritime",
        "detector": "lanes",
        "algorithm": "Lane axes from vessel-density ridge Hough",
        "needs_scene": True,
    },
    "oil_spill_detection": {
        "label": "Oil spill",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "oil",
        "algorithm": "Dark slick anomaly on water (low NIR/SWIR in NDWI mask)",
        "needs_scene": True,
    },
    "wake_detection": {
        "label": "Wake",
        "kind": "line",
        "domain": "maritime",
        "detector": "wake",
        "algorithm": "Linear wake ridges (Canny on water residual)",
        "needs_scene": True,
    },
    "port_activity_monitoring": {
        "label": "Port berth",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "port",
        "algorithm": "Berth polygons from NDBI shore facilities",
        "needs_scene": True,
    },
    "dark_vessel_detection": {
        "label": "Dark vessel",
        "kind": "point",
        "domain": "maritime",
        "detector": "dark_ships",
        "algorithm": "Inverse-CFAR dark targets in water mask",
        "needs_scene": True,
    },
    "maritime_domain_awareness": {
        "label": "Maritime contact",
        "kind": "point",
        "domain": "maritime",
        "detector": "ships",
        "algorithm": "Fused optical CFAR contacts on water",
        "needs_scene": True,
    },
    "sea_surface_temperature": {
        "label": "SST cell",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "sst",
        "algorithm": "Thermal / SWIR anomaly zoning (relative SST proxy)",
        "needs_scene": True,
    },
    "chlorophyll_overlay": {
        "label": "Chlorophyll",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "chl",
        "algorithm": "Green/blue ratio bloom zones over water",
        "needs_scene": True,
    },
    "wave_height_overlay": {
        "label": "Wave height",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "wave",
        "algorithm": "Local variance texture zoning over water",
        "needs_scene": True,
    },
    "wind_speed_overlay": {
        "label": "Wind speed",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "wave",
        "algorithm": "Roughness proxy zoning (texture variance)",
        "needs_scene": True,
    },
    "coastal_erosion_mapping": {
        "label": "Coastal erosion",
        "kind": "line",
        "domain": "maritime",
        "detector": "shoreline",
        "algorithm": "Shoreline polyline from NDWI Canny edge",
        "needs_scene": True,
    },
    "tidal_zone_mapping": {
        "label": "Tidal zone",
        "kind": "polygon",
        "domain": "maritime",
        "detector": "tidal",
        "algorithm": "Intertidal NDWI fringe polygons",
        "needs_scene": True,
    },
    # Air
    "airport_detection": {
        "label": "Airport",
        "kind": "polygon",
        "domain": "air",
        "detector": "airport",
        "algorithm": "Large NDBI facility + runway Hough fusion",
        "needs_scene": True,
    },
    "runway_extraction": {
        "label": "Runway",
        "kind": "line",
        "domain": "air",
        "detector": "runway",
        "algorithm": "Long straight Hough lines on pavement mask",
        "needs_scene": True,
    },
    "airfield_monitoring": {
        "label": "Airfield asset",
        "kind": "polygon",
        "domain": "air",
        "detector": "airport",
        "algorithm": "Airfield parcel segmentation (NDBI apron)",
        "needs_scene": True,
    },
    "helicopter_detection": {
        "label": "Helicopter",
        "kind": "point",
        "domain": "air",
        "detector": "aircraft",
        "algorithm": "Small-scale DoG bright-target peaks on apron",
        "needs_scene": True,
    },
    "uav_detection": {
        "label": "UAV",
        "kind": "point",
        "domain": "air",
        "detector": "vehicles",
        "algorithm": "Compact DoG blob detector (small-object CFAR)",
        "needs_scene": True,
    },
    "airport_database": {
        "label": "Airport",
        "kind": "point",
        "domain": "air",
        "detector": "airport_point",
        "algorithm": "Facility centroid from NDBI apron cluster",
        "needs_scene": True,
    },
    "runway_inventory": {
        "label": "Runway",
        "kind": "line",
        "domain": "air",
        "detector": "runway",
        "algorithm": "Runway axis inventory (Hough on pavement)",
        "needs_scene": True,
    },
    "airport_expansion_monitoring": {
        "label": "Airport expansion",
        "kind": "polygon",
        "domain": "air",
        "detector": "construction",
        "algorithm": "Bare-soil / NDBI expansion near airfield",
        "needs_scene": True,
    },
    "airspace_overlay": {
        "label": "Airspace",
        "kind": "polygon",
        "domain": "air",
        "detector": "external",
        "algorithm": "Requires live airspace feed (not imagery-derived)",
        "needs_scene": False,
    },
    "notam_overlay": {
        "label": "NOTAM",
        "kind": "polygon",
        "domain": "air",
        "detector": "external",
        "algorithm": "Requires live NOTAM feed (not imagery-derived)",
        "needs_scene": False,
    },
    "weather_overlay": {
        "label": "Weather cell",
        "kind": "polygon",
        "domain": "air",
        "detector": "cloud",
        "algorithm": "Cloud/weather cell segmentation from optical mask",
        "needs_scene": True,
    },
    "terrain_awareness": {
        "label": "Terrain hazard",
        "kind": "polygon",
        "domain": "air",
        "detector": "terrain",
        "algorithm": "High edge-texture / relief proxy hazard zones",
        "needs_scene": True,
    },
    "visibility_analysis": {
        "label": "Visibility",
        "kind": "polygon",
        "domain": "air",
        "detector": "cloud",
        "algorithm": "Low-visibility proxy from cloud / haze mask",
        "needs_scene": True,
    },
    "vessel_tracking": {
        "label": "Vessel track",
        "kind": "line",
        "domain": "maritime",
        "detector": "lanes",
        "algorithm": "Track linking of CFAR ship peaks via Hough lanes",
        "needs_scene": True,
    },
}


class DetectionService:
    """Specialized EO detectors — OpenCV CV + scikit-learn ML (no random fakes)."""

    ANALYSIS_SIZE = 512

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
            "kind": "point",
            "domain": "ai",
            "detector": "objects",
            "algorithm": "Multi-scale DoG blob detector",
            "needs_scene": True,
        }
        algorithm = str(meta.get("algorithm") or "specialized EO detector")
        needs_scene = bool(meta.get("needs_scene", True))
        detector = str(meta.get("detector") or "objects")

        if detector == "external":
            return DetectionRunResponse(
                task=task,
                bounds=bounds,
                overlay_base64=None,
                geojson={"type": "FeatureCollection", "features": []},
                count=0,
                legend=self._legend(meta["label"], algorithm),
                message=(
                    f"{meta['label']}: live external feed not configured. "
                    "Connect AIS/NOTAM/airspace API for real overlays."
                ),
                formula=algorithm,
            )

        if needs_scene and not request.scene_id:
            raise ValidationError(
                f"{meta['label']} requires Eye-On imagery. Toggle a scene eye, then run again."
            )

        bands = self._try_load_bands(request.scene_id)
        if not bands:
            raise ValidationError(
                f"Could not load analysis bands for {meta['label']}. "
                "Eye-On an optical scene (Sentinel-2 / Landsat) over the AOI."
            )

        try:
            features = self._dispatch(
                detector, task, meta, bands, bounds, request.confidence_min
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Detector {} failed: {}", detector, exc)
            raise ValidationError(f"Detection failed ({algorithm}): {exc}") from exc

        heatmap = self._confidence_heatmap(bounds, features, bands, size=self.ANALYSIS_SIZE)
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
                f"conf≥{request.confidence_min:.2f} · {algorithm}"
            ),
            formula=algorithm,
        )

    # ── band / index helpers ──────────────────────────────────────────────

    def _try_load_bands(self, scene_id: str | None) -> dict[str, np.ndarray] | None:
        if not scene_id:
            return None
        try:
            from app.services.scene_imagery_service import SceneImageryService

            bands, _bounds, _fp, _layer = SceneImageryService().load_analysis_bands(
                scene_id, size=self.ANALYSIS_SIZE
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

    def _band(self, bands: dict[str, np.ndarray], *keys: str) -> np.ndarray | None:
        for k in keys:
            if bands.get(k) is not None:
                return np.asarray(bands[k], dtype=np.float32)
        return None

    def _ndvi(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        nir, red = self._band(bands, "nir"), self._band(bands, "red")
        if nir is None or red is None:
            return None
        return np.clip(self._safe_div(nir - red, nir + red), -1, 1)

    def _ndwi(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        green, nir = self._band(bands, "green"), self._band(bands, "nir")
        if green is None or nir is None:
            return None
        return np.clip(self._safe_div(green - nir, green + nir), -1, 1)

    def _mndwi(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        green = self._band(bands, "green")
        swir = self._band(bands, "swir", "swir2")
        if green is None or swir is None:
            return None
        return np.clip(self._safe_div(green - swir, green + swir), -1, 1)

    def _water_index(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        m = self._mndwi(bands)
        if m is not None:
            return m
        return self._ndwi(bands)

    def _ndbi(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        swir = self._band(bands, "swir", "swir2")
        nir = self._band(bands, "nir")
        if swir is None or nir is None:
            return None
        return np.clip(self._safe_div(swir - nir, swir + nir), -1, 1)

    def _nbr(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        nir = self._band(bands, "nir")
        swir2 = self._band(bands, "swir2", "swir")
        if nir is None or swir2 is None:
            return None
        return np.clip(self._safe_div(nir - swir2, nir + swir2), -1, 1)

    def _bsi(self, bands: dict[str, np.ndarray]) -> np.ndarray | None:
        red, green = self._band(bands, "red"), self._band(bands, "green")
        nir, swir = self._band(bands, "nir"), self._band(bands, "swir", "swir2")
        if any(x is None for x in (red, green, nir, swir)):
            return None
        assert red is not None and green is not None and nir is not None and swir is not None
        num = (swir + red) - (nir + green)
        den = (swir + red) + (nir + green)
        return np.clip(self._safe_div(num, den), -1, 1)

    def _intensity(self, bands: dict[str, np.ndarray]) -> np.ndarray:
        stack = [
            b
            for b in (
                self._band(bands, "nir"),
                self._band(bands, "red"),
                self._band(bands, "green"),
                self._band(bands, "blue"),
                self._band(bands, "swir", "swir2"),
            )
            if b is not None
        ]
        if not stack:
            raise ValidationError("No reflectance bands available")
        return np.nanmean(np.stack(stack, axis=0), axis=0).astype(np.float32)

    def _to_u8(self, arr: np.ndarray, p_lo: float = 2, p_hi: float = 98) -> np.ndarray:
        valid = arr[np.isfinite(arr)]
        if valid.size == 0:
            return np.zeros(arr.shape, dtype=np.uint8)
        lo, hi = np.percentile(valid, [p_lo, p_hi])
        scaled = np.clip((arr - lo) / (hi - lo + 1e-9), 0, 1)
        scaled = np.nan_to_num(scaled, nan=0.0)
        return (scaled * 255).astype(np.uint8)

    def _otsu_mask(self, arr: np.ndarray, invert: bool = False) -> np.ndarray:
        u8 = self._to_u8(arr)
        thr, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = u8 >= thr
        return ~mask if invert else mask

    def _morph_clean(self, mask: np.ndarray, open_k: int = 3, close_k: int = 5) -> np.ndarray:
        m = (mask.astype(np.uint8) * 255)
        if open_k > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        if close_k > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        return m > 0

    # ── geometry helpers ──────────────────────────────────────────────────

    def _pixel_to_lonlat(
        self, row: float, col: float, shape: tuple[int, int], bounds: list[float]
    ) -> tuple[float, float]:
        west, south, east, north = bounds
        h, w = shape
        lon = west + (col + 0.5) / w * (east - west)
        lat = north - (row + 0.5) / h * (north - south)
        return float(lon), float(lat)

    def _contour_polygons(
        self,
        mask: np.ndarray,
        score: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        confidence_min: float,
        min_area: int = 40,
        max_features: int = 60,
        class_name: str | None = None,
    ) -> list[dict[str, Any]]:
        m = (mask.astype(np.uint8) * 255)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        features: list[dict[str, Any]] = []
        h, w = mask.shape
        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            # Simplify
            eps = 0.01 * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, eps, True)
            if len(approx) < 3:
                continue
            ring = []
            for pt in approx[:, 0, :]:
                lon, lat = self._pixel_to_lonlat(float(pt[1]), float(pt[0]), (h, w), bounds)
                ring.append([lon, lat])
            ring.append(ring[0])
            # Confidence from mean score inside contour
            cmask = np.zeros_like(m)
            cv2.drawContours(cmask, [cnt], -1, 255, -1)
            vals = score[cmask > 0]
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                conf = 0.5
            else:
                conf = float(np.clip(np.nanmean(self._norm01(vals)), 0.05, 0.99))
            if conf < confidence_min:
                continue
            props: dict[str, Any] = {
                "label": label if not class_name else f"{label}: {class_name}",
                "confidence": round(conf, 3),
                "task": task,
                "id": f"{task}_{i}",
                "algorithm": TASK_META.get(task, {}).get("algorithm"),
                "area_px": int(area),
            }
            if class_name:
                props["class"] = class_name
            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
            if len(features) >= max_features:
                break
        return features

    def _hough_lines(
        self,
        edge_u8: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        confidence_min: float,
        min_line_length: int = 40,
        max_line_gap: int = 12,
        threshold: int = 40,
        max_features: int = 40,
        score_map: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        lines = cv2.HoughLinesP(
            edge_u8,
            rho=1,
            theta=np.pi / 180,
            threshold=threshold,
            minLineLength=min_line_length,
            maxLineGap=max_line_gap,
        )
        if lines is None:
            return []
        h, w = edge_u8.shape
        features: list[dict[str, Any]] = []
        for i, line in enumerate(lines[:, 0, :]):
            x1, y1, x2, y2 = map(int, line)
            length = math.hypot(x2 - x1, y2 - y1)
            conf = float(np.clip(length / max(h, w), 0.15, 0.99))
            if score_map is not None:
                rs = np.linspace(y1, y2, num=max(5, int(length // 4)))
                cs = np.linspace(x1, x2, num=max(5, int(length // 4)))
                samp = score_map[
                    np.clip(rs.astype(int), 0, h - 1),
                    np.clip(cs.astype(int), 0, w - 1),
                ]
                conf = float(np.clip(0.4 * conf + 0.6 * np.nanmean(self._norm01(samp)), 0.05, 0.99))
            if conf < confidence_min:
                continue
            lon1, lat1 = self._pixel_to_lonlat(y1, x1, (h, w), bounds)
            lon2, lat2 = self._pixel_to_lonlat(y2, x2, (h, w), bounds)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": label,
                        "confidence": round(conf, 3),
                        "task": task,
                        "id": f"{task}_{i}",
                        "algorithm": TASK_META.get(task, {}).get("algorithm"),
                        "length_px": round(length, 1),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon1, lat1], [lon2, lat2]],
                    },
                }
            )
            if len(features) >= max_features:
                break
        return features

    def _norm01(self, arr: np.ndarray) -> np.ndarray:
        valid = arr[np.isfinite(arr)]
        if valid.size == 0:
            return np.zeros_like(arr, dtype=np.float32)
        lo, hi = np.percentile(valid, [5, 95])
        return np.clip((arr - lo) / (hi - lo + 1e-9), 0, 1).astype(np.float32)

    def _cfar_peaks(
        self,
        intensity: np.ndarray,
        guard: int = 3,
        background: int = 9,
        pfa: float = 1e-4,
        mask: np.ndarray | None = None,
        max_peaks: int = 40,
    ) -> list[tuple[int, int, float]]:
        """Two-parameter cell-averaging CFAR (CA-CFAR)."""
        img = np.nan_to_num(intensity.astype(np.float32), nan=0.0)
        h, w = img.shape
        # Background mean via box filter; exclude guard with difference of boxes
        k_bg = 2 * background + 1
        k_gd = 2 * guard + 1
        blur_bg = cv2.blur(img, (k_bg, k_bg))
        blur_gd = cv2.blur(img, (k_gd, k_gd))
        # Approximate ring mean
        area_bg = float(k_bg * k_bg)
        area_gd = float(k_gd * k_gd)
        ring = (blur_bg * area_bg - blur_gd * area_gd) / max(area_bg - area_gd, 1.0)
        # Noise estimate from local MAD-ish via std of blurred residual
        sq = cv2.blur(img * img, (k_bg, k_bg))
        var = np.maximum(sq - blur_bg * blur_bg, 1e-8)
        sigma = np.sqrt(var)
        # Threshold: ring + alpha * sigma  (alpha from approximate Pfa)
        alpha = max(3.0, -math.log10(max(pfa, 1e-8)))
        thr = ring + alpha * sigma
        peaks = (img > thr) & (img > np.percentile(img, 85))
        if mask is not None:
            peaks = peaks & mask
        # Non-max suppression
        kernel = np.ones((5, 5), np.uint8)
        local_max = cv2.dilate(img, kernel) == img
        peaks = peaks & local_max
        ys, xs = np.where(peaks)
        scored = [(int(y), int(x), float(img[y, x])) for y, x in zip(ys, xs, strict=False)]
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:max_peaks]

    def _dog_blobs(
        self,
        intensity: np.ndarray,
        mask: np.ndarray | None = None,
        sigma_small: float = 1.2,
        sigma_large: float = 3.0,
        max_peaks: int = 40,
    ) -> list[tuple[int, int, float]]:
        img = np.nan_to_num(self._norm01(intensity), nan=0.0)
        g1 = cv2.GaussianBlur(img, (0, 0), sigma_small)
        g2 = cv2.GaussianBlur(img, (0, 0), sigma_large)
        dog = g1 - g2
        dog_u8 = self._to_u8(dog)
        # Local maxima
        dil = cv2.dilate(dog, np.ones((5, 5), np.uint8))
        peaks = (dog == dil) & (dog > np.percentile(dog, 90))
        if mask is not None:
            peaks = peaks & mask
        ys, xs = np.where(peaks)
        scored = [(int(y), int(x), float(dog[y, x])) for y, x in zip(ys, xs, strict=False)]
        scored.sort(key=lambda t: t[2], reverse=True)
        _ = dog_u8  # kept for potential debug
        return scored[:max_peaks]

    def _peaks_to_points(
        self,
        peaks: list[tuple[int, int, float]],
        score: np.ndarray,
        bounds: list[float],
        label: str,
        task: str,
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        h, w = score.shape
        for i, (r, c, raw) in enumerate(peaks):
            conf = float(np.clip(self._norm01(np.array([raw]))[0], 0.05, 0.99))
            # Blend with local score
            conf = float(np.clip(0.5 * conf + 0.5 * float(self._norm01(score)[r, c]), 0.05, 0.99))
            if conf < confidence_min:
                continue
            lon, lat = self._pixel_to_lonlat(r, c, (h, w), bounds)
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
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
        return features

    # ── dispatch ──────────────────────────────────────────────────────────

    def _dispatch(
        self,
        detector: str,
        task: str,
        meta: dict[str, Any],
        bands: dict[str, np.ndarray],
        bounds: list[float],
        confidence_min: float,
    ) -> list[dict[str, Any]]:
        label = meta["label"]
        handlers = {
            "buildings": self._det_buildings,
            "roads": self._det_roads,
            "railway": self._det_railway,
            "runway": self._det_runway,
            "corridor": self._det_corridor,
            "bridges": self._det_bridges,
            "ships": self._det_ships,
            "ships_sar": self._det_ships_sar,
            "dark_ships": self._det_dark_ships,
            "aircraft": self._det_aircraft,
            "vehicles": self._det_vehicles,
            "objects": self._det_objects,
            "water": self._det_water,
            "flood": self._det_flood,
            "oil": self._det_oil,
            "burn": self._det_burn,
            "fire": self._det_fire,
            "cloud": self._det_cloud,
            "solar": self._det_solar,
            "construction": self._det_construction,
            "vegetation": self._det_vegetation,
            "crops": self._det_crops,
            "deforest": self._det_deforest,
            "change": self._det_change,
            "lulc": self._det_lulc,
            "airport": self._det_airport,
            "airport_point": self._det_airport_point,
            "port": self._det_port,
            "lanes": self._det_lanes,
            "wake": self._det_wake,
            "shoreline": self._det_shoreline,
            "tidal": self._det_tidal,
            "sst": self._det_sst,
            "chl": self._det_chl,
            "wave": self._det_wave,
            "terrain": self._det_terrain,
            "wind": self._det_wind,
        }
        fn = handlers.get(detector, self._det_objects)
        return fn(task, label, bands, bounds, confidence_min)

    # ── specialized detectors ─────────────────────────────────────────────

    def _det_buildings(self, task, label, bands, bounds, conf_min):
        """Deep-learning-style MLP built-up classifier + morphological refine.

        Highlights only built-up / urban fabric (not vegetation, water, or bare soil).
        Uses a multi-layer perceptron on spectral + local texture features.
        """
        ndbi = self._ndbi(bands)
        ndvi = self._ndvi(bands)
        ndwi = self._water_index(bands)
        bsi = self._bsi(bands)
        inten = self._intensity(bands)
        if ndbi is None:
            raise ValidationError(
                "Building detection needs NIR+SWIR (Eye-On Sentinel-2 / Landsat optical)."
            )

        h, w = inten.shape
        n_ndvi = self._norm01(ndvi) if ndvi is not None else np.zeros((h, w), dtype=np.float32)
        n_ndbi = self._norm01(ndbi)
        n_ndwi = self._norm01(ndwi) if ndwi is not None else np.zeros((h, w), dtype=np.float32)
        n_bsi = self._norm01(bsi) if bsi is not None else np.zeros((h, w), dtype=np.float32)
        n_int = self._norm01(inten)

        # Local texture (std) + Sobel edge — built-up tends to be textured
        mu = cv2.blur(np.nan_to_num(inten), (7, 7))
        mu2 = cv2.blur(np.nan_to_num(inten) ** 2, (7, 7))
        tex = self._norm01(np.sqrt(np.maximum(mu2 - mu * mu, 0)))
        gx = cv2.Sobel(np.nan_to_num(inten), cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(np.nan_to_num(inten), cv2.CV_32F, 0, 1, ksize=3)
        edge = self._norm01(np.hypot(gx, gy))

        # Feature stack: [NDVI, NDBI, NDWI, BSI, intensity, texture, edge]
        X = np.stack([n_ndvi, n_ndbi, n_ndwi, n_bsi, n_int, tex, edge], axis=-1).reshape(-1, 7)

        # Pseudo-labels for built-up vs background (spectral decision rules)
        # Built-up: high NDBI, low NDVI, low water, not extreme bare-soil only
        built = (
            (n_ndbi > 0.45)
            & (n_ndvi < 0.40)
            & (n_ndwi < 0.35)
            & (n_int > 0.15)
        )
        # Strong non-built priors
        veg = n_ndvi > 0.45
        water = n_ndwi > 0.45
        dark = n_int < 0.08
        y = np.full(h * w, -1, dtype=np.int32)
        y[built.reshape(-1)] = 1
        y[(veg | water | dark).reshape(-1)] = 0
        # Ambiguous mid pixels: leave unlabeled (-1)

        labeled = y >= 0
        if labeled.sum() < 200:
            # Fallback spectral MBI if scene has too few clear training pixels
            score = n_ndbi * (1.0 - 0.6 * n_ndvi) * (0.4 + 0.6 * n_int)
            u8 = self._to_u8(score)
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
            tophat = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT, k)
            mask = self._otsu_mask(tophat.astype(np.float32))
            mask = mask & (n_ndvi < 0.45) & (n_ndwi < 0.40)
            mask = self._morph_clean(mask, open_k=3, close_k=7)
            return self._contour_polygons(
                mask, score, bounds, label, task, conf_min, min_area=40, max_features=60
            )

        rng = np.random.default_rng(42)
        idx = np.where(labeled)[0]
        # Balance classes
        pos = idx[y[idx] == 1]
        neg = idx[y[idx] == 0]
        n = min(4000, len(pos), len(neg))
        if n < 80:
            n = min(len(pos), len(neg), 4000)
        if n < 40:
            raise ValidationError(
                "Not enough built-up spectral contrast in this scene for Building Detection. "
                "Try a clearer optical scene over an urban area."
            )
        sel = np.concatenate(
            [
                rng.choice(pos, size=min(n, len(pos)), replace=False),
                rng.choice(neg, size=min(n, len(neg)), replace=False),
            ]
        )
        rng.shuffle(sel)

        # Multi-layer perceptron (neural network) — built-up vs non-built
        clf = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            solver="adam",
            max_iter=120,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=8,
        )
        clf.fit(X[sel], y[sel])
        proba = clf.predict_proba(X)[:, list(clf.classes_).index(1)].reshape(h, w)

        # Built-up probability mask — require ML confidence AND urban spectral prior
        thr = max(0.55, float(conf_min))
        mask = (proba >= thr) & (n_ndvi < 0.42) & (n_ndwi < 0.38)
        # Morphological Building Index refine: top-hat on ML score
        u8 = self._to_u8(proba)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        tophat = cv2.morphologyEx(u8, cv2.MORPH_TOPHAT, k)
        mask = mask | ((tophat > 18) & (n_ndbi > 0.40) & (n_ndvi < 0.40) & (n_ndwi < 0.35))
        mask = self._morph_clean(mask, open_k=3, close_k=7)
        # Drop tiny speckles; keep compact urban patches
        mask_u8 = (mask.astype(np.uint8) * 255)
        nlab, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
        clean = np.zeros_like(mask)
        min_area = max(35, int(0.00015 * h * w))
        for i in range(1, nlab):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= min_area:
                clean[labels == i] = True
        return self._contour_polygons(
            clean,
            proba,
            bounds,
            label,
            task,
            conf_min,
            min_area=min_area,
            max_features=80,
        )

    def _det_roads(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        inten = self._intensity(bands)
        # Spectral road cue: bright, low vegetation
        road = self._norm01(inten)
        if ndvi is not None:
            road = road * (1.0 - self._norm01(ndvi))
        u8 = self._to_u8(road)
        blur = cv2.GaussianBlur(u8, (5, 5), 0)
        edges = cv2.Canny(blur, 40, 120)
        return self._hough_lines(
            edges,
            bounds,
            label,
            task,
            conf_min,
            min_line_length=35,
            max_line_gap=10,
            threshold=35,
            score_map=road,
        )

    def _det_railway(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        u8 = self._to_u8(inten)
        edges = cv2.Canny(cv2.GaussianBlur(u8, (3, 3), 0), 50, 140)
        # Prefer thinner features: erode edges slightly
        edges = cv2.erode(edges, np.ones((2, 2), np.uint8), iterations=1)
        return self._hough_lines(
            edges,
            bounds,
            label,
            task,
            conf_min,
            min_line_length=45,
            max_line_gap=8,
            threshold=45,
            score_map=inten,
        )

    def _det_runway(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        inten = self._intensity(bands)
        pavement = self._norm01(inten)
        if ndvi is not None:
            pavement = pavement * (1.0 - self._norm01(ndvi))
        u8 = self._to_u8(pavement)
        # Strong long lines
        edges = cv2.Canny(cv2.GaussianBlur(u8, (5, 5), 0), 60, 160)
        return self._hough_lines(
            edges,
            bounds,
            label,
            task,
            conf_min,
            min_line_length=80,
            max_line_gap=15,
            threshold=55,
            max_features=12,
            score_map=pavement,
        )

    def _det_corridor(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        if ndvi is None:
            raise ValidationError("Corridor mapping needs NIR+Red")
        # Cleared vegetation corridors = low NDVI linear features
        clearing = 1.0 - self._norm01(ndvi)
        u8 = self._to_u8(clearing)
        edges = cv2.Canny(cv2.GaussianBlur(u8, (5, 5), 0), 40, 110)
        return self._hough_lines(
            edges, bounds, label, task, conf_min, min_line_length=50, score_map=clearing
        )

    def _det_bridges(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        inten = self._intensity(bands)
        if ndwi is None:
            raise ValidationError("Bridge detection needs Green+NIR/SWIR")
        water = self._otsu_mask(ndwi)
        water = self._morph_clean(water, open_k=3, close_k=7)
        # Dilate water so bridges near shore are included
        water_d = cv2.dilate(water.astype(np.uint8), np.ones((9, 9), np.uint8), iterations=1) > 0
        u8 = self._to_u8(inten)
        edges = cv2.Canny(cv2.GaussianBlur(u8, (3, 3), 0), 50, 140)
        edges = edges * water_d.astype(np.uint8)
        return self._hough_lines(
            edges,
            bounds,
            label,
            task,
            conf_min,
            min_line_length=25,
            max_line_gap=8,
            threshold=25,
            max_features=20,
            score_map=inten,
        )

    def _det_ships(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        inten = self._intensity(bands)
        if ndwi is None:
            raise ValidationError("Ship detection needs water index bands")
        water = self._otsu_mask(ndwi)
        water = self._morph_clean(water, open_k=2, close_k=5)
        peaks = self._cfar_peaks(inten, guard=2, background=10, pfa=5e-4, mask=water)
        return self._peaks_to_points(peaks, inten, bounds, label, task, conf_min)

    def _det_ships_sar(self, task, label, bands, bounds, conf_min):
        # Optical proxy when SAR bands unavailable: CFAR on intensity, prefer water
        inten = self._intensity(bands)
        ndwi = self._water_index(bands)
        mask = self._otsu_mask(ndwi) if ndwi is not None else None
        peaks = self._cfar_peaks(inten, guard=3, background=12, pfa=1e-4, mask=mask)
        return self._peaks_to_points(peaks, inten, bounds, label, task, conf_min)

    def _det_dark_ships(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        inten = self._intensity(bands)
        if ndwi is None:
            raise ValidationError("Dark vessel detection needs water bands")
        water = self._otsu_mask(ndwi)
        # Inverse CFAR on dark targets
        peaks = self._cfar_peaks(-inten, guard=2, background=10, pfa=5e-4, mask=water)
        return self._peaks_to_points(peaks, -inten, bounds, label, task, conf_min)

    def _det_aircraft(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        ndbi = self._ndbi(bands)
        inten = self._intensity(bands)
        apron = np.ones(inten.shape, dtype=bool)
        if ndvi is not None:
            apron &= self._norm01(ndvi) < 0.35
        if ndbi is not None:
            apron &= self._norm01(ndbi) > 0.35
        # If apron too empty, relax to low-NDVI bright areas
        if apron.sum() < 50 and ndvi is not None:
            apron = self._norm01(ndvi) < 0.4
        peaks = self._dog_blobs(inten, mask=apron, sigma_small=1.0, sigma_large=2.8)
        return self._peaks_to_points(peaks, inten, bounds, label, task, conf_min)

    def _det_vehicles(self, task, label, bands, bounds, conf_min):
        nir = self._band(bands, "nir")
        swir = self._band(bands, "swir", "swir2")
        inten = self._intensity(bands)
        residual = inten
        if nir is not None and swir is not None:
            residual = np.abs(swir - nir)
        peaks = self._dog_blobs(residual, sigma_small=0.8, sigma_large=2.0, max_peaks=50)
        return self._peaks_to_points(peaks, residual, bounds, label, task, conf_min)

    def _det_objects(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        peaks = self._dog_blobs(inten, sigma_small=1.5, sigma_large=4.0, max_peaks=50)
        return self._peaks_to_points(peaks, inten, bounds, label, task, conf_min)

    def _det_wind(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        peaks = self._dog_blobs(inten, sigma_small=1.2, sigma_large=3.5, max_peaks=30)
        return self._peaks_to_points(peaks, inten, bounds, label, task, conf_min)

    def _det_water(self, task, label, bands, bounds, conf_min):
        water_idx = self._water_index(bands)
        if water_idx is None:
            raise ValidationError("Water extraction needs Green+NIR/SWIR")
        mask = self._otsu_mask(water_idx)
        mask = self._morph_clean(mask, open_k=3, close_k=7)
        return self._contour_polygons(
            mask, water_idx, bounds, label, task, conf_min, min_area=60
        )

    def _det_flood(self, task, label, bands, bounds, conf_min):
        # Flood ≈ expansive water; use slightly lower threshold + larger morph close
        water_idx = self._water_index(bands)
        if water_idx is None:
            raise ValidationError("Flood detection needs water index bands")
        u8 = self._to_u8(water_idx)
        thr, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = u8 >= max(0, int(thr) - 12)
        mask = self._morph_clean(mask, open_k=2, close_k=11)
        return self._contour_polygons(
            mask, water_idx, bounds, label, task, conf_min, min_area=80
        )

    def _det_oil(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        nir = self._band(bands, "nir")
        swir = self._band(bands, "swir", "swir2")
        if ndwi is None or nir is None:
            raise ValidationError("Oil spill detection needs water + NIR")
        water = self._otsu_mask(ndwi)
        dark = -self._norm01(nir)
        if swir is not None:
            dark = 0.5 * dark + 0.5 * (-self._norm01(swir))
        score = dark * water.astype(np.float32)
        mask = score > np.percentile(score[water], 85) if water.any() else score > 0.7
        mask = self._morph_clean(mask & water, open_k=2, close_k=5)
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=30)

    def _det_burn(self, task, label, bands, bounds, conf_min):
        nbr = self._nbr(bands)
        if nbr is None:
            raise ValidationError("Burn scar detection needs NIR+SWIR")
        # Low NBR = burn
        mask = self._otsu_mask(nbr, invert=True)
        mask = self._morph_clean(mask, open_k=3, close_k=7)
        score = -nbr
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=50)

    def _det_fire(self, task, label, bands, bounds, conf_min):
        swir = self._band(bands, "swir", "swir2")
        thermal = self._band(bands, "thermal")
        hot = swir if swir is not None else thermal
        if hot is None:
            hot = self._intensity(bands)
        peaks = self._cfar_peaks(hot, guard=2, background=8, pfa=1e-4)
        return self._peaks_to_points(peaks, hot, bounds, label, task, conf_min)

    def _det_cloud(self, task, label, bands, bounds, conf_min):
        blue = self._band(bands, "blue")
        nir = self._band(bands, "nir")
        inten = self._intensity(bands)
        score = self._norm01(inten)
        if blue is not None and nir is not None:
            ratio = self._safe_div(blue, nir + 1e-6)
            score = 0.5 * score + 0.5 * self._norm01(ratio)
        mask = self._otsu_mask(score)
        mask = self._morph_clean(mask, open_k=3, close_k=9)
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=40)

    def _det_solar(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        ndvi = self._ndvi(bands)
        # Dark panels, low vegetation
        dark = 1.0 - self._norm01(inten)
        if ndvi is not None:
            dark = dark * (1.0 - 0.5 * self._norm01(ndvi))
        mask = self._otsu_mask(dark)
        mask = self._morph_clean(mask, open_k=3, close_k=5)
        # Prefer rectangular-ish contours
        feats = self._contour_polygons(
            mask, dark, bounds, label, task, conf_min, min_area=40, max_features=40
        )
        filtered = []
        for f in feats:
            ring = f["geometry"]["coordinates"][0]
            if len(ring) <= 8:  # roughly rectangular after approx
                filtered.append(f)
            elif f["properties"].get("area_px", 0) > 200:
                filtered.append(f)
        return filtered or feats

    def _det_construction(self, task, label, bands, bounds, conf_min):
        bsi = self._bsi(bands)
        if bsi is None:
            ndbi = self._ndbi(bands)
            if ndbi is None:
                raise ValidationError("Construction detection needs BSI/NDBI bands")
            bsi = ndbi
        mask = self._otsu_mask(bsi)
        mask = self._morph_clean(mask, open_k=3, close_k=5)
        return self._contour_polygons(mask, bsi, bounds, label, task, conf_min, min_area=40)

    def _det_vegetation(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        if ndvi is None:
            raise ValidationError("Vegetation classification needs NIR+Red")
        features: list[dict[str, Any]] = []
        bins = [
            ("sparse", 0.2, 0.4),
            ("moderate", 0.4, 0.6),
            ("dense", 0.6, 1.01),
        ]
        for name, lo, hi in bins:
            mask = (ndvi >= lo) & (ndvi < hi)
            mask = self._morph_clean(mask, open_k=2, close_k=3)
            features.extend(
                self._contour_polygons(
                    mask,
                    ndvi,
                    bounds,
                    label,
                    task,
                    conf_min,
                    min_area=50,
                    max_features=20,
                    class_name=name,
                )
            )
        return features[:60]

    def _det_crops(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        if ndvi is None:
            raise ValidationError("Crop classification needs NIR+Red")
        agri = (ndvi > 0.35) & (ndvi < 0.85)
        agri = self._morph_clean(agri, open_k=3, close_k=5)
        # Watershed-like separation via distance transform
        u8 = (agri.astype(np.uint8) * 255)
        dist = cv2.distanceTransform(u8, cv2.DIST_L2, 5)
        _, sure = cv2.threshold(dist, 0.35 * dist.max() if dist.max() > 0 else 0, 255, 0)
        sure = np.uint8(sure)
        unknown = cv2.subtract(u8, sure)
        _, markers = cv2.connectedComponents(sure)
        markers = markers + 1
        markers[unknown == 255] = 0
        color = cv2.cvtColor(u8, cv2.COLOR_GRAY2BGR)
        markers = cv2.watershed(color, markers)
        features: list[dict[str, Any]] = []
        for mid in range(2, int(markers.max()) + 1):
            mask = markers == mid
            if mask.sum() < 40:
                continue
            features.extend(
                self._contour_polygons(
                    mask, ndvi, bounds, label, task, conf_min, min_area=40, max_features=1
                )
            )
            if len(features) >= 40:
                break
        return features or self._contour_polygons(
            agri, ndvi, bounds, label, task, conf_min, min_area=60
        )

    def _det_deforest(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        if ndvi is None:
            raise ValidationError("Deforestation detection needs NIR+Red")
        # Low NDVI patches amid higher vegetation context
        low = ndvi < np.nanpercentile(ndvi[np.isfinite(ndvi)], 30)
        ctx = cv2.blur(self._norm01(ndvi), (21, 21))
        mask = low & (ctx > 0.35)
        mask = self._morph_clean(mask, open_k=3, close_k=5)
        return self._contour_polygons(
            mask, -ndvi, bounds, label, task, conf_min, min_area=40
        )

    def _det_change(self, task, label, bands, bounds, conf_min):
        ndvi = self._ndvi(bands)
        inten = self._intensity(bands)
        if ndvi is None:
            score = np.abs(inten - cv2.blur(np.nan_to_num(inten), (15, 15)))
        else:
            local = cv2.blur(np.nan_to_num(ndvi), (15, 15))
            score = np.abs(ndvi - local)
        mask = score > np.nanpercentile(score, 88)
        mask = self._morph_clean(mask, open_k=2, close_k=5)
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=35)

    def _det_lulc(self, task, label, bands, bounds, conf_min):
        """RandomForest land-cover on spectral + texture features."""
        ndvi = self._ndvi(bands)
        ndwi = self._ndwi(bands)
        ndbi = self._ndbi(bands)
        bsi = self._bsi(bands)
        inten = self._intensity(bands)
        h, w = inten.shape
        # Feature stack
        feats = [self._norm01(inten)]
        for arr in (ndvi, ndwi, ndbi, bsi):
            feats.append(
                self._norm01(arr) if arr is not None else np.zeros((h, w), dtype=np.float32)
            )
        # Local texture (std)
        mu = cv2.blur(np.nan_to_num(inten), (7, 7))
        mu2 = cv2.blur(np.nan_to_num(inten) ** 2, (7, 7))
        tex = np.sqrt(np.maximum(mu2 - mu * mu, 0))
        feats.append(self._norm01(tex))
        X_img = np.stack(feats, axis=-1)  # H,W,C
        # Pseudo-labels from spectral rules to train RF (supervised spectral ML)
        y = np.full((h, w), -1, dtype=np.int32)
        names = ["water", "vegetation", "built-up", "bare", "other"]
        if ndwi is not None:
            y[ndwi > 0.15] = 0
        if ndvi is not None:
            y[(ndvi > 0.35) & (y < 0)] = 1
        if ndbi is not None:
            y[(ndbi > 0.05) & (y < 0)] = 2
        if bsi is not None:
            y[(bsi > 0.1) & (y < 0)] = 3
        y[y < 0] = 4
        # Sample train pixels
        rng = np.random.default_rng(42)
        flat_X = X_img.reshape(-1, X_img.shape[-1])
        flat_y = y.reshape(-1)
        idx = rng.choice(flat_X.shape[0], size=min(8000, flat_X.shape[0]), replace=False)
        clf = RandomForestClassifier(
            n_estimators=60, max_depth=12, min_samples_leaf=5, n_jobs=1, random_state=42
        )
        clf.fit(flat_X[idx], flat_y[idx])
        pred = clf.predict(flat_X).reshape(h, w)
        proba = clf.predict_proba(flat_X).reshape(h, w, -1)
        features: list[dict[str, Any]] = []
        for ci, cname in enumerate(names):
            if ci >= proba.shape[-1]:
                break
            mask = pred == ci
            mask = self._morph_clean(mask, open_k=2, close_k=3)
            score = proba[..., ci]
            features.extend(
                self._contour_polygons(
                    mask,
                    score,
                    bounds,
                    label,
                    task,
                    conf_min,
                    min_area=80,
                    max_features=15,
                    class_name=cname,
                )
            )
        return features[:70]

    def _det_airport(self, task, label, bands, bounds, conf_min):
        ndbi = self._ndbi(bands)
        ndvi = self._ndvi(bands)
        inten = self._intensity(bands)
        score = self._norm01(inten)
        if ndbi is not None:
            score = 0.5 * score + 0.5 * self._norm01(ndbi)
        if ndvi is not None:
            score = score * (1.0 - 0.4 * self._norm01(ndvi))
        mask = self._otsu_mask(score)
        mask = self._morph_clean(mask, open_k=5, close_k=11)
        polys = self._contour_polygons(
            mask, score, bounds, label, task, conf_min, min_area=200, max_features=8
        )
        # Also add runway axes
        runways = self._det_runway(task, "Runway", bands, bounds, conf_min)
        return polys + runways[:4]

    def _det_airport_point(self, task, label, bands, bounds, conf_min):
        polys = self._det_airport(task, label, bands, bounds, conf_min)
        points: list[dict[str, Any]] = []
        for i, f in enumerate(polys):
            if f["geometry"]["type"] != "Polygon":
                continue
            ring = f["geometry"]["coordinates"][0]
            lon = sum(p[0] for p in ring[:-1]) / max(len(ring) - 1, 1)
            lat = sum(p[1] for p in ring[:-1]) / max(len(ring) - 1, 1)
            points.append(
                {
                    "type": "Feature",
                    "properties": {
                        **f["properties"],
                        "id": f"{task}_pt_{i}",
                        "label": label,
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
        return points[:5]

    def _det_port(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        ndbi = self._ndbi(bands)
        if ndwi is None:
            raise ValidationError("Port mapping needs water index bands")
        water = self._otsu_mask(ndwi)
        # Quay = built-up near water
        quay_score = self._norm01(ndbi) if ndbi is not None else self._norm01(self._intensity(bands))
        shore = cv2.dilate(water.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
        mask = (quay_score > np.percentile(quay_score, 70)) & shore & (~water)
        mask = self._morph_clean(mask, open_k=3, close_k=7)
        return self._contour_polygons(mask, quay_score, bounds, label, task, conf_min, min_area=50)

    def _det_lanes(self, task, label, bands, bounds, conf_min):
        ships = self._det_ships(task, "Ship", bands, bounds, max(0.3, conf_min - 0.1))
        # Build density from ship points then Hough
        inten = self._intensity(bands)
        dens = np.zeros_like(inten, dtype=np.float32)
        h, w = inten.shape
        for f in ships:
            lon, lat = f["geometry"]["coordinates"]
            west, south, east, north = bounds
            c = int((lon - west) / (east - west) * w)
            r = int((north - lat) / (north - south) * h)
            if 0 <= r < h and 0 <= c < w:
                cv2.circle(dens, (c, r), 8, 1.0, -1)
        dens = cv2.GaussianBlur(dens, (0, 0), 6)
        u8 = self._to_u8(dens)
        edges = cv2.Canny(u8, 30, 90)
        return self._hough_lines(
            edges, bounds, label, task, conf_min, min_line_length=40, threshold=20, score_map=dens
        )

    def _det_wake(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        inten = self._intensity(bands)
        if ndwi is None:
            return self._det_roads(task, label, bands, bounds, conf_min)
        water = self._otsu_mask(ndwi)
        residual = np.abs(inten - cv2.blur(np.nan_to_num(inten), (9, 9)))
        u8 = self._to_u8(residual * water.astype(np.float32))
        edges = cv2.Canny(u8, 40, 100)
        return self._hough_lines(
            edges, bounds, label, task, conf_min, min_line_length=20, threshold=20, score_map=residual
        )

    def _det_shoreline(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        if ndwi is None:
            raise ValidationError("Shoreline mapping needs water bands")
        water = self._otsu_mask(ndwi).astype(np.uint8) * 255
        edges = cv2.Canny(water, 50, 150)
        return self._hough_lines(
            edges, bounds, label, task, conf_min, min_line_length=30, threshold=25, score_map=ndwi
        )

    def _det_tidal(self, task, label, bands, bounds, conf_min):
        ndwi = self._water_index(bands)
        if ndwi is None:
            raise ValidationError("Tidal zone mapping needs water bands")
        # Fringe: mid NDWI
        n = self._norm01(ndwi)
        mask = (n > 0.25) & (n < 0.55)
        mask = self._morph_clean(mask, open_k=2, close_k=5)
        return self._contour_polygons(mask, ndwi, bounds, label, task, conf_min, min_area=40)

    def _det_sst(self, task, label, bands, bounds, conf_min):
        thermal = self._band(bands, "thermal")
        swir = self._band(bands, "swir", "swir2")
        score = thermal if thermal is not None else swir
        if score is None:
            score = self._intensity(bands)
        ndwi = self._water_index(bands)
        mask_base = self._otsu_mask(ndwi) if ndwi is not None else np.ones(score.shape, dtype=bool)
        # Relative warm / cool cells
        features: list[dict[str, Any]] = []
        for name, lo, hi in (("warm", 70, 100), ("cool", 0, 30)):
            p_lo, p_hi = np.nanpercentile(score[mask_base], [lo, hi]) if mask_base.any() else (0, 1)
            if name == "warm":
                mask = (score >= p_lo) & mask_base
            else:
                mask = (score <= p_hi) & mask_base
            mask = self._morph_clean(mask, open_k=3, close_k=5)
            features.extend(
                self._contour_polygons(
                    mask, score, bounds, label, task, conf_min, min_area=60, max_features=12, class_name=name
                )
            )
        return features

    def _det_chl(self, task, label, bands, bounds, conf_min):
        green, blue = self._band(bands, "green"), self._band(bands, "blue")
        ndwi = self._water_index(bands)
        if green is None or blue is None:
            raise ValidationError("Chlorophyll overlay needs blue+green")
        ratio = self._safe_div(green, blue + 1e-6)
        water = self._otsu_mask(ndwi) if ndwi is not None else np.ones(ratio.shape, dtype=bool)
        score = self._norm01(ratio) * water.astype(np.float32)
        mask = score > np.percentile(score[water], 75) if water.any() else score > 0.6
        mask = self._morph_clean(mask, open_k=2, close_k=5)
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=40)

    def _det_wave(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        ndwi = self._water_index(bands)
        water = self._otsu_mask(ndwi) if ndwi is not None else np.ones(inten.shape, dtype=bool)
        mu = cv2.blur(np.nan_to_num(inten), (9, 9))
        mu2 = cv2.blur(np.nan_to_num(inten) ** 2, (9, 9))
        var = np.sqrt(np.maximum(mu2 - mu * mu, 0))
        score = self._norm01(var) * water.astype(np.float32)
        mask = score > np.percentile(score[water], 70) if water.any() else score > 0.5
        mask = self._morph_clean(mask, open_k=2, close_k=5)
        return self._contour_polygons(mask, score, bounds, label, task, conf_min, min_area=50)

    def _det_terrain(self, task, label, bands, bounds, conf_min):
        inten = self._intensity(bands)
        gx = cv2.Sobel(np.nan_to_num(inten), cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(np.nan_to_num(inten), cv2.CV_32F, 0, 1, ksize=3)
        mag = np.hypot(gx, gy)
        mask = self._otsu_mask(mag)
        mask = self._morph_clean(mask, open_k=3, close_k=5)
        return self._contour_polygons(mask, mag, bounds, label, task, conf_min, min_area=50)

    # ── overlay / legend / bounds ─────────────────────────────────────────

    def _confidence_heatmap(
        self,
        bounds: list[float],
        features: list[dict[str, Any]],
        bands: dict[str, np.ndarray],
        size: int = 512,
    ) -> bytes:
        """Render confidence field from detection score / feature locations."""
        h = w = size
        field = np.zeros((h, w), dtype=np.float32)
        for f in features:
            conf = float(f.get("properties", {}).get("confidence", 0.5))
            geom = f.get("geometry") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            if not coords:
                continue
            if gtype == "Point":
                lon, lat = coords[0], coords[1]
                c = int((lon - bounds[0]) / (bounds[2] - bounds[0]) * w)
                r = int((bounds[3] - lat) / (bounds[3] - bounds[1]) * h)
                if 0 <= r < h and 0 <= c < w:
                    cv2.circle(field, (c, r), 10, conf, -1)
            elif gtype == "LineString":
                pts = []
                for lon, lat in coords:
                    c = int((lon - bounds[0]) / (bounds[2] - bounds[0]) * w)
                    r = int((bounds[3] - lat) / (bounds[3] - bounds[1]) * h)
                    pts.append([c, r])
                if len(pts) >= 2:
                    cv2.polylines(
                        field,
                        [np.array(pts, dtype=np.int32)],
                        False,
                        conf,
                        3,
                    )
            elif gtype == "Polygon":
                ring = coords[0]
                pts = []
                for lon, lat in ring:
                    c = int((lon - bounds[0]) / (bounds[2] - bounds[0]) * w)
                    r = int((bounds[3] - lat) / (bounds[3] - bounds[1]) * h)
                    pts.append([c, r])
                if len(pts) >= 3:
                    cv2.fillPoly(field, [np.array(pts, dtype=np.int32)], conf)
        field = cv2.GaussianBlur(field, (0, 0), 3)
        # Tint with intensity for context
        try:
            inten = self._to_u8(self._intensity(bands))
            if inten.shape != field.shape:
                inten = cv2.resize(inten, (w, h))
        except Exception:  # noqa: BLE001
            inten = np.zeros((h, w), dtype=np.uint8)
        heat = self._to_u8(field)
        color = cv2.applyColorMap(heat, cv2.COLORMAP_TURBO)
        color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
        alpha = np.clip(heat.astype(np.float32) * 0.9, 0, 220).astype(np.uint8)
        # Mix faint grayscale context
        base = np.stack([inten, inten, inten], axis=-1)
        mix = (
            base.astype(np.float32) * (1 - alpha[..., None] / 255.0)
            + color.astype(np.float32) * (alpha[..., None] / 255.0)
        ).astype(np.uint8)
        rgba = np.dstack([mix, np.maximum(alpha, (inten > 0).astype(np.uint8) * 40)])
        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _legend(self, label: str, algorithm: str) -> LegendInfo:
        return LegendInfo(
            min=0.0,
            max=1.0,
            unit="score",
            label=f"{label} confidence",
            formula=algorithm,
            colormap="turbo",
            stops=[
                ColormapStop(value=0.0, color="#30123b"),
                ColormapStop(value=0.5, color="#a2fc3c"),
                ColormapStop(value=1.0, color="#7a0403"),
            ],
        )

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
                return [minx, miny, maxx, maxy]
            except Exception:  # noqa: BLE001
                pass
        raise ValidationError("Detection requires a valid bbox or AOI")
