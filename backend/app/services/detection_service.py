"""Deterministic demo detectors for AI / maritime / air-domain toolbox tools."""

from __future__ import annotations

import base64
import hashlib
import io
import math
from typing import Any

import numpy as np
from PIL import Image

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.detection import DetectionRunRequest, DetectionRunResponse

# Task metadata: label, geometry kind, typical count range
TASK_META: dict[str, dict[str, Any]] = {
    # AI Detection
    "building_detection": {
        "label": "Building",
        "kind": "polygon",
        "count": (8, 22),
        "domain": "ai",
    },
    "road_extraction": {
        "label": "Road",
        "kind": "line",
        "count": (4, 10),
        "domain": "ai",
    },
    "vehicle_detection": {
        "label": "Vehicle",
        "kind": "point",
        "count": (12, 36),
        "domain": "ai",
    },
    "change_detection": {
        "label": "Change",
        "kind": "polygon",
        "count": (3, 9),
        "domain": "ai",
    },
    "flood_detection": {
        "label": "Flood",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "ai",
    },
    "land_cover_classification": {
        "label": "Land cover",
        "kind": "polygon",
        "count": (5, 12),
        "domain": "ai",
    },
    "object_detection": {
        "label": "Object",
        "kind": "point",
        "count": (10, 28),
        "domain": "ai",
    },
    "deforestation_detection": {
        "label": "Deforestation",
        "kind": "polygon",
        "count": (2, 7),
        "domain": "ai",
    },
    "fire_detection": {
        "label": "Fire / hot spot",
        "kind": "point",
        "count": (4, 14),
        "domain": "ai",
    },
    "crop_classification": {
        "label": "Crop parcel",
        "kind": "polygon",
        "count": (6, 16),
        "domain": "ai",
    },
    # Maritime
    "ship_detection": {
        "label": "Ship",
        "kind": "point",
        "count": (5, 18),
        "domain": "maritime",
    },
    "vessel_tracking": {
        "label": "Vessel track",
        "kind": "line",
        "count": (3, 8),
        "domain": "maritime",
    },
    "oil_spill_detection": {
        "label": "Oil spill",
        "kind": "polygon",
        "count": (1, 4),
        "domain": "maritime",
    },
    "wake_detection": {
        "label": "Wake",
        "kind": "line",
        "count": (3, 9),
        "domain": "maritime",
    },
    "port_activity_monitoring": {
        "label": "Port berth",
        "kind": "polygon",
        "count": (4, 12),
        "domain": "maritime",
    },
    "dark_vessel_detection": {
        "label": "Dark vessel",
        "kind": "point",
        "count": (2, 8),
        "domain": "maritime",
    },
    "maritime_domain_awareness": {
        "label": "Maritime contact",
        "kind": "point",
        "count": (8, 24),
        "domain": "maritime",
    },
    # Air Domain
    "aircraft_detection": {
        "label": "Aircraft",
        "kind": "point",
        "count": (3, 12),
        "domain": "air",
    },
    "airport_detection": {
        "label": "Airport",
        "kind": "polygon",
        "count": (1, 3),
        "domain": "air",
    },
    "runway_extraction": {
        "label": "Runway",
        "kind": "line",
        "count": (1, 4),
        "domain": "air",
    },
    "airfield_monitoring": {
        "label": "Airfield asset",
        "kind": "polygon",
        "count": (3, 10),
        "domain": "air",
    },
    "helicopter_detection": {
        "label": "Helicopter",
        "kind": "point",
        "count": (2, 8),
        "domain": "air",
    },
    "uav_detection": {
        "label": "UAV",
        "kind": "point",
        "count": (4, 16),
        "domain": "air",
    },
    # Extra AI / infrastructure (Light Explorer toolbox)
    "bridge_detection": {"label": "Bridge", "kind": "line", "count": (2, 6), "domain": "ai"},
    "airport_mapping": {"label": "Airport", "kind": "polygon", "count": (1, 3), "domain": "ai"},
    "runway_detection": {"label": "Runway", "kind": "line", "count": (1, 4), "domain": "ai"},
    "port_mapping": {"label": "Port", "kind": "polygon", "count": (2, 6), "domain": "ai"},
    "harbor_detection": {"label": "Harbor", "kind": "polygon", "count": (2, 5), "domain": "ai"},
    "railway_detection": {"label": "Railway", "kind": "line", "count": (3, 8), "domain": "ai"},
    "powerline_corridor_mapping": {
        "label": "Powerline corridor",
        "kind": "line",
        "count": (2, 7),
        "domain": "ai",
    },
    "solar_farm_detection": {
        "label": "Solar farm",
        "kind": "polygon",
        "count": (2, 8),
        "domain": "ai",
    },
    "wind_farm_detection": {
        "label": "Wind farm",
        "kind": "point",
        "count": (6, 20),
        "domain": "ai",
    },
    "construction_site_detection": {
        "label": "Construction site",
        "kind": "polygon",
        "count": (2, 7),
        "domain": "ai",
    },
    "urban_expansion_detection": {
        "label": "Urban expansion",
        "kind": "polygon",
        "count": (3, 9),
        "domain": "ai",
    },
    "vegetation_classification": {
        "label": "Vegetation class",
        "kind": "polygon",
        "count": (5, 14),
        "domain": "ai",
    },
    "burn_scar_detection": {
        "label": "Burn scar",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "ai",
    },
    "water_body_extraction": {
        "label": "Water body",
        "kind": "polygon",
        "count": (3, 10),
        "domain": "ai",
    },
    "confidence_heatmap": {
        "label": "Confidence",
        "kind": "point",
        "count": (15, 40),
        "domain": "ai",
    },
    # Maritime extras
    "ship_detection_sar": {"label": "Ship (SAR)", "kind": "point", "count": (6, 20), "domain": "maritime"},
    "ship_detection_optical": {
        "label": "Ship (optical)",
        "kind": "point",
        "count": (5, 18),
        "domain": "maritime",
    },
    "vessel_density_map": {
        "label": "Vessel density",
        "kind": "point",
        "count": (20, 50),
        "domain": "maritime",
    },
    "port_activity_mapping": {
        "label": "Port activity",
        "kind": "polygon",
        "count": (4, 12),
        "domain": "maritime",
    },
    "anchorage_detection": {
        "label": "Anchorage",
        "kind": "point",
        "count": (4, 14),
        "domain": "maritime",
    },
    "shipping_lane_visualization": {
        "label": "Shipping lane",
        "kind": "line",
        "count": (2, 6),
        "domain": "maritime",
    },
    "sea_surface_temperature": {
        "label": "SST cell",
        "kind": "polygon",
        "count": (8, 18),
        "domain": "maritime",
    },
    "chlorophyll_overlay": {
        "label": "Chlorophyll",
        "kind": "polygon",
        "count": (6, 16),
        "domain": "maritime",
    },
    "wave_height_overlay": {
        "label": "Wave height",
        "kind": "polygon",
        "count": (6, 14),
        "domain": "maritime",
    },
    "wind_speed_overlay": {
        "label": "Wind speed",
        "kind": "polygon",
        "count": (6, 14),
        "domain": "maritime",
    },
    "coastal_erosion_mapping": {
        "label": "Coastal erosion",
        "kind": "line",
        "count": (2, 6),
        "domain": "maritime",
    },
    "tidal_zone_mapping": {
        "label": "Tidal zone",
        "kind": "polygon",
        "count": (2, 5),
        "domain": "maritime",
    },
    # Air extras
    "airport_database": {"label": "Airport", "kind": "point", "count": (1, 4), "domain": "air"},
    "runway_inventory": {"label": "Runway", "kind": "line", "count": (1, 5), "domain": "air"},
    "airport_expansion_monitoring": {
        "label": "Airport expansion",
        "kind": "polygon",
        "count": (2, 6),
        "domain": "air",
    },
    "airspace_overlay": {"label": "Airspace", "kind": "polygon", "count": (2, 5), "domain": "air"},
    "notam_overlay": {"label": "NOTAM", "kind": "polygon", "count": (3, 9), "domain": "air"},
    "weather_overlay": {"label": "Weather cell", "kind": "polygon", "count": (4, 10), "domain": "air"},
    "terrain_awareness": {"label": "Terrain hazard", "kind": "polygon", "count": (3, 8), "domain": "air"},
    "visibility_analysis": {"label": "Visibility", "kind": "polygon", "count": (2, 6), "domain": "air"},
}


class DetectionService:
    """Synthetic but deterministic detections within an AOI bbox."""

    def list_tasks(self) -> list[dict[str, str]]:
        return [
            {
                "id": key,
                "name": meta["label"],
                "domain": meta["domain"],
                "geometry": meta["kind"],
            }
            for key, meta in TASK_META.items()
        ]

    def run(self, request: DetectionRunRequest) -> DetectionRunResponse:
        task = request.task.strip().lower().replace(" ", "_").replace("-", "_")
        bounds = self._resolve_bounds(request.bbox, request.aoi)
        west, south, east, north = bounds
        if east <= west or north <= south:
            raise ValidationError("Invalid bbox: east>west and north>south required")

        seed = self._seed(task, bounds)
        rng = np.random.default_rng(seed)
        # Unknown task ids still run with a generic detector so toolbox buttons always work
        meta = TASK_META.get(task) or {
            "label": task.replace("_", " ").title(),
            "kind": "polygon" if "map" in task or "zone" in task else "point",
            "count": (4, 12),
            "domain": "ai",
        }
        lo, hi = meta["count"]
        n = int(rng.integers(lo, hi + 1))

        features: list[dict[str, Any]] = []
        for i in range(n):
            conf = float(rng.uniform(0.35, 0.98))
            if conf < request.confidence_min:
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
                    },
                    "geometry": geom,
                }
            )

        heatmap = self._confidence_heatmap(bounds, features, size=256)
        overlay_b64 = base64.b64encode(heatmap).decode("ascii")
        legend = self._legend(meta["label"])

        return DetectionRunResponse(
            task=task,
            bounds=bounds,
            overlay_base64=overlay_b64,
            geojson={"type": "FeatureCollection", "features": features},
            count=len(features),
            legend=legend,
            message=f"{len(features)} {meta['label'].lower()} detections · conf≥{request.confidence_min}",
            formula="heuristic/demo detector on AOI",
        )

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
            # Prefer longer corridors for roads / runways / wakes
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

        # polygon — axis-aligned / lightly rotated rectangles
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
        """Semi-transparent RGBA confidence heatmap similar to terrain overlays."""
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
                # centroid-ish + vertices
                if ring:
                    lons = [c[0] for c in ring[:-1]]
                    lats = [c[1] for c in ring[:-1]]
                    pts = [(float(np.mean(lons)), float(np.mean(lats)))]
                    pts.extend((float(c[0]), float(c[1])) for c in ring[:-1: max(1, len(ring) // 4)])
            for lon, lat in pts:
                col = int(np.clip(round((lon - west) / (east - west + 1e-12) * (size - 1)), 0, size - 1))
                row = int(np.clip(round((north - lat) / (north - south + 1e-12) * (size - 1)), 0, size - 1))
                # Gaussian blob
                yy, xx = np.mgrid[0:size, 0:size]
                sigma = size * 0.045
                blob = np.exp(-((xx - col) ** 2 + (yy - row) ** 2) / (2 * sigma**2))
                heat += conf * blob

        if heat.max() > 0:
            heat = heat / heat.max()
        # Hot colormap: transparent → yellow → orange → red
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
        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _legend(self, label: str) -> LegendInfo:
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
            formula="heuristic/demo detector on AOI",
            stops=stops,
        )
