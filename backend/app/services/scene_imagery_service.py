"""Collection-aware scene imagery: S2 TCI, S1 SAR grayscale, Landsat RGB + footprints."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from loguru import logger
from PIL import Image
from shapely.geometry import Point, shape

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
}

# Registry schema version — bump to invalidate old all-S2 layers
LAYER_VERSION = 3


class SceneImageryService:
    """Resolve per-collection satellite imagery and serve XYZ tiles."""

    TILE_SIZE = 256

    def __init__(self) -> None:
        self.settings = get_settings()
        self.registry_dir = self.settings.imagery_cache_dir / "scene_layers"
        self.tile_cache = self.settings.imagery_cache_dir / "scene_tiles"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.tile_cache.mkdir(parents=True, exist_ok=True)

    def _registry_path(self, scene_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", scene_id)[:180]
        return self.registry_dir / f"{safe}.json"

    def _tile_cache_root(self, scene_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", scene_id)[:180]
        return self.tile_cache / safe

    def get_layer(self, scene_id: str) -> dict[str, Any] | None:
        path = self._registry_path(scene_id)
        if not path.exists():
            return None
        try:
            layer = json.loads(path.read_bytes())
        except Exception:  # noqa: BLE001
            return None
        if layer.get("version") != LAYER_VERSION:
            return None
        return layer

    def save_layer(self, scene_id: str, layer: dict[str, Any]) -> dict[str, Any]:
        layer = {**layer, "version": LAYER_VERSION}
        path = self._registry_path(scene_id)
        path.write_text(json.dumps(layer), encoding="utf-8")
        return layer

    @staticmethod
    def _normalize_collection(collection: str | None) -> str:
        c = (collection or "SENTINEL-2").upper().replace("_", "-")
        if c.startswith("S2") or "SENTINEL-2" in c:
            return "SENTINEL-2"
        if c.startswith("S1") or "SENTINEL-1" in c:
            return "SENTINEL-1"
        if "LANDSAT-8" in c or c in {"LC08", "L8"}:
            return "LANDSAT-8"
        if "LANDSAT-9" in c or c in {"LC09", "L9"}:
            return "LANDSAT-9"
        if "LANDSAT" in c:
            return "LANDSAT-8"
        return c

    @staticmethod
    def _bbox_from_footprint(footprint: dict[str, Any] | None) -> list[float] | None:
        if not footprint or footprint.get("type") != "Polygon":
            return None
        ring = footprint["coordinates"][0]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        return [min(lons), min(lats), max(lons), max(lats)]

    def resolve_bounds(
        self,
        bbox: list[float] | None,
        footprint: dict[str, Any] | None,
    ) -> list[float]:
        from_fp = self._bbox_from_footprint(footprint)
        if from_fp:
            return from_fp
        if bbox and len(bbox) == 4:
            return [float(x) for x in bbox]
        return [74.15, 31.35, 74.55, 31.7]

    def _parse_sensing_time(self, sensing_time: str | None) -> datetime | None:
        if not sensing_time:
            return None
        try:
            return datetime.fromisoformat(sensing_time.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _coverage(bbox: list[float], item_bbox: list[float]) -> float:
        west, south, east, north = bbox
        if len(item_bbox) != 4:
            return 0.0
        ix0 = max(west, float(item_bbox[0]))
        iy0 = max(south, float(item_bbox[1]))
        ix1 = min(east, float(item_bbox[2]))
        iy1 = min(north, float(item_bbox[3]))
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        area = max((east - west) * (north - south), 1e-12)
        return inter / area

    @staticmethod
    def _s3_to_https(href: str) -> str:
        if href.startswith("s3://"):
            bucket, _, key = href[5:].partition("/")
            return f"https://{bucket}.s3.amazonaws.com/{key}"
        return href

    def _sign_pc(self, href: str, client: httpx.Client) -> str:
        resp = client.get(PC_SIGN_URL, params={"href": href})
        if resp.status_code != 200:
            raise NotFoundError(f"Failed to sign Landsat asset ({resp.status_code})")
        return resp.json()["href"]

    def _datetime_windows(self, sensing_time: str | None) -> list[tuple[str, str]]:
        dt = self._parse_sensing_time(sensing_time)
        windows: list[tuple[str, str]] = []
        if dt:
            for days in (3, 10, 30, 90, 365):
                start = (dt - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
                end = (dt + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59Z")
                windows.append((start, end))
        now = datetime.now(UTC)
        windows.append(
            (
                (now - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z"),
                now.strftime("%Y-%m-%dT23:59:59Z"),
            )
        )
        return windows

    def _stac_search(
        self,
        client: httpx.Client,
        url: str,
        collections: list[str],
        bbox: list[float],
        start: str,
        end: str,
        query: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "collections": collections,
            "bbox": bbox,
            "datetime": f"{start}/{end}",
            "limit": limit,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }
        if query:
            body["query"] = query
        resp = client.post(url, json=body)
        if resp.status_code != 200:
            logger.warning("STAC search {} → {}", url, resp.status_code)
            return []
        return resp.json().get("features") or []

    def find_sentinel2(
        self,
        bbox: list[float],
        sensing_time: str | None,
        target_cloud: float | None,
    ) -> dict[str, Any]:
        """Match S2 TCI whose cloud cover is closest to the catalog scene."""
        last_error = "empty"
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            for start, end in self._datetime_windows(sensing_time):
                # Allow high cloud so cloudy catalog scenes can match cloudy imagery
                features = self._stac_search(
                    client,
                    EARTH_SEARCH_URL,
                    ["sentinel-2-l2a"],
                    bbox,
                    start,
                    end,
                    query={"eo:cloud_cover": {"lt": 95}},
                )
                scored: list[tuple[float, dict[str, Any]]] = []
                for feat in features:
                    cov = self._coverage(bbox, feat.get("bbox") or [])
                    if cov < 0.15:
                        continue
                    assets = feat.get("assets") or {}
                    visual = assets.get("visual")
                    if not visual or not visual.get("href"):
                        continue
                    cloud = float((feat.get("properties") or {}).get("eo:cloud_cover") or 0)
                    # Prefer coverage, then closest cloud % to catalog scene
                    target = float(target_cloud) if target_cloud is not None else cloud
                    cloud_delta = abs(cloud - target)
                    score = cov * 5.0 - cloud_delta / 8.0
                    # Strongly penalize clear substitutes for cloudy catalog scenes
                    if target_cloud is not None and target_cloud >= 15 and cloud < max(5.0, target_cloud * 0.35):
                        score -= 3.0
                    scored.append((score, feat))
                if not scored:
                    last_error = f"no covering S2 in {start}..{end}"
                    continue
                scored.sort(key=lambda t: -t[0])
                feat = scored[0][1]
                props = feat.get("properties") or {}
                assets = feat.get("assets") or {}
                analysis_bands = {
                    k: assets[k]["href"]
                    for k in (
                        "coastal",
                        "blue",
                        "green",
                        "red",
                        "rededge1",
                        "rededge2",
                        "rededge3",
                        "nir",
                        "nir08",
                        "nir09",
                        "swir16",
                        "swir22",
                    )
                    if k in assets and assets[k].get("href")
                }
                # Friendly aliases used by indices / band picker
                if "swir16" in analysis_bands:
                    analysis_bands["swir"] = analysis_bands["swir16"]
                if "swir22" in analysis_bands:
                    analysis_bands["swir2"] = analysis_bands["swir22"]
                elif "swir" in analysis_bands:
                    analysis_bands["swir2"] = analysis_bands["swir"]
                if "nir08" in analysis_bands and "nir" not in analysis_bands:
                    analysis_bands["nir"] = analysis_bands["nir08"]
                return {
                    "stac_id": feat.get("id"),
                    "cog_url": assets["visual"]["href"],
                    "analysis_bands": analysis_bands,
                    "sign": None,
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "render_mode": "rgb",
                    "source": "sentinel2_tci",
                    "bands": {"R": "B04 Red", "G": "B03 Green", "B": "B02 Blue"},
                    "label": "Sentinel-2 true-color (TCI)",
                }
        raise NotFoundError(f"No Sentinel-2 TCI found ({last_error})")

    def find_sentinel1(self, bbox: list[float], sensing_time: str | None) -> dict[str, Any]:
        """Match Sentinel-1 GRD VV (grayscale SAR)."""
        last_error = "empty"
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            for start, end in self._datetime_windows(sensing_time):
                features = self._stac_search(
                    client, EARTH_SEARCH_URL, ["sentinel-1-grd"], bbox, start, end
                )
                scored: list[tuple[float, dict[str, Any]]] = []
                for feat in features:
                    cov = self._coverage(bbox, feat.get("bbox") or [])
                    if cov < 0.05:
                        continue
                    assets = feat.get("assets") or {}
                    vv = assets.get("vv") or assets.get("vh")
                    if not vv or not vv.get("href"):
                        continue
                    scored.append((cov, feat))
                if not scored:
                    last_error = f"no covering S1 in {start}..{end}"
                    continue
                scored.sort(key=lambda t: -t[0])
                feat = scored[0][1]
                props = feat.get("properties") or {}
                assets = feat.get("assets") or {}
                pol = "vv" if "vv" in assets else "vh"
                analysis_bands: dict[str, str] = {}
                if assets.get("vv", {}).get("href"):
                    analysis_bands["vv"] = self._s3_to_https(assets["vv"]["href"])
                if assets.get("vh", {}).get("href"):
                    analysis_bands["vh"] = self._s3_to_https(assets["vh"]["href"])
                return {
                    "stac_id": feat.get("id"),
                    "cog_url": self._s3_to_https(assets[pol]["href"]),
                    "analysis_bands": analysis_bands,
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": None,
                    "render_mode": "grayscale",
                    "source": "sentinel1_grd",
                    "polarization": pol.upper(),
                    "bands": {"R": f"{pol.upper()} SAR", "G": f"{pol.upper()} SAR", "B": f"{pol.upper()} SAR"},
                    "label": f"Sentinel-1 GRD {pol.upper()} (grayscale)",
                    "proj_epsg": props.get("proj:epsg"),
                    "proj_transform": props.get("proj:transform"),
                }
        raise NotFoundError(f"No Sentinel-1 GRD found ({last_error})")

    def find_landsat(
        self,
        bbox: list[float],
        sensing_time: str | None,
        target_cloud: float | None,
        platform: str,
    ) -> dict[str, Any]:
        """Match Landsat C2 L2 RGB via Planetary Computer (signed COGs) + tilted footprint."""
        last_error = "empty"
        # Filter by platform when possible
        platform_q = "landsat-8" if platform == "LANDSAT-8" else "landsat-9"
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for start, end in self._datetime_windows(sensing_time):
                features = self._stac_search(
                    client,
                    PC_STAC_URL,
                    ["landsat-c2-l2"],
                    bbox,
                    start,
                    end,
                    query={"eo:cloud_cover": {"lt": 95}},
                    limit=25,
                )
                scored: list[tuple[float, dict[str, Any]]] = []
                for feat in features:
                    props = feat.get("properties") or {}
                    plat = (props.get("platform") or "").lower()
                    # Soft preference for requested Landsat-8 vs 9
                    if platform == "LANDSAT-8" and "9" in plat and "8" not in plat:
                        platform_bonus = -0.05
                    elif platform == "LANDSAT-9" and "8" in plat and "9" not in plat:
                        platform_bonus = -0.05
                    else:
                        platform_bonus = 0.0
                    cov = self._coverage(bbox, feat.get("bbox") or [])
                    if cov < 0.1:
                        continue
                    assets = feat.get("assets") or {}
                    if not all(k in assets and assets[k].get("href") for k in ("red", "green", "blue")):
                        continue
                    cloud = float(props.get("eo:cloud_cover") or 0)
                    target = float(target_cloud) if target_cloud is not None else cloud
                    cloud_delta = abs(cloud - target)
                    score = cov * 10.0 - cloud_delta / 100.0 + platform_bonus
                    scored.append((score, feat))
                if not scored:
                    last_error = f"no covering Landsat in {start}..{end}"
                    continue
                scored.sort(key=lambda t: -t[0])
                feat = scored[0][1]
                props = feat.get("properties") or {}
                assets = feat.get("assets") or {}
                analysis_bands = {
                    "red": assets["red"]["href"],
                    "green": assets["green"]["href"],
                    "blue": assets["blue"]["href"],
                }
                if assets.get("nir08", {}).get("href"):
                    analysis_bands["nir"] = assets["nir08"]["href"]
                if assets.get("swir16", {}).get("href"):
                    analysis_bands["swir"] = assets["swir16"]["href"]
                if assets.get("swir22", {}).get("href"):
                    analysis_bands["swir2"] = assets["swir22"]["href"]
                elif analysis_bands.get("swir"):
                    analysis_bands["swir2"] = analysis_bands["swir"]
                if assets.get("lwir11", {}).get("href"):
                    analysis_bands["thermal"] = assets["lwir11"]["href"]
                return {
                    "stac_id": feat.get("id"),
                    "cog_urls": {
                        "red": assets["red"]["href"],
                        "green": assets["green"]["href"],
                        "blue": assets["blue"]["href"],
                    },
                    "analysis_bands": analysis_bands,
                    "sign": "planetary_computer",
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "render_mode": "rgb",
                    "source": "landsat_c2_l2",
                    "platform": props.get("platform") or platform_q,
                    "bands": {"R": "SR_B4 Red", "G": "SR_B3 Green", "B": "SR_B2 Blue"},
                    "label": f"{platform} true-color (OLI)",
                }
        raise NotFoundError(f"No Landsat imagery found ({last_error})")

    def prepare_scene_layer(
        self,
        scene_id: str,
        *,
        bbox: list[float] | None = None,
        footprint: dict[str, Any] | None = None,
        sensing_time: str | None = None,
        cloud_cover: float | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        coll = self._normalize_collection(collection)
        existing = self.get_layer(scene_id)
        if existing and existing.get("collection") == coll:
            return existing

        # Prefer STAC footprint bounds; fall back to request bbox
        search_bbox = self.resolve_bounds(bbox, footprint)

        if coll == "SENTINEL-1":
            match = self.find_sentinel1(search_bbox, sensing_time)
        elif coll in {"LANDSAT-8", "LANDSAT-9"}:
            match = self.find_landsat(search_bbox, sensing_time, cloud_cover, coll)
        else:
            # SENTINEL-2 and other optical defaults
            match = self.find_sentinel2(search_bbox, sensing_time, cloud_cover)
            coll = "SENTINEL-2"

        stac_fp = match.get("footprint")
        # Display bounds from actual STAC footprint (tilted scenes → correct envelope)
        display_bounds = self._bbox_from_footprint(stac_fp) or match.get("bbox") or search_bbox

        layer: dict[str, Any] = {
            "scene_id": scene_id,
            "collection": coll,
            "source": match["source"],
            "composite": "grayscale_SAR" if match["render_mode"] == "grayscale" else "true_color_RGB",
            "render_mode": match["render_mode"],
            "bands": match["bands"],
            "label": match["label"],
            "cog_url": match.get("cog_url"),
            "cog_urls": match.get("cog_urls"),
            "analysis_bands": match.get("analysis_bands") or {},
            "sign": match.get("sign"),
            "stac_id": match.get("stac_id"),
            "bounds": display_bounds,
            "footprint": stac_fp,
            "acquisition_date": match.get("datetime"),
            "cloud_cover": match.get("cloud_cover"),
            "polarization": match.get("polarization"),
            "tile_url_template": f"/api/v1/catalog/scenes/{scene_id}/tiles/{{z}}/{{x}}/{{y}}.png",
        }
        # Drop previous tile cache when remapping a scene
        cache_root = self._tile_cache_root(scene_id)
        if cache_root.exists():
            import shutil

            shutil.rmtree(cache_root, ignore_errors=True)
        return self.save_layer(scene_id, layer)

    def _mercator_bounds(self, z: int, x: int, y: int) -> tuple[float, float, float, float]:
        n = 2.0**z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return lon_min, lat_min, lon_max, lat_max

    def _empty_tile(self) -> bytes:
        import io

        img = Image.new("RGBA", (self.TILE_SIZE, self.TILE_SIZE), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _footprint_mask(
        self, footprint: dict[str, Any] | None, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ) -> np.ndarray | None:
        """Boolean mask (True=inside footprint) for the tile grid."""
        if not footprint:
            return None
        try:
            geom = shape(footprint)
        except Exception:  # noqa: BLE001
            return None
        size = self.TILE_SIZE
        xs = np.linspace(lon_min, lon_max, size, endpoint=False) + (lon_max - lon_min) / (2 * size)
        ys = np.linspace(lat_max, lat_min, size, endpoint=False) + (lat_min - lat_max) / (2 * size)
        # Coarser mask then upsample for speed
        step = 4
        mask_small = np.zeros((size // step, size // step), dtype=bool)
        for iy, lat in enumerate(ys[::step]):
            for ix, lon in enumerate(xs[::step]):
                mask_small[iy, ix] = geom.contains(Point(lon, lat)) or geom.touches(Point(lon, lat))
        # Nearest upsample
        mask = np.repeat(np.repeat(mask_small, step, axis=0), step, axis=1)
        if mask.shape[0] < size or mask.shape[1] < size:
            padded = np.zeros((size, size), dtype=bool)
            padded[: mask.shape[0], : mask.shape[1]] = mask
            mask = padded
        return mask[:size, :size]

    def _read_rgb_cog(
        self, cog_url: str, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ) -> np.ndarray:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        with rasterio.Env(**GDAL_ENV):
            with rasterio.open(cog_url) as src:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                )
                window = from_bounds(left, bottom, right, top, transform=src.transform)
                oversampling = float(window.width) < self.TILE_SIZE or float(window.height) < self.TILE_SIZE
                resampling = Resampling.nearest if oversampling else Resampling.bilinear
                count = min(3, src.count)
                data = src.read(
                    indexes=list(range(1, count + 1)),
                    out_shape=(count, self.TILE_SIZE, self.TILE_SIZE),
                    window=window,
                    resampling=resampling,
                    boundless=True,
                    fill_value=0,
                )
        if data.shape[0] == 1:
            return np.stack([data[0], data[0], data[0]], axis=0)
        return data[:3]

    def _read_landsat_rgb(
        self,
        cog_urls: dict[str, str],
        lon_min: float,
        lat_min: float,
        lon_max: float,
        lat_max: float,
    ) -> np.ndarray:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        bands: list[np.ndarray] = []
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            signed = {k: self._sign_pc(v, client) for k, v in cog_urls.items()}
        with rasterio.Env():
            for name in ("red", "green", "blue"):
                with rasterio.open(signed[name]) as src:
                    left, bottom, right, top = transform_bounds(
                        "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                    )
                    window = from_bounds(left, bottom, right, top, transform=src.transform)
                    oversampling = float(window.width) < self.TILE_SIZE or float(window.height) < self.TILE_SIZE
                    resampling = Resampling.nearest if oversampling else Resampling.bilinear
                    arr = src.read(
                        1,
                        out_shape=(self.TILE_SIZE, self.TILE_SIZE),
                        window=window,
                        resampling=resampling,
                        boundless=True,
                        fill_value=0,
                    )
                    bands.append(arr.astype(np.float32))
        stacked = np.stack(bands, axis=0)
        # Landsat C2 SR scaling
        refl = np.clip(stacked * 0.0000275 - 0.2, 0, 1)
        return (refl * 10000).astype(np.float32)  # keep as float reflectance*10000 for joint stretch

    def _read_s1_gray(
        self, cog_url: str, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ) -> np.ndarray:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import reproject

        dst = np.zeros((self.TILE_SIZE, self.TILE_SIZE), dtype=np.float32)
        dst_transform = rasterio.transform.from_bounds(
            lon_min, lat_min, lon_max, lat_max, self.TILE_SIZE, self.TILE_SIZE
        )
        with rasterio.Env(**GDAL_ENV):
            with rasterio.open(self._s3_to_https(cog_url)) as src:
                src_crs = src.crs
                gcps = None
                if src_crs is None and src.gcps and src.gcps[0]:
                    gcps = src.gcps[0]
                    src_crs = src.gcps[1]
                reproject(
                    source=rasterio.band(src, 1),
                    destination=dst,
                    src_transform=src.transform if gcps is None else None,
                    src_crs=src_crs,
                    src_gcps=gcps,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:4326",
                    resampling=Resampling.bilinear,
                    src_nodata=0,
                    dst_nodata=0,
                )
        return np.stack([dst, dst, dst], axis=0)

    def _to_rgba(self, rgb: np.ndarray, mask: np.ndarray | None, mode: str) -> bytes:
        import io

        rgb_f = rgb.astype(np.float32)
        if mode == "grayscale":
            band = rgb_f[0]
            valid = band[band > 0]
            if valid.size:
                lo, hi = np.percentile(valid, (2, 98))
                g = np.clip((band - lo) / (hi - lo + 1e-9), 0, 1)
            else:
                g = np.zeros_like(band)
            g[band <= 0] = 0
            rgb_u8 = (np.stack([g, g, g], axis=0) * 255).astype(np.uint8)
            alpha = np.where(band > 0, 255, 0).astype(np.uint8)
        else:
            # Joint stretch for natural color balance
            if rgb_f.max() <= 1.5:
                # already 0–1 reflectance-ish
                stacked = rgb_f
            elif rgb_f.max() <= 255:
                stacked = rgb_f
            else:
                # Landsat scaled reflectance*10000 or raw DN
                stacked = np.clip(rgb_f / 10000.0, 0, 1) if rgb_f.max() > 255 else rgb_f
            valid_mask = np.any(stacked > 0, axis=0)
            valid = stacked[:, valid_mask]
            if valid.size:
                lo = float(np.percentile(valid, 2))
                hi = float(np.percentile(valid, 98))
                if hi <= lo:
                    hi = lo + 1e-6
                stretched = np.clip((stacked - lo) / (hi - lo), 0, 1)
            else:
                stretched = np.zeros_like(stacked)
            rgb_u8 = (stretched * 255).astype(np.uint8)
            alpha = np.where(valid_mask, 255, 0).astype(np.uint8)

        if mask is not None:
            alpha = np.where(mask, alpha, 0).astype(np.uint8)

        rgba = np.dstack([rgb_u8[0], rgb_u8[1], rgb_u8[2], alpha])
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def render_tile(self, scene_id: str, z: int, x: int, y: int) -> bytes:
        if z < 0 or z > 18:
            raise ValidationError("Zoom level out of range")
        n = 2**z
        if x < 0 or x >= n or y < 0 or y >= n:
            raise ValidationError("Tile coordinates out of range")

        layer = self.get_layer(scene_id)
        if not layer:
            raise NotFoundError("Scene imagery layer not prepared — open the eye overlay first")

        cache_path = self._tile_cache_root(scene_id) / str(z) / str(x) / f"{y}.png"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            return cache_path.read_bytes()

        lon_min, lat_min, lon_max, lat_max = self._mercator_bounds(z, x, y)
        west, south, east, north = layer["bounds"]
        if lon_max < west or lon_min > east or lat_max < south or lat_min > north:
            data = self._empty_tile()
            cache_path.write_bytes(data)
            return data

        mode = layer.get("render_mode") or "rgb"
        try:
            if layer.get("source") == "sentinel1_grd":
                rgb = self._read_s1_gray(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
            elif layer.get("cog_urls"):
                rgb = self._read_landsat_rgb(layer["cog_urls"], lon_min, lat_min, lon_max, lat_max)
            else:
                rgb = self._read_rgb_cog(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scene tile read failed {}/{}/{}/{}: {}", scene_id, z, x, y, exc)
            return self._empty_tile()

        # Clip to tilted STAC footprint (critical for Landsat / S1 swaths)
        mask = self._footprint_mask(layer.get("footprint"), lon_min, lat_min, lon_max, lat_max)
        png = self._to_rgba(rgb, mask, mode)
        cache_path.write_bytes(png)
        return png

    def render_preview(self, scene_id: str, size: int = 768) -> bytes:
        """Full-scene PNG covering layer bounds — used for download / ImageOverlay."""
        layer = self.get_layer(scene_id)
        if not layer:
            raise NotFoundError("Scene imagery layer not prepared — open the eye overlay first")

        size = max(64, min(int(size), 2048))
        west, south, east, north = (float(v) for v in layer["bounds"])
        pad_x = (east - west) * 0.01
        pad_y = (north - south) * 0.01
        lon_min, lon_max = west - pad_x, east + pad_x
        lat_min, lat_max = south - pad_y, north + pad_y
        mode = layer.get("render_mode") or "rgb"

        old = self.TILE_SIZE
        self.TILE_SIZE = size
        try:
            if layer.get("source") == "sentinel1_grd":
                rgb = self._read_s1_gray(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
            elif layer.get("cog_urls"):
                rgb = self._read_landsat_rgb(layer["cog_urls"], lon_min, lat_min, lon_max, lat_max)
            else:
                rgb = self._read_rgb_cog(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
            mask = self._footprint_mask(
                layer.get("footprint"), lon_min, lat_min, lon_max, lat_max
            )
            return self._to_rgba(rgb, mask, mode)
        finally:
            self.TILE_SIZE = old

    def read_band_grid(
        self,
        href: str,
        bounds: list[float],
        size: int = 512,
        *,
        sign: str | None = None,
        reflectance_scale: str | None = None,
    ) -> np.ndarray:
        """Sample a COG band into a size×size grid covering [west,south,east,north]."""
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        url = self._s3_to_https(href)
        if sign == "planetary_computer":
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                url = self._sign_pc(url, client)

        west, south, east, north = (float(v) for v in bounds)
        env = GDAL_ENV if sign != "planetary_computer" else {}
        with rasterio.Env(**env):
            with rasterio.open(url) as src:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, west, south, east, north
                )
                window = from_bounds(left, bottom, right, top, transform=src.transform)
                data = src.read(
                    1,
                    out_shape=(size, size),
                    window=window,
                    resampling=Resampling.bilinear,
                    boundless=True,
                    fill_value=0,
                ).astype(np.float64)

        if reflectance_scale == "landsat_c2_sr":
            data = np.clip(data * 0.0000275 - 0.2, 0, 1)
            data[data <= 0] = np.nan
        elif reflectance_scale == "sentinel2_l2a":
            if np.nanmax(data) > 1.5:
                data = data / 10000.0
            data[data <= 0] = np.nan
        else:
            data[data <= 0] = np.nan
        return data

    def load_analysis_bands(
        self, scene_id: str, size: int = 512
    ) -> tuple[dict[str, np.ndarray], list[float], dict[str, Any] | None, dict[str, Any]]:
        """Load optical analysis bands for a prepared scene over its full footprint bounds."""
        layer = self.get_layer(scene_id)
        if not layer:
            raise NotFoundError(
                "Scene imagery is not on the map yet — turn the eye on first, then run indices"
            )
        if layer.get("collection") == "SENTINEL-1" or layer.get("render_mode") == "grayscale":
            raise ValidationError(
                "Sentinel-1 SAR is grayscale radar and does not support optical indices "
                "(NDVI, NDWI, NDBI, SAVI, BSI, LST, EVI, NDMI, NBR). Use a Sentinel-2 or Landsat scene."
            )

        bounds = [float(x) for x in layer["bounds"]]
        analysis = layer.get("analysis_bands") or {}
        sign = layer.get("sign")
        scale = "landsat_c2_sr" if layer.get("source") == "landsat_c2_l2" else "sentinel2_l2a"

        bands: dict[str, np.ndarray] = {}
        for name in (
            "coastal",
            "blue",
            "green",
            "red",
            "rededge1",
            "rededge2",
            "rededge3",
            "nir",
            "nir08",
            "nir09",
            "swir",
            "swir16",
            "swir2",
            "swir22",
            "thermal",
            "vv",
            "vh",
        ):
            href = analysis.get(name)
            if not href:
                continue
            try:
                if name in {"vv", "vh", "thermal"}:
                    bands[name] = self.read_band_grid(
                        href, bounds, size, sign=sign, reflectance_scale=None
                    )
                else:
                    bands[name] = self.read_band_grid(
                        href, bounds, size, sign=sign, reflectance_scale=scale
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load analysis band {} for {}: {}", name, scene_id, exc)

        if "swir2" not in bands and "swir" in bands:
            bands["swir2"] = bands["swir"]
        if "swir" not in bands and "swir16" in bands:
            bands["swir"] = bands["swir16"]
        if "nir" not in bands and "nir08" in bands:
            bands["nir"] = bands["nir08"]

        return bands, bounds, layer.get("footprint"), layer

    # Display metadata for band-picker downloads
    BAND_INFO: dict[str, dict[str, str]] = {
        "coastal": {"label": "Coastal / Aerosol", "code": "B01", "group": "optical"},
        "blue": {"label": "Blue", "code": "B02 / SR_B2", "group": "optical"},
        "green": {"label": "Green", "code": "B03 / SR_B3", "group": "optical"},
        "red": {"label": "Red", "code": "B04 / SR_B4", "group": "optical"},
        "rededge1": {"label": "Red Edge 1", "code": "B05", "group": "optical"},
        "rededge2": {"label": "Red Edge 2", "code": "B06", "group": "optical"},
        "rededge3": {"label": "Red Edge 3", "code": "B07", "group": "optical"},
        "nir": {"label": "NIR", "code": "B08 / SR_B5", "group": "optical"},
        "nir08": {"label": "NIR narrow", "code": "B8A / nir08", "group": "optical"},
        "nir09": {"label": "Water vapour", "code": "B09", "group": "optical"},
        "swir": {"label": "SWIR 1", "code": "B11 / SR_B6", "group": "optical"},
        "swir16": {"label": "SWIR 1.6 µm", "code": "swir16", "group": "optical"},
        "swir2": {"label": "SWIR 2", "code": "B12 / SR_B7", "group": "optical"},
        "swir22": {"label": "SWIR 2.2 µm", "code": "swir22", "group": "optical"},
        "thermal": {"label": "Thermal", "code": "ST_B10 / lwir11", "group": "thermal"},
        "vv": {"label": "VV polarization", "code": "VV", "group": "sar"},
        "vh": {"label": "VH polarization", "code": "VH", "group": "sar"},
    }

    def list_download_bands(
        self,
        scene_id: str,
        *,
        bbox: list[float] | None = None,
        footprint: dict[str, Any] | None = None,
        sensing_time: str | None = None,
        cloud_cover: float | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Return selectable spectral / SAR bands for a scene download."""
        layer = self.get_layer(scene_id)
        if not layer or (collection and layer.get("collection") != self._normalize_collection(collection)):
            layer = self.prepare_scene_layer(
                scene_id,
                bbox=bbox,
                footprint=footprint,
                sensing_time=sensing_time,
                cloud_cover=cloud_cover,
                collection=collection,
            )

        analysis = layer.get("analysis_bands") or {}
        # Prefer canonical keys; skip raw duplicates when aliases exist
        skip = set()
        if "swir" in analysis:
            skip.update({"swir16"})
        if "swir2" in analysis:
            skip.update({"swir22"})
        if "nir" in analysis and "nir08" in analysis:
            skip.add("nir08")

        available: list[dict[str, str]] = []
        for key in analysis.keys():
            if key in skip:
                continue
            meta = self.BAND_INFO.get(key, {"label": key, "code": key, "group": "other"})
            available.append(
                {
                    "id": key,
                    "label": meta["label"],
                    "code": meta["code"],
                    "group": meta["group"],
                }
            )

        # Stable display order
        order = list(self.BAND_INFO.keys())
        available.sort(key=lambda b: order.index(b["id"]) if b["id"] in order else 999)

        defaults = [b["id"] for b in available if b["id"] in {"red", "green", "blue", "vv"}]
        if not defaults and available:
            defaults = [available[0]["id"]]

        return {
            "scene_id": scene_id,
            "collection": layer.get("collection"),
            "stac_id": layer.get("stac_id"),
            "bounds": layer.get("bounds"),
            "bands": available,
            "default_bands": defaults,
            "formats": ["geotiff"],
        }

    def export_selected_bands(
        self,
        scene_id: str,
        band_ids: list[str],
        *,
        size: int = 512,
        collection: str | None = None,
        bbox: list[float] | None = None,
        footprint: dict[str, Any] | None = None,
        sensing_time: str | None = None,
        cloud_cover: float | None = None,
    ) -> tuple[bytes, str]:
        """Load chosen bands and package as a multi-band GeoTIFF."""
        from app.services.geotiff_export import band_arrays_to_geotiff

        if not band_ids:
            raise ValidationError("Select at least one band to download")

        layer = self.get_layer(scene_id)
        if not layer:
            layer = self.prepare_scene_layer(
                scene_id,
                bbox=bbox,
                footprint=footprint,
                sensing_time=sensing_time,
                cloud_cover=cloud_cover,
                collection=collection,
            )

        # SAR: allow loading even though optical indices are blocked
        bounds = [float(x) for x in layer["bounds"]]
        analysis = layer.get("analysis_bands") or {}
        sign = layer.get("sign")
        scale = "landsat_c2_sr" if layer.get("source") == "landsat_c2_l2" else None
        if layer.get("source") == "sentinel2_tci":
            scale = "sentinel2_l2a"

        # Resolve aliases
        resolved: list[str] = []
        for bid in band_ids:
            if bid in analysis:
                resolved.append(bid)
            elif bid == "swir" and "swir16" in analysis:
                resolved.append("swir16")
            elif bid == "swir2" and "swir22" in analysis:
                resolved.append("swir22")
            elif bid == "nir" and "nir08" in analysis:
                resolved.append("nir08")
            else:
                raise ValidationError(f"Band '{bid}' is not available for this scene")

        # De-dupe while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for b in resolved:
            if b not in seen:
                seen.add(b)
                unique.append(b)

        size = max(64, min(int(size), 2048))
        loaded: dict[str, np.ndarray] = {}
        for name in unique:
            href = analysis[name]
            if name in {"vv", "vh", "thermal"}:
                loaded[name] = self.read_band_grid(
                    href, bounds, size, sign=sign, reflectance_scale=None
                )
            else:
                loaded[name] = self.read_band_grid(
                    href, bounds, size, sign=sign, reflectance_scale=scale
                )

        coll = (layer.get("collection") or "scene").replace("-", "")
        stac = (layer.get("stac_id") or scene_id)[:60]
        band_tag = "-".join(unique)[:80]
        filename = f"{coll}_{stac}_{band_tag}.tif".replace("/", "_")
        return band_arrays_to_geotiff(
            loaded, bounds, filename=filename, band_order=unique
        )
