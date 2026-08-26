"""Offline basemaps, landmarks, DEM/DTM/DSM and vector reference layers for SAT EYE."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.core.config import get_settings


LANDMARKS: list[dict[str, Any]] = [
    {"name": "Mount Everest", "lon": 86.9250, "lat": 27.9881, "type": "peak", "elevation_m": 8849},
    {"name": "K2", "lon": 76.5133, "lat": 35.8825, "type": "peak", "elevation_m": 8611},
    {"name": "Kilimanjaro", "lon": 37.3556, "lat": -3.0674, "type": "peak", "elevation_m": 5895},
    {"name": "Aconcagua", "lon": -70.0109, "lat": -32.6532, "type": "peak", "elevation_m": 6961},
    {"name": "Denali", "lon": -151.0074, "lat": 63.0695, "type": "peak", "elevation_m": 6190},
    {"name": "Grand Canyon", "lon": -112.1401, "lat": 36.0544, "type": "landmark", "elevation_m": 2100},
    {"name": "Amazon River Mouth", "lon": -50.0, "lat": 0.0, "type": "hydro", "elevation_m": 0},
    {"name": "Nile Delta", "lon": 31.2357, "lat": 30.0444, "type": "hydro", "elevation_m": 10},
    {"name": "Sahara Desert", "lon": 10.0, "lat": 23.0, "type": "region", "elevation_m": 400},
    {"name": "Amazon Rainforest", "lon": -60.0, "lat": -3.0, "type": "region", "elevation_m": 100},
    {"name": "Great Barrier Reef", "lon": 147.7, "lat": -18.2871, "type": "hydro", "elevation_m": 0},
    {"name": "Victoria Falls", "lon": 25.8572, "lat": -17.9243, "type": "hydro", "elevation_m": 900},
    {"name": "Niagara Falls", "lon": -79.0750, "lat": 43.0828, "type": "hydro", "elevation_m": 170},
    {"name": "Lake Baikal", "lon": 108.0, "lat": 53.5, "type": "hydro", "elevation_m": 456},
    {"name": "Dead Sea", "lon": 35.5, "lat": 31.5, "type": "hydro", "elevation_m": -430},
    {"name": "Mariana Trench", "lon": 142.2, "lat": 11.35, "type": "ocean", "elevation_m": -10984},
    {"name": "New York City", "lon": -74.0060, "lat": 40.7128, "type": "city", "elevation_m": 10},
    {"name": "London", "lon": -0.1276, "lat": 51.5074, "type": "city", "elevation_m": 35},
    {"name": "Tokyo", "lon": 139.6917, "lat": 35.6895, "type": "city", "elevation_m": 40},
    {"name": "Cairo", "lon": 31.2357, "lat": 30.0444, "type": "city", "elevation_m": 23},
    {"name": "Sydney", "lon": 151.2093, "lat": -33.8688, "type": "city", "elevation_m": 58},
    {"name": "Cape Town", "lon": 18.4241, "lat": -33.9249, "type": "city", "elevation_m": 100},
    {"name": "Rio de Janeiro", "lon": -43.1729, "lat": -22.9068, "type": "city", "elevation_m": 20},
    {"name": "Mumbai", "lon": 72.8777, "lat": 19.0760, "type": "city", "elevation_m": 14},
    {"name": "Beijing", "lon": 116.4074, "lat": 39.9042, "type": "city", "elevation_m": 44},
    {"name": "Moscow", "lon": 37.6173, "lat": 55.7558, "type": "city", "elevation_m": 156},
    {"name": "Singapore", "lon": 103.8198, "lat": 1.3521, "type": "city", "elevation_m": 15},
    {"name": "Dubai", "lon": 55.2708, "lat": 25.2048, "type": "city", "elevation_m": 5},
    {"name": "Istanbul", "lon": 28.9784, "lat": 41.0082, "type": "city", "elevation_m": 100},
    {"name": "Mexico City", "lon": -99.1332, "lat": 19.4326, "type": "city", "elevation_m": 2240},
    {"name": "Los Angeles", "lon": -118.2437, "lat": 34.0522, "type": "city", "elevation_m": 93},
    {"name": "Paris", "lon": 2.3522, "lat": 48.8566, "type": "city", "elevation_m": 35},
    {"name": "Berlin", "lon": 13.4050, "lat": 52.5200, "type": "city", "elevation_m": 34},
    {"name": "Nairobi", "lon": 36.8219, "lat": -1.2921, "type": "city", "elevation_m": 1795},
    {"name": "Santiago", "lon": -70.6693, "lat": -33.4489, "type": "city", "elevation_m": 570},
    {"name": "Yellowstone", "lon": -110.5885, "lat": 44.4280, "type": "landmark", "elevation_m": 2400},
    {"name": "Uluru", "lon": 131.0369, "lat": -25.3444, "type": "landmark", "elevation_m": 863},
    {"name": "Machu Picchu", "lon": -72.5450, "lat": -13.1631, "type": "landmark", "elevation_m": 2430},
    {"name": "Petra", "lon": 35.4444, "lat": 30.3285, "type": "landmark", "elevation_m": 810},
    {"name": "Great Wall (Badaling)", "lon": 116.0169, "lat": 40.3560, "type": "landmark", "elevation_m": 700},
]


# Approximate continental outlines as simple polygons for offline basemap context
CONTINENT_OUTLINES: list[dict[str, Any]] = [
    {
        "name": "North America",
        "coordinates": [
            [-168, 65], [-140, 70], [-100, 72], [-60, 60], [-55, 45],
            [-80, 25], [-100, 15], [-120, 30], [-130, 50], [-168, 65],
        ],
    },
    {
        "name": "South America",
        "coordinates": [
            [-80, 10], [-50, 5], [-35, -5], [-40, -25], [-55, -55],
            [-70, -55], [-75, -40], [-80, -10], [-80, 10],
        ],
    },
    {
        "name": "Europe",
        "coordinates": [
            [-10, 35], [0, 50], [20, 70], [40, 65], [40, 40],
            [25, 35], [10, 35], [-10, 35],
        ],
    },
    {
        "name": "Africa",
        "coordinates": [
            [-18, 20], [10, 35], [35, 30], [50, 10], [40, -35],
            [20, -35], [10, 0], [-15, 5], [-18, 20],
        ],
    },
    {
        "name": "Asia",
        "coordinates": [
            [40, 40], [60, 55], [100, 70], [140, 60], [145, 40],
            [120, 10], [100, 5], [70, 20], [50, 25], [40, 40],
        ],
    },
    {
        "name": "Australia",
        "coordinates": [
            [112, -20], [130, -12], [145, -15], [153, -28],
            [145, -38], [115, -35], [112, -20],
        ],
    },
]


class OfflineLayersService:
    """Generate and serve fully offline reference layers for SAT EYE."""

    def __init__(self) -> None:
        settings = get_settings()
        self.root = settings.offline_data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.basemap_dir = self.root / "basemap"
        self.dem_dir = self.root / "dem"
        self.vector_dir = self.root / "vector"
        for d in (self.basemap_dir, self.dem_dir, self.vector_dir):
            d.mkdir(parents=True, exist_ok=True)

    def ensure_seed_data(self) -> dict[str, Any]:
        """Create offline basemap tiles, DEM GeoTIFFs, and vector GeoJSON if missing."""
        created: list[str] = []
        landmarks_path = self.vector_dir / "landmarks.geojson"
        if not landmarks_path.exists():
            landmarks_path.write_text(json.dumps(self.landmarks_geojson(), indent=2))
            created.append("landmarks.geojson")

        continents_path = self.vector_dir / "continents.geojson"
        if not continents_path.exists():
            continents_path.write_text(json.dumps(self.continents_geojson(), indent=2))
            created.append("continents.geojson")

        coasts_path = self.vector_dir / "coastlines.geojson"
        if not coasts_path.exists():
            coasts_path.write_text(json.dumps(self.continents_geojson(as_lines=True), indent=2))
            created.append("coastlines.geojson")

        grid_path = self.vector_dir / "graticule.geojson"
        if not grid_path.exists():
            grid_path.write_text(json.dumps(self.graticule_geojson(), indent=2))
            created.append("graticule.geojson")

        for kind in ("dem", "dtm", "dsm"):
            path = self.dem_dir / f"sample_{kind}.tif"
            if not path.exists():
                self._write_sample_elevation(path, kind=kind)
                created.append(path.name)

        tile_marker = self.basemap_dir / ".seeded"
        if not tile_marker.exists():
            self._generate_basemap_tiles()
            tile_marker.write_text("ok")
            created.append("basemap_tiles")

        catalog_path = self.root / "layer_catalog.json"
        catalog = self.list_layers()
        catalog_path.write_text(json.dumps(catalog, indent=2))
        return {"created": created, "layers": len(catalog)}

    def landmarks_geojson(self) -> dict[str, Any]:
        features = []
        for lm in LANDMARKS:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lm["lon"], lm["lat"]]},
                    "properties": {
                        "name": lm["name"],
                        "type": lm["type"],
                        "elevation_m": lm["elevation_m"],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def continents_geojson(self, as_lines: bool = False) -> dict[str, Any]:
        features = []
        for c in CONTINENT_OUTLINES:
            coords = c["coordinates"]
            if as_lines:
                geom = {"type": "LineString", "coordinates": coords}
            else:
                geom = {"type": "Polygon", "coordinates": [coords]}
            features.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {"name": c["name"], "layer": "continents"},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def graticule_geojson(self) -> dict[str, Any]:
        features = []
        for lon in range(-180, 181, 30):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, -85], [lon, 85]],
                    },
                    "properties": {"name": f"{lon}°", "kind": "meridian"},
                }
            )
        for lat in range(-80, 81, 20):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-180, lat], [180, lat]],
                    },
                    "properties": {"name": f"{lat}°", "kind": "parallel"},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def list_layers(self) -> list[dict[str, Any]]:
        layers = [
            {
                "id": "basemap_satellite",
                "name": "Offline Satellite Basemap",
                "category": "basemap",
                "type": "imagery",
                "description": "Locally generated satellite-style basemap with land/ocean tint",
                "url_template": "/api/v1/offline/basemap/{z}/{x}/{y}.png",
                "enabled_default": True,
            },
            {
                "id": "basemap_topo",
                "name": "Offline Topographic Basemap",
                "category": "basemap",
                "type": "imagery",
                "description": "Local topographic color-relief style basemap",
                "url_template": "/api/v1/offline/basemap/{z}/{x}/{y}.png?style=topo",
                "enabled_default": False,
            },
            {
                "id": "basemap_dark",
                "name": "Offline Dark Basemap",
                "category": "basemap",
                "type": "imagery",
                "description": "Dark cartographic basemap for analysis overlays",
                "url_template": "/api/v1/offline/basemap/{z}/{x}/{y}.png?style=dark",
                "enabled_default": False,
            },
            {
                "id": "landmarks",
                "name": "World Landmarks",
                "category": "vector",
                "type": "geojson",
                "description": "Major peaks, cities, and geographic landmarks",
                "path": str(self.vector_dir / "landmarks.geojson"),
                "enabled_default": True,
            },
            {
                "id": "continents",
                "name": "Continent Outlines",
                "category": "vector",
                "type": "geojson",
                "description": "Simplified continental polygons",
                "path": str(self.vector_dir / "continents.geojson"),
                "enabled_default": False,
            },
            {
                "id": "coastlines",
                "name": "Coastlines",
                "category": "vector",
                "type": "geojson",
                "description": "Simplified coastline polylines",
                "path": str(self.vector_dir / "coastlines.geojson"),
                "enabled_default": True,
            },
            {
                "id": "graticule",
                "name": "Graticule",
                "category": "vector",
                "type": "geojson",
                "description": "Latitude/longitude grid",
                "path": str(self.vector_dir / "graticule.geojson"),
                "enabled_default": False,
            },
            {
                "id": "sample_dem",
                "name": "Sample DEM (Digital Elevation Model)",
                "category": "elevation",
                "type": "raster",
                "subtype": "DEM",
                "description": "Embedded sample DEM for terrain analysis",
                "path": str(self.dem_dir / "sample_dem.tif"),
                "enabled_default": False,
            },
            {
                "id": "sample_dtm",
                "name": "Sample DTM (Digital Terrain Model)",
                "category": "elevation",
                "type": "raster",
                "subtype": "DTM",
                "description": "Bare-earth sample DTM",
                "path": str(self.dem_dir / "sample_dtm.tif"),
                "enabled_default": False,
            },
            {
                "id": "sample_dsm",
                "name": "Sample DSM (Digital Surface Model)",
                "category": "elevation",
                "type": "raster",
                "subtype": "DSM",
                "description": "Surface (trees/buildings) sample DSM",
                "path": str(self.dem_dir / "sample_dsm.tif"),
                "enabled_default": False,
            },
        ]

        # User-uploaded elevation / vector layers
        for path in sorted(self.dem_dir.glob("user_*.tif")):
            layers.append(
                {
                    "id": f"user_elev_{path.stem}",
                    "name": path.name,
                    "category": "elevation",
                    "type": "raster",
                    "subtype": "USER",
                    "description": "User-uploaded elevation model",
                    "path": str(path),
                    "enabled_default": False,
                }
            )
        for path in sorted(self.vector_dir.glob("user_*.geojson")):
            layers.append(
                {
                    "id": f"user_vec_{path.stem}",
                    "name": path.name,
                    "category": "vector",
                    "type": "geojson",
                    "description": "User-uploaded vector layer",
                    "path": str(path),
                    "enabled_default": False,
                }
            )
        return layers

    def get_vector_geojson(self, layer_id: str) -> dict[str, Any] | None:
        mapping = {
            "landmarks": self.vector_dir / "landmarks.geojson",
            "continents": self.vector_dir / "continents.geojson",
            "coastlines": self.vector_dir / "coastlines.geojson",
            "graticule": self.vector_dir / "graticule.geojson",
        }
        path = mapping.get(layer_id)
        if path is None:
            # user vectors
            candidate = self.vector_dir / f"{layer_id.replace('user_vec_', '')}.geojson"
            if not candidate.exists():
                candidate = self.vector_dir / f"{layer_id}.geojson"
            path = candidate if candidate.exists() else None
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text())

    def render_basemap_tile(self, z: int, x: int, y: int, style: str = "satellite") -> bytes:
        """Procedural offline basemap tile (256x256 PNG). No network required."""
        size = 256
        n = 2**z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        lat_max = self._tile_y_to_lat(y, n)
        lat_min = self._tile_y_to_lat(y + 1, n)

        img = Image.new("RGB", (size, size))
        pixels = img.load()

        for py in range(size):
            lat = lat_max + (lat_min - lat_max) * (py / (size - 1))
            for px in range(size):
                lon = lon_min + (lon_max - lon_min) * (px / (size - 1))
                land = self._is_land(lon, lat)
                elev = self._pseudo_elevation(lon, lat)
                if style == "dark":
                    pixels[px, py] = (18, 22, 28) if not land else (
                        int(30 + elev * 40),
                        int(40 + elev * 50),
                        int(48 + elev * 40),
                    )
                elif style == "topo":
                    if not land:
                        pixels[px, py] = (70, 130, 180)
                    else:
                        # green lowlands → brown → white peaks
                        if elev < 0.3:
                            pixels[px, py] = (90, 160, 90)
                        elif elev < 0.6:
                            pixels[px, py] = (160, 140, 80)
                        elif elev < 0.85:
                            pixels[px, py] = (140, 110, 80)
                        else:
                            pixels[px, py] = (230, 230, 235)
                else:  # satellite
                    if not land:
                        depth = 0.4 + 0.3 * math.sin(lon * 0.05) * math.cos(lat * 0.05)
                        pixels[px, py] = (
                            int(10 + 20 * depth),
                            int(40 + 50 * depth),
                            int(80 + 70 * depth),
                        )
                    else:
                        veg = 0.35 + 0.4 * elev
                        pixels[px, py] = (
                            int(40 + 50 * (1 - veg) + 30 * elev),
                            int(70 + 90 * veg),
                            int(40 + 40 * (1 - elev)),
                        )

        # Draw subtle graticule at low zoom
        if z <= 3:
            draw = ImageDraw.Draw(img)
            for glon in range(-180, 181, 30):
                if lon_min <= glon <= lon_max:
                    gx = int((glon - lon_min) / (lon_max - lon_min + 1e-9) * (size - 1))
                    draw.line([(gx, 0), (gx, size)], fill=(255, 255, 255, 30), width=1)
            for glat in range(-80, 81, 20):
                if lat_min <= glat <= lat_max:
                    gy = int((lat_max - glat) / (lat_max - lat_min + 1e-9) * (size - 1))
                    draw.line([(0, gy), (size, gy)], fill=(255, 255, 255, 30), width=1)

        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _generate_basemap_tiles(self) -> None:
        """Pre-generate a small z0–z2 cache for instant offline startup."""
        for style in ("satellite", "topo", "dark"):
            for z in range(0, 3):
                n = 2**z
                for x in range(n):
                    for y in range(n):
                        out = self.basemap_dir / style / str(z) / str(x)
                        out.mkdir(parents=True, exist_ok=True)
                        path = out / f"{y}.png"
                        if not path.exists():
                            path.write_bytes(self.render_basemap_tile(z, x, y, style=style))

    def get_cached_or_render_tile(self, z: int, x: int, y: int, style: str = "satellite") -> bytes:
        cached = self.basemap_dir / style / str(z) / str(x) / f"{y}.png"
        if cached.exists():
            return cached.read_bytes()
        data = self.render_basemap_tile(z, x, y, style=style)
        if z <= 4:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        return data

    def _write_sample_elevation(self, path: Path, kind: str = "dem") -> None:
        """Write a small synthetic GeoTIFF elevation model around 0°N, 0°E."""
        try:
            import rasterio
            from rasterio.transform import from_bounds
        except ImportError:
            # Fallback: write a simple binary heightfield + sidecar meta
            arr = self._elevation_array(kind)
            Image.fromarray(((arr - arr.min()) / (arr.max() - arr.min() + 1e-6) * 255).astype(np.uint8)).save(
                path.with_suffix(".png")
            )
            path.with_suffix(".json").write_text(
                json.dumps({"kind": kind, "bounds": [-2, -2, 2, 2], "note": "PNG fallback without rasterio"})
            )
            # Still create an empty marker tif path for catalog consistency
            path.write_bytes(b"")
            return

        height, width = 256, 256
        data = self._elevation_array(kind, height=height, width=width).astype(np.float32)
        transform = from_bounds(-2.0, -2.0, 2.0, 2.0, width, height)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            compress="lzw",
        ) as dst:
            dst.write(data, 1)
            dst.update_tags(SAT_EYE_LAYER=kind.upper())

    def _elevation_array(self, kind: str, height: int = 256, width: int = 256) -> np.ndarray:
        ys = np.linspace(-1, 1, height)
        xs = np.linspace(-1, 1, width)
        xx, yy = np.meshgrid(xs, ys)
        base = 200 + 800 * np.exp(-(xx**2 + yy**2) * 2.5)  # central hill
        ridges = 120 * np.sin(6 * xx) * np.cos(4 * yy)
        noise = 40 * np.sin(20 * xx + 13 * yy) * np.cos(17 * yy)
        dem = base + ridges + noise
        if kind == "dtm":
            return dem  # bare earth
        if kind == "dsm":
            canopy = 25 * (np.sin(30 * xx) ** 2) * (np.cos(28 * yy) ** 2)
            buildings = np.where((np.abs(xx) < 0.15) & (np.abs(yy) < 0.15), 40, 0)
            return dem + canopy + buildings
        return dem  # dem

    @staticmethod
    def _tile_y_to_lat(y: int, n: int) -> float:
        # Web Mercator inverse
        t = math.pi - 2.0 * math.pi * y / n
        return math.degrees(math.atan(math.sinh(t)))

    @staticmethod
    def _pseudo_elevation(lon: float, lat: float) -> float:
        v = (
            math.sin(math.radians(lon * 3)) * math.cos(math.radians(lat * 2))
            + 0.5 * math.sin(math.radians(lat * 5))
        )
        return max(0.0, min(1.0, (v + 1.5) / 3.0))

    @staticmethod
    def _is_land(lon: float, lat: float) -> bool:
        """Very coarse land mask from continent bounding polygons."""
        for c in CONTINENT_OUTLINES:
            coords = c["coordinates"]
            if OfflineLayersService._point_in_poly(lon, lat, coords):
                return True
        # Greenland / Antarctica rough boxes
        if -55 <= lon <= -10 and 60 <= lat <= 85:
            return True
        if -180 <= lon <= 180 and lat <= -65:
            return True
        return False

    @staticmethod
    def _point_in_poly(x: float, y: float, poly: list[list[float]]) -> bool:
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside
