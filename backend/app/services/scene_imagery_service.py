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
LAYER_VERSION = 4

# Cap concurrent COG reads so Leaflet's tile burst does not starve the API
_TILE_SEMAPHORE = None
_TILE_SEMAPHORE_LIMIT = 6


def _tile_semaphore():
    global _TILE_SEMAPHORE
    if _TILE_SEMAPHORE is None:
        import threading

        _TILE_SEMAPHORE = threading.Semaphore(_TILE_SEMAPHORE_LIMIT)
    return _TILE_SEMAPHORE


class SceneImageryService:
    """Resolve per-collection satellite imagery and serve XYZ tiles."""

    TILE_SIZE = 256
    PREVIEW_SIZE = 512
    # Planetary Computer SAS tokens typically last ~1h; refresh earlier
    SIGNED_URL_TTL_SEC = 45 * 60

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

    def _ensure_signed_cog_urls(self, layer: dict[str, Any]) -> dict[str, str]:
        """Return Landsat band→signed URL map, refreshing Planetary Computer SAS as needed."""
        cog_urls = layer.get("cog_urls") or {}
        if not cog_urls:
            return {}
        signed = layer.get("signed_cog_urls") or {}
        signed_at = layer.get("signed_at")
        fresh = False
        if signed and signed_at and set(signed.keys()) >= set(cog_urls.keys()):
            try:
                ts = datetime.fromisoformat(str(signed_at).replace("Z", "+00:00"))
                age = (datetime.now(UTC) - ts).total_seconds()
                fresh = age < self.SIGNED_URL_TTL_SEC
            except ValueError:
                fresh = False
        if fresh:
            return {k: signed[k] for k in cog_urls}
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            refreshed = {k: self._sign_pc(v, client) for k, v in cog_urls.items()}
        layer["signed_cog_urls"] = refreshed
        layer["signed_at"] = datetime.now(UTC).isoformat()
        # Persist so concurrent tile workers reuse the same SAS token
        scene_id = layer.get("scene_id")
        if scene_id:
            self.save_layer(str(scene_id), layer)
        return refreshed

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

    def _datetime_windows_for_collection(
        self, collection: str, sensing_time: str | None
    ) -> list[tuple[str, str]]:
        """Collection-aware datetime windows (S1 did not exist in 2000; Landsat-7 did)."""
        dt = self._parse_sensing_time(sensing_time)
        if collection == "SENTINEL-1":
            # Sentinel-1 ops start mid-2014 — never search empty pre-mission years
            if dt is None or dt.year < 2015:
                return [
                    ("2015-01-01T00:00:00Z", "2016-12-31T23:59:59Z"),
                    ("2017-01-01T00:00:00Z", "2019-12-31T23:59:59Z"),
                    (
                        (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z"),
                        datetime.now(UTC).strftime("%Y-%m-%dT23:59:59Z"),
                    ),
                ]
            return self._datetime_windows(sensing_time)
        if collection in {"LANDSAT-8", "LANDSAT-9", "LANDSAT-7", "LANDSAT"}:
            if dt and dt.year <= 2012:
                # Landsat-5/7 era — widen around the requested year
                year = dt.year
                return [
                    (f"{year}-01-01T00:00:00Z", f"{year}-12-31T23:59:59Z"),
                    (f"{year - 1}-01-01T00:00:00Z", f"{year + 1}-12-31T23:59:59Z"),
                    ("1999-01-01T00:00:00Z", "2002-12-31T23:59:59Z"),
                ]
        if collection == "SENTINEL-2":
            if dt is None or dt.year < 2016:
                return [
                    ("2017-01-01T00:00:00Z", "2018-12-31T23:59:59Z"),
                    (
                        (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z"),
                        datetime.now(UTC).strftime("%Y-%m-%dT23:59:59Z"),
                    ),
                ]
        return self._datetime_windows(sensing_time)

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
            for start, end in self._datetime_windows_for_collection("SENTINEL-2", sensing_time):
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
                    for k in ("red", "green", "blue", "nir", "swir16", "swir22")
                    if k in assets and assets[k].get("href")
                }
                if "swir16" in analysis_bands:
                    analysis_bands["swir"] = analysis_bands["swir16"]
                if "swir22" in analysis_bands:
                    analysis_bands["swir2"] = analysis_bands["swir22"]
                elif "swir" in analysis_bands:
                    # Fallback: NBR uses SWIR2 when available; else SWIR1 with note
                    analysis_bands["swir2"] = analysis_bands["swir"]
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
            for start, end in self._datetime_windows_for_collection("SENTINEL-1", sensing_time):
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
                return {
                    "stac_id": feat.get("id"),
                    "cog_url": self._s3_to_https(assets[pol]["href"]),
                    "thumbnail_url": self._s3_to_https(
                        (assets.get("thumbnail") or {}).get("href") or ""
                    )
                    or None,
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
            for start, end in self._datetime_windows_for_collection(platform, sensing_time):
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
                    # Soft preference for requested Landsat-8 vs 9; allow L5/L7 for year-2000 era
                    if platform == "LANDSAT-8" and "9" in plat and "8" not in plat:
                        platform_bonus = -0.05
                    elif platform == "LANDSAT-9" and "8" in plat and "9" not in plat:
                        platform_bonus = -0.05
                    elif "landsat-7" in plat or "landsat-5" in plat:
                        # Prefer heritage missions when searching ~2000
                        dt = self._parse_sensing_time(sensing_time)
                        platform_bonus = 0.15 if dt and dt.year <= 2012 else -0.02
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
                    "label": f"{(props.get('platform') or platform).replace('-', ' ').title()} true-color",
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
            "thumbnail_url": match.get("thumbnail_url"),
            "tile_url_template": f"/api/v1/catalog/scenes/{scene_id}/tiles/{{z}}/{{x}}/{{y}}.png",
        }
        # Pre-sign Landsat COGs once so every XYZ tile does not pay SAS latency
        if match.get("sign") == "planetary_computer" and match.get("cog_urls"):
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                layer["signed_cog_urls"] = {
                    k: self._sign_pc(v, client) for k, v in match["cog_urls"].items()
                }
            layer["signed_at"] = datetime.now(UTC).isoformat()
        # Drop previous tile cache when remapping a scene
        cache_root = self._tile_cache_root(scene_id)
        if cache_root.exists():
            import shutil

            shutil.rmtree(cache_root, ignore_errors=True)
        return self.save_layer(scene_id, layer)

    def cache_remote_preview(self, scene_id: str, url: str | None, size: int = 256) -> str | None:
        """Download a small remote thumbnail into the preview cache (fast S1 eye-on)."""
        if not url:
            return None
        url = self._s3_to_https(url)
        path = self._preview_cache_path(scene_id, size)
        if path.exists() and path.stat().st_size > 0:
            return f"/api/v1/catalog/scenes/{scene_id}/overlay.png"
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code != 200 or not resp.content:
                logger.warning("Remote preview HTTP {}: {}", resp.status_code, url[:120])
                return None
            # Normalize to PNG
            img = Image.open(__import__("io").BytesIO(resp.content)).convert("RGBA")
            img.thumbnail((size, size))
            path.parent.mkdir(parents=True, exist_ok=True)
            buf = __import__("io").BytesIO()
            img.save(buf, format="PNG", optimize=True)
            path.write_bytes(buf.getvalue())
            return f"/api/v1/catalog/scenes/{scene_id}/overlay.png"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote preview cache failed {}: {}", scene_id, exc)
            return None

    def prewarm_center_tiles(self, scene_id: str, zoom: int = 9, radius: int = 1) -> None:
        """Background warm of nearby tiles after eye-on (non-blocking for Serveo)."""
        layer = self.get_layer(scene_id)
        if not layer:
            return
        bounds = layer.get("bounds") or []
        if len(bounds) != 4:
            return
        west, south, east, north = (float(v) for v in bounds)
        clon = (west + east) / 2
        clat = (south + north) / 2
        n = 2**zoom
        cx = int((clon + 180.0) / 360.0 * n)
        cy = int(
            (
                1.0
                - math.log(math.tan(math.radians(clat)) + 1.0 / math.cos(math.radians(clat)))
                / math.pi
            )
            / 2.0
            * n
        )
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                try:
                    self.render_tile(scene_id, zoom, cx + dx, cy + dy)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Tile prewarm {}/{}/{}/{}: {}", scene_id, zoom, cx + dx, cy + dy, exc)

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
        try:
            from rasterio.features import geometry_mask
            from rasterio.transform import from_bounds

            # Row 0 = north (lat_max), matching image / PNG orientation
            transform = from_bounds(lon_min, lat_min, lon_max, lat_max, size, size)
            outside = geometry_mask(
                [geom],
                out_shape=(size, size),
                transform=transform,
                all_touched=True,
                invert=False,
            )
            return ~outside
        except Exception:  # noqa: BLE001
            # Fallback: coarse point sampling
            xs = np.linspace(lon_min, lon_max, size, endpoint=False) + (lon_max - lon_min) / (2 * size)
            ys = np.linspace(lat_max, lat_min, size, endpoint=False) + (lat_min - lat_max) / (2 * size)
            step = 8
            mask_small = np.zeros((size // step, size // step), dtype=bool)
            for iy, lat in enumerate(ys[::step]):
                for ix, lon in enumerate(xs[::step]):
                    mask_small[iy, ix] = geom.contains(Point(lon, lat)) or geom.touches(Point(lon, lat))
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
        *,
        already_signed: bool = False,
    ) -> np.ndarray:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        bands: list[np.ndarray] = []
        if already_signed:
            signed = cog_urls
        else:
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
        """Fast windowed SAR read via WarpedVRT (full-scene reproject was 10–40s/tile)."""
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.vrt import WarpedVRT
        from rasterio.windows import from_bounds

        url = self._s3_to_https(cog_url)
        dst = np.zeros((self.TILE_SIZE, self.TILE_SIZE), dtype=np.float32)
        with rasterio.Env(**GDAL_ENV):
            with rasterio.open(url) as src:
                src_crs = src.crs
                if src_crs is None and src.gcps and src.gcps[0]:
                    # GCP-only products: fall back to slower full reproject
                    from rasterio.warp import reproject

                    dst_transform = rasterio.transform.from_bounds(
                        lon_min, lat_min, lon_max, lat_max, self.TILE_SIZE, self.TILE_SIZE
                    )
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=dst,
                        src_transform=None,
                        src_crs=src.gcps[1],
                        src_gcps=src.gcps[0],
                        dst_transform=dst_transform,
                        dst_crs="EPSG:4326",
                        resampling=Resampling.bilinear,
                        src_nodata=0,
                        dst_nodata=0,
                    )
                else:
                    with WarpedVRT(
                        src,
                        crs="EPSG:4326",
                        resampling=Resampling.bilinear,
                    ) as vrt:
                        window = from_bounds(
                            lon_min, lat_min, lon_max, lat_max, transform=vrt.transform
                        )
                        data = vrt.read(
                            1,
                            window=window,
                            out_shape=(self.TILE_SIZE, self.TILE_SIZE),
                            boundless=True,
                            fill_value=0,
                        )
                        dst = data.astype(np.float32)
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
        sem = _tile_semaphore()
        acquired = sem.acquire(timeout=90)
        if not acquired:
            logger.warning("Tile semaphore timeout {}/{}/{}/{}", scene_id, z, x, y)
            return self._empty_tile()
        try:
            try:
                if layer.get("source") == "sentinel1_grd":
                    rgb = self._read_s1_gray(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
                elif layer.get("cog_urls"):
                    signed = self._ensure_signed_cog_urls(layer)
                    rgb = self._read_landsat_rgb(
                        signed, lon_min, lat_min, lon_max, lat_max, already_signed=True
                    )
                else:
                    rgb = self._read_rgb_cog(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scene tile read failed {}/{}/{}/{}: {}", scene_id, z, x, y, exc)
                # Do not cache failures — next request can retry after transient COG/SAS errors
                return self._empty_tile()

            # Clip to tilted STAC footprint (critical for Landsat / S1 swaths)
            # Skip dense mask for S1 — WarpedVRT already leaves exterior as nodata/0,
            # and the mask was adding seconds per tile (Serveo timeouts).
            if layer.get("source") == "sentinel1_grd":
                mask = None
            else:
                mask = self._footprint_mask(
                    layer.get("footprint"), lon_min, lat_min, lon_max, lat_max
                )
            png = self._to_rgba(rgb, mask, mode)
            cache_path.write_bytes(png)
            return png
        finally:
            sem.release()

    def render_preview(self, scene_id: str, size: int | None = None) -> bytes:
        """Single ImageOverlay preview covering the scene bounds (shows immediately while XYZ tiles load)."""
        import io

        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds as window_from_bounds
        import rasterio

        layer = self.get_layer(scene_id)
        if not layer:
            raise NotFoundError("Scene imagery layer not prepared — open the eye overlay first")

        size = size or self.PREVIEW_SIZE
        west, south, east, north = (float(v) for v in layer["bounds"])
        mode = layer.get("render_mode") or "rgb"
        # Slight pad so preview edges aren't clipped oddly
        pad_x = (east - west) * 0.01
        pad_y = (north - south) * 0.01
        lon_min, lon_max = west - pad_x, east + pad_x
        lat_min, lat_max = south - pad_y, north + pad_y

        try:
            if layer.get("source") == "sentinel1_grd":
                # Reuse tile reader at preview resolution via temporary override
                old = self.TILE_SIZE
                self.TILE_SIZE = size
                try:
                    rgb = self._read_s1_gray(layer["cog_url"], lon_min, lat_min, lon_max, lat_max)
                finally:
                    self.TILE_SIZE = old
            elif layer.get("cog_urls"):
                signed = self._ensure_signed_cog_urls(layer)
                bands: list[np.ndarray] = []
                with rasterio.Env():
                    for name in ("red", "green", "blue"):
                        with rasterio.open(signed[name]) as src:
                            left, bottom, right, top = transform_bounds(
                                "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                            )
                            window = window_from_bounds(
                                left, bottom, right, top, transform=src.transform
                            )
                            arr = src.read(
                                1,
                                out_shape=(size, size),
                                window=window,
                                resampling=Resampling.bilinear,
                                boundless=True,
                                fill_value=0,
                            )
                            bands.append(arr.astype(np.float32))
                stacked = np.stack(bands, axis=0)
                refl = np.clip(stacked * 0.0000275 - 0.2, 0, 1)
                rgb = (refl * 10000).astype(np.float32)
            else:
                with rasterio.Env(**GDAL_ENV):
                    with rasterio.open(layer["cog_url"]) as src:
                        left, bottom, right, top = transform_bounds(
                            "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                        )
                        window = window_from_bounds(
                            left, bottom, right, top, transform=src.transform
                        )
                        count = min(3, src.count)
                        data = src.read(
                            indexes=list(range(1, count + 1)),
                            out_shape=(count, size, size),
                            window=window,
                            resampling=Resampling.bilinear,
                            boundless=True,
                            fill_value=0,
                        )
                if data.shape[0] == 1:
                    rgb = np.stack([data[0], data[0], data[0]], axis=0)
                else:
                    rgb = data[:3]

            # Footprint mask at preview resolution
            old = self.TILE_SIZE
            self.TILE_SIZE = size
            try:
                mask = self._footprint_mask(
                    layer.get("footprint"), lon_min, lat_min, lon_max, lat_max
                )
            finally:
                self.TILE_SIZE = old
            return self._to_rgba(rgb, mask, mode)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scene preview failed {}: {}", scene_id, exc)
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

    def _preview_cache_path(self, scene_id: str, size: int) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", scene_id)[:180]
        return self.tile_cache / safe / f"preview_{size}.png"

    def ensure_preview(self, scene_id: str, size: int = 384) -> bytes:
        """Return cached full-scene preview PNG, generating on first request."""
        path = self._preview_cache_path(scene_id, size)
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()
        png = self.render_preview(scene_id, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return png

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
                    # Cubic reads sharper detail for map overlays than bilinear
                    resampling=Resampling.cubic if size >= 512 else Resampling.bilinear,
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
        for name in ("red", "green", "blue", "nir", "swir", "swir2", "thermal"):
            href = analysis.get(name)
            if not href:
                continue
            try:
                if name == "thermal" and scale == "landsat_c2_sr":
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

        return bands, bounds, layer.get("footprint"), layer
