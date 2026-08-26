"""Collection-aware scene imagery: S2 TCI, S1 SAR, Landsat/MODIS via PC tiles."""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Any, Sequence
from urllib.parse import quote

import httpx
import numpy as np
from loguru import logger
from PIL import Image
from shapely.geometry import Point, shape

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, NotFoundError, ValidationError

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
PC_TILEJSON_URL = "https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json"

GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_TIMEOUT": "60",
    # Speed: reuse HTTP ranges + modest decode cache for interactive previews
    "GDAL_CACHEMAX": "256",
    "GDAL_NUM_THREADS": "2",
    "CPL_VSIL_CURL_CACHE_SIZE": "200000000",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "100000000",
}

# Interactive analysis grid — tools share this ceiling unless the client asks higher
INTERACTIVE_PREVIEW_MAX = 1024

# Canonical analysis keys (order used when loading the full set)
ANALYSIS_BAND_ORDER: tuple[str, ...] = (
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
    "qa_pixel",
    "scl",
    "vv",
    "vh",
)

# Requested logical name → STAC / alias keys that satisfy it
BAND_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "swir": ("swir", "swir16"),
    "swir2": ("swir2", "swir22"),
    "nir": ("nir", "nir08"),
    "thermal": ("thermal", "lwir11"),
    "blue": ("blue",),
    "green": ("green",),
    "red": ("red",),
    "coastal": ("coastal",),
    "rededge1": ("rededge1",),
    "rededge2": ("rededge2",),
    "rededge3": ("rededge3",),
    "nir08": ("nir08", "nir"),
    "nir09": ("nir09",),
    "swir16": ("swir16", "swir"),
    "swir22": ("swir22", "swir2"),
    "qa_pixel": ("qa_pixel",),
    "scl": ("scl",),
    "vv": ("vv",),
    "vh": ("vh",),
    "lwir11": ("lwir11", "thermal"),
}

# Fast PNG for map overlays (optimize=True is very slow on large RGBA)
FAST_PNG_KWARGS: dict[str, Any] = {"optimize": False, "compress_level": 3}

# Registry schema version — bump to invalidate slow Landsat self-tile layers
LAYER_VERSION = 5

# In-process SAS cache: unsigned_href -> (signed_href, expiry_epoch)
_PC_SIGN_CACHE: dict[str, tuple[str, float]] = {}

# Fallback product filenames when STAC hrefs omit a basename
S2_BAND_FILES: dict[str, str] = {
    "coastal": "B01.tif",
    "blue": "B02.tif",
    "green": "B03.tif",
    "red": "B04.tif",
    "rededge1": "B05.tif",
    "rededge2": "B06.tif",
    "rededge3": "B07.tif",
    "nir": "B08.tif",
    "nir08": "B8A.tif",
    "nir09": "B09.tif",
    "swir16": "B11.tif",
    "swir22": "B12.tif",
    "scl": "SCL.tif",
    "aot": "AOT.tif",
    "wvp": "WVP.tif",
    "visual": "TCI.tif",
}
S1_BAND_FILES: dict[str, str] = {
    "vv": "VV.tif",
    "vh": "VH.tif",
}
LANDSAT_BAND_FILES: dict[str, str] = {
    "blue": "SR_B2.TIF",
    "green": "SR_B3.TIF",
    "red": "SR_B4.TIF",
    "nir08": "SR_B5.TIF",
    "nir": "SR_B5.TIF",
    "swir16": "SR_B6.TIF",
    "swir": "SR_B6.TIF",
    "swir22": "SR_B7.TIF",
    "swir2": "SR_B7.TIF",
    "lwir11": "ST_B10.TIF",
    "thermal": "ST_B10.TIF",
    "qa_pixel": "QA_PIXEL.TIF",
}

# Landsat Collection-2 Level-2 scale / offset (USGS)
LANDSAT_C2_SR_SCALE = 0.0000275
LANDSAT_C2_SR_OFFSET = -0.2
LANDSAT_C2_ST_SCALE = 0.00341802
LANDSAT_C2_ST_OFFSET = 149.0
# QA_PIXEL bits to treat as invalid for optical indices (C2 bitfield)
# 0=Fill, 1=Dilated Cloud, 2=Cirrus, 3=Cloud, 4=Cloud Shadow
LANDSAT_QA_INVALID_MASK = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)

# Sentinel-2 L2A BOA reflectance (ESA PB ≥ 04.00 / Element84 Earth Search)
SENTINEL2_L2A_SCALE = 0.0001
SENTINEL2_L2A_OFFSET = -0.1
# SCL classes to mask for optical indices (ESA Scene Classification)
# Keep 4=vegetation, 5=not vegetated, 6=water, 7=unclassified
S2_SCL_INVALID = frozenset({0, 1, 2, 3, 8, 9, 10, 11})


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
        if "SENTINEL-3" in c or c in {"S3", "OLCI", "SLSTR"} or c.startswith("S3-"):
            return "SENTINEL-3"
        if "SENTINEL-5" in c or "S5P" in c:
            return "SENTINEL-5P"
        if "SMOS" in c:
            return "SMOS"
        if "LANDSAT-8" in c or c in {"LC08", "L8"}:
            return "LANDSAT-8"
        if "LANDSAT-9" in c or c in {"LC09", "L9"}:
            return "LANDSAT-9"
        if "LANDSAT-7" in c or c in {"LE07", "L7"}:
            return "LANDSAT-7"
        if "LANDSAT" in c:
            return "LANDSAT-8"
        if c in {"MODIS", "TERRAAQUA", "TERRA", "AQUA"} or "MODIS" in c:
            return "MODIS"
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

    @staticmethod
    def _stac_band_meta(
        asset_key: str,
        asset: dict[str, Any],
        *,
        fallback_filename: str | None = None,
    ) -> dict[str, Any]:
        """Build download metadata from a STAC asset (real filename + extension)."""
        href = str(asset.get("href") or "")
        path_part = href.split("?", 1)[0]
        filename = path_part.rsplit("/", 1)[-1] if path_part else ""
        if not filename or "." not in filename:
            filename = fallback_filename or f"{asset_key}.tif"
        ext = Path(filename).suffix or ".tif"
        media = str(asset.get("type") or "image/tiff; application=geotiff")
        is_tif = "tif" in ext.lower() or "tiff" in media.lower()
        return {
            "id": asset_key,
            "href": href,
            "filename": filename,
            "extension": ext if ext.startswith(".") else f".{ext}",
            "title": str(asset.get("title") or asset_key),
            "media_type": media,
            "format": "GeoTIFF" if is_tif else ext.lstrip(".").upper() or "GeoTIFF",
            "code": Path(filename).stem,
        }

    def _sign_pc(self, href: str, client: httpx.Client | None = None) -> str:
        """Sign a Planetary Computer blob URL, with in-memory reuse to avoid 429s."""
        now = time.time()
        cached = _PC_SIGN_CACHE.get(href)
        if cached and cached[1] > now + 180:
            return cached[0]

        owns_client = client is None
        if owns_client:
            client = httpx.Client(timeout=45.0, follow_redirects=True)
        assert client is not None
        try:
            last_status = 0
            for attempt in range(4):
                resp = client.get(PC_SIGN_URL, params={"href": href})
                last_status = resp.status_code
                if resp.status_code == 200:
                    payload = resp.json()
                    signed = str(payload["href"])
                    expiry_raw = payload.get("msft:expiry") or payload.get("expiry")
                    expiry = now + 50 * 60
                    if isinstance(expiry_raw, str):
                        try:
                            exp_dt = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
                            expiry = exp_dt.timestamp()
                        except ValueError:
                            pass
                    _PC_SIGN_CACHE[href] = (signed, expiry)
                    # Cap cache size
                    if len(_PC_SIGN_CACHE) > 512:
                        oldest = sorted(_PC_SIGN_CACHE.items(), key=lambda kv: kv[1][1])[:128]
                        for key, _ in oldest:
                            _PC_SIGN_CACHE.pop(key, None)
                    return signed
                if resp.status_code == 429:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                break
            raise NotFoundError(f"Failed to sign Landsat asset ({last_status})")
        finally:
            if owns_client:
                client.close()

    def _pc_xyz_template(
        self,
        *,
        collection: str,
        item_id: str,
        assets: list[str],
        color_formula: str | None = None,
        tilejson_href: str | None = None,
        client: httpx.Client | None = None,
    ) -> str | None:
        """Resolve a hosted XYZ tile template from Planetary Computer (fast map path)."""
        owns = client is None
        if owns:
            client = httpx.Client(timeout=45.0, follow_redirects=True)
        assert client is not None
        try:
            href = tilejson_href
            if not href:
                params = [("collection", collection), ("item", item_id)]
                for a in assets:
                    params.append(("assets", a))
                if color_formula:
                    params.append(("color_formula", color_formula))
                q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params)
                href = f"{PC_TILEJSON_URL}?{q}"
            resp = client.get(href)
            if resp.status_code != 200:
                logger.warning("PC tilejson {} → {}", collection, resp.status_code)
                return None
            tiles = (resp.json() or {}).get("tiles") or []
            if not tiles:
                return None
            return str(tiles[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("PC tilejson resolve failed: {}", exc)
            return None
        finally:
            if owns:
                client.close()

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
                spectral_keys = (
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
                    "scl",
                )
                analysis_bands: dict[str, str] = {}
                download_bands: dict[str, dict[str, Any]] = {}
                for k in spectral_keys:
                    asset = assets.get(k) or {}
                    if not asset.get("href"):
                        continue
                    analysis_bands[k] = asset["href"]
                    download_bands[k] = self._stac_band_meta(
                        k, asset, fallback_filename=S2_BAND_FILES.get(k)
                    )
                # Friendly aliases used by indices only (not shown in download picker)
                if "swir16" in analysis_bands:
                    analysis_bands["swir"] = analysis_bands["swir16"]
                if "swir22" in analysis_bands:
                    analysis_bands["swir2"] = analysis_bands["swir22"]
                # Do not alias SWIR1→SWIR2 (NBR needs distinct SWIR2 / B12)
                if "nir08" in analysis_bands and "nir" not in analysis_bands:
                    analysis_bands["nir"] = analysis_bands["nir08"]
                # BOA scale/offset from STAC (PB ≥ 04.00 → offset −0.1)
                boa_scale, boa_offset = self._s2_boa_scale_offset(assets, props)
                return {
                    "stac_id": feat.get("id"),
                    "cog_url": assets["visual"]["href"],
                    "analysis_bands": analysis_bands,
                    "download_bands": download_bands,
                    "sign": None,
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "render_mode": "rgb",
                    "source": "sentinel2_l2a",
                    "boa_scale": boa_scale,
                    "boa_offset": boa_offset,
                    "processing_baseline": props.get("s2:processing_baseline"),
                    "bands": {"R": "B04.tif", "G": "B03.tif", "B": "B02.tif"},
                    "label": "Sentinel-2 L2A true-color (TCI)",
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
                download_bands: dict[str, dict[str, Any]] = {}
                for key in ("vv", "vh"):
                    asset = assets.get(key) or {}
                    if not asset.get("href"):
                        continue
                    href = self._s3_to_https(asset["href"])
                    analysis_bands[key] = href
                    download_bands[key] = self._stac_band_meta(
                        key,
                        {**asset, "href": href},
                        fallback_filename=S1_BAND_FILES.get(key),
                    )
                return {
                    "stac_id": feat.get("id"),
                    "cog_url": self._s3_to_https(assets[pol]["href"]),
                    "analysis_bands": analysis_bands,
                    "download_bands": download_bands,
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": None,
                    "render_mode": "grayscale",
                    "source": "sentinel1_grd",
                    "polarization": pol.upper(),
                    "bands": {"R": f"{pol.upper()}.tif", "G": f"{pol.upper()}.tif", "B": f"{pol.upper()}.tif"},
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
        platform_q = {
            "LANDSAT-8": "landsat-8",
            "LANDSAT-9": "landsat-9",
            "LANDSAT-7": "landsat-7",
        }.get(platform, "landsat-8")
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
                want_mission = platform_q.replace("landsat-", "")  # "7" | "8" | "9"
                for feat in features:
                    props = feat.get("properties") or {}
                    plat = (props.get("platform") or "").lower().replace("_", "-")
                    # Hard-match Landsat-7/8/9 so an L9 catalog scene never binds L8 COGs
                    # (same band numbers, but wrong product / calibration / date).
                    if want_mission in {"7", "8", "9"} and plat:
                        plat_mission = None
                        for m in ("7", "8", "9"):
                            if f"landsat-{m}" in plat or plat.endswith(f"-{m}") or plat == m:
                                plat_mission = m
                                break
                        if plat_mission is not None and plat_mission != want_mission:
                            continue
                    cov = self._coverage(bbox, feat.get("bbox") or [])
                    if cov < 0.1:
                        continue
                    assets = feat.get("assets") or {}
                    if not all(k in assets and assets[k].get("href") for k in ("red", "green", "blue")):
                        continue
                    cloud = float(props.get("eo:cloud_cover") or 0)
                    target = float(target_cloud) if target_cloud is not None else cloud
                    cloud_delta = abs(cloud - target)
                    score = cov * 10.0 - cloud_delta / 100.0
                    scored.append((score, feat))
                if not scored:
                    last_error = (
                        f"no covering {platform_q} in {start}..{end}"
                    )
                    continue
                scored.sort(key=lambda t: -t[0])
                feat = scored[0][1]
                props = feat.get("properties") or {}
                assets = feat.get("assets") or {}
                analysis_bands: dict[str, str] = {
                    "red": assets["red"]["href"],
                    "green": assets["green"]["href"],
                    "blue": assets["blue"]["href"],
                }
                download_bands: dict[str, dict[str, Any]] = {
                    k: self._stac_band_meta(
                        k, assets[k], fallback_filename=LANDSAT_BAND_FILES.get(k)
                    )
                    for k in ("red", "green", "blue")
                }
                if assets.get("nir08", {}).get("href"):
                    analysis_bands["nir"] = assets["nir08"]["href"]
                    download_bands["nir08"] = self._stac_band_meta(
                        "nir08",
                        assets["nir08"],
                        fallback_filename=LANDSAT_BAND_FILES.get("nir08"),
                    )
                if assets.get("swir16", {}).get("href"):
                    analysis_bands["swir"] = assets["swir16"]["href"]
                    download_bands["swir16"] = self._stac_band_meta(
                        "swir16",
                        assets["swir16"],
                        fallback_filename=LANDSAT_BAND_FILES.get("swir16"),
                    )
                if assets.get("swir22", {}).get("href"):
                    analysis_bands["swir2"] = assets["swir22"]["href"]
                    download_bands["swir22"] = self._stac_band_meta(
                        "swir22",
                        assets["swir22"],
                        fallback_filename=LANDSAT_BAND_FILES.get("swir22"),
                    )
                # Do not alias SWIR1→SWIR2 — NBR/burn composites need true B7
                if assets.get("lwir11", {}).get("href"):
                    analysis_bands["thermal"] = assets["lwir11"]["href"]
                    download_bands["lwir11"] = self._stac_band_meta(
                        "lwir11",
                        assets["lwir11"],
                        fallback_filename=LANDSAT_BAND_FILES.get("lwir11"),
                    )
                if assets.get("qa_pixel", {}).get("href"):
                    analysis_bands["qa_pixel"] = assets["qa_pixel"]["href"]
                    download_bands["qa_pixel"] = self._stac_band_meta(
                        "qa_pixel",
                        assets["qa_pixel"],
                        fallback_filename=LANDSAT_BAND_FILES.get("qa_pixel"),
                    )
                stac_id = str(feat.get("id") or "")
                color_formula = "gamma RGB 2.7, saturation 1.5, sigmoidal RGB 15 0.35"
                external_tile = self._pc_xyz_template(
                    collection="landsat-c2-l2",
                    item_id=stac_id,
                    assets=["red", "green", "blue"],
                    color_formula=color_formula,
                    tilejson_href=(assets.get("tilejson") or {}).get("href"),
                    client=client,
                )
                thumbnail = (assets.get("rendered_preview") or {}).get("href")
                return {
                    "stac_id": stac_id,
                    "cog_urls": {
                        "red": assets["red"]["href"],
                        "green": assets["green"]["href"],
                        "blue": assets["blue"]["href"],
                    },
                    "analysis_bands": analysis_bands,
                    "download_bands": download_bands,
                    "sign": "planetary_computer",
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "render_mode": "rgb",
                    "source": "landsat_c2_l2",
                    "platform": props.get("platform") or platform_q,
                    "bands": {"R": "SR_B4.TIF", "G": "SR_B3.TIF", "B": "SR_B2.TIF"},
                    "label": (
                        f"{platform} true-color ("
                        + {
                            "LANDSAT-9": "OLI-2",
                            "LANDSAT-8": "OLI",
                            "LANDSAT-7": "ETM+",
                        }.get(platform, "OLI")
                        + ")"
                    ),
                    "external_tile_url": external_tile,
                    "thumbnail_url": thumbnail,
                }
        raise NotFoundError(f"No Landsat imagery found ({last_error})")

    def find_modis(
        self,
        bbox: list[float],
        sensing_time: str | None,
        platform_hint: str | None = None,
    ) -> dict[str, Any]:
        """Match MODIS 8-day surface reflectance via Planetary Computer hosted tiles."""
        last_error = "empty"
        hint = (platform_hint or "").upper()
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for start, end in self._datetime_windows(sensing_time):
                features = self._stac_search(
                    client,
                    PC_STAC_URL,
                    ["modis-09A1-061"],
                    bbox,
                    start,
                    end,
                    limit=20,
                )
                scored: list[tuple[float, dict[str, Any]]] = []
                for feat in features:
                    cov = self._coverage(bbox, feat.get("bbox") or [])
                    if cov < 0.05:
                        continue
                    assets = feat.get("assets") or {}
                    # True-color-ish: B01 red, B04 green, B03 blue
                    if not all(
                        assets.get(k, {}).get("href")
                        for k in ("sur_refl_b01", "sur_refl_b04", "sur_refl_b03")
                    ):
                        continue
                    fid = str(feat.get("id") or "")
                    is_aqua = fid.startswith("MYD")
                    is_terra = fid.startswith("MOD")
                    plat_bonus = 0.0
                    if "AQUA" in hint and not is_aqua:
                        plat_bonus = -0.25
                    elif "TERRA" in hint and "AQUA" not in hint and not is_terra:
                        plat_bonus = -0.25
                    score = cov * 10.0 + plat_bonus
                    scored.append((score, feat))
                if not scored:
                    last_error = f"no covering MODIS in {start}..{end}"
                    continue
                scored.sort(key=lambda t: -t[0])
                feat = scored[0][1]
                props = feat.get("properties") or {}
                assets = feat.get("assets") or {}
                stac_id = str(feat.get("id") or "")
                analysis_bands = {
                    "red": assets["sur_refl_b01"]["href"],
                    "green": assets["sur_refl_b04"]["href"],
                    "blue": assets["sur_refl_b03"]["href"],
                    "nir": assets.get("sur_refl_b02", {}).get("href")
                    or assets["sur_refl_b01"]["href"],
                }
                if assets.get("sur_refl_b06", {}).get("href"):
                    analysis_bands["swir"] = assets["sur_refl_b06"]["href"]
                if assets.get("sur_refl_b07", {}).get("href"):
                    analysis_bands["swir2"] = assets["sur_refl_b07"]["href"]
                download_bands = {
                    k: self._stac_band_meta(k, assets[k])
                    for k in (
                        "sur_refl_b01",
                        "sur_refl_b02",
                        "sur_refl_b03",
                        "sur_refl_b04",
                        "sur_refl_b05",
                        "sur_refl_b06",
                        "sur_refl_b07",
                    )
                    if assets.get(k, {}).get("href")
                }
                external_tile = self._pc_xyz_template(
                    collection="modis-09A1-061",
                    item_id=stac_id,
                    assets=["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"],
                    color_formula="gamma RGB 2.2, saturation 1.2, sigmoidal RGB 10 0.35",
                    tilejson_href=(assets.get("tilejson") or {}).get("href"),
                    client=client,
                )
                return {
                    "stac_id": stac_id,
                    "cog_urls": {
                        "red": assets["sur_refl_b01"]["href"],
                        "green": assets["sur_refl_b04"]["href"],
                        "blue": assets["sur_refl_b03"]["href"],
                    },
                    "analysis_bands": analysis_bands,
                    "download_bands": download_bands,
                    "sign": "planetary_computer",
                    "bbox": [float(x) for x in (feat.get("bbox") or bbox)],
                    "footprint": feat.get("geometry"),
                    "datetime": props.get("datetime") or props.get("start_datetime"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "render_mode": "rgb",
                    "source": "modis_09a1",
                    "platform": "aqua" if stac_id.startswith("MYD") else "terra",
                    "bands": {"R": "sur_refl_b01", "G": "sur_refl_b04", "B": "sur_refl_b03"},
                    "label": "MODIS 8-day true-color (09A1)",
                    "external_tile_url": external_tile,
                    "thumbnail_url": (assets.get("rendered_preview") or {}).get("href"),
                }
        raise NotFoundError(f"No MODIS imagery found ({last_error})")

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
        elif coll in {"LANDSAT-8", "LANDSAT-9", "LANDSAT-7"}:
            match = self.find_landsat(search_bbox, sensing_time, cloud_cover, coll)
        elif coll == "MODIS":
            match = self.find_modis(search_bbox, sensing_time, platform_hint=collection)
        elif coll in {"SENTINEL-3", "SENTINEL-5P", "SMOS"}:
            # Do not silently remap to Sentinel-2 — that would fake optical tools.
            from app.services.satellite_bands import unsupported_image_processing_reason

            raise ValidationError(
                unsupported_image_processing_reason(coll)
                or f"{coll} imagery is not available for map eye-load / indices in this app."
            )
        elif coll == "SENTINEL-2":
            match = self.find_sentinel2(search_bbox, sensing_time, cloud_cover)
        else:
            # Unknown optical-ish collections: try Sentinel-2 L2A, keep original label
            match = self.find_sentinel2(search_bbox, sensing_time, cloud_cover)
            coll = "SENTINEL-2"

        stac_fp = match.get("footprint")
        # Display bounds from actual STAC footprint (tilted scenes → correct envelope)
        display_bounds = self._bbox_from_footprint(stac_fp) or match.get("bbox") or search_bbox

        # Prefer Planetary Computer hosted XYZ for Landsat/MODIS (avoids per-tile SAS 429s)
        external_tiles = match.get("external_tile_url")
        local_tiles = f"/api/v1/catalog/scenes/{scene_id}/tiles/{{z}}/{{x}}/{{y}}.png"
        tile_template = external_tiles or local_tiles

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
            "download_bands": match.get("download_bands") or {},
            "sign": match.get("sign"),
            "stac_id": match.get("stac_id"),
            "bounds": display_bounds,
            "footprint": stac_fp,
            "acquisition_date": match.get("datetime"),
            "cloud_cover": match.get("cloud_cover"),
            "polarization": match.get("polarization"),
            "thumbnail_url": match.get("thumbnail_url"),
            "external_tile_url": external_tiles,
            "tile_url_template": tile_template,
            "boa_scale": match.get("boa_scale"),
            "boa_offset": match.get("boa_offset"),
            "processing_baseline": match.get("processing_baseline"),
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
        img.save(buf, format="PNG", **FAST_PNG_KWARGS)
        return buf.getvalue()

    def _footprint_mask(
        self, footprint: dict[str, Any] | None, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ) -> np.ndarray | None:
        """Boolean mask (True=inside footprint) for the tile grid."""
        if not footprint:
            return None
        size = self.TILE_SIZE
        try:
            from affine import Affine
            from rasterio.features import geometry_mask

            transform = Affine(
                (lon_max - lon_min) / size,
                0.0,
                lon_min,
                0.0,
                (lat_min - lat_max) / size,
                lat_max,
            )
            outside = geometry_mask(
                [footprint],
                out_shape=(size, size),
                transform=transform,
                all_touched=True,
                invert=False,
            )
            return ~outside
        except Exception:  # noqa: BLE001
            pass
        try:
            geom = shape(footprint)
        except Exception:  # noqa: BLE001
            return None
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
                # Bilinear is far cheaper than cubic for interactive map tiles
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

        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            signed = {k: self._sign_pc(v, client) for k, v in cog_urls.items()}

        def _read_one(name: str) -> np.ndarray:
            with rasterio.Env(**GDAL_ENV):
                with rasterio.open(signed[name]) as src:
                    left, bottom, right, top = transform_bounds(
                        "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                    )
                    window = from_bounds(left, bottom, right, top, transform=src.transform)
                    oversampling = (
                        float(window.width) < self.TILE_SIZE
                        or float(window.height) < self.TILE_SIZE
                    )
                    resampling = Resampling.nearest if oversampling else Resampling.bilinear
                    arr = src.read(
                        1,
                        out_shape=(self.TILE_SIZE, self.TILE_SIZE),
                        window=window,
                        resampling=resampling,
                        boundless=True,
                        fill_value=0,
                    )
                    return arr.astype(np.float32)

        with ThreadPoolExecutor(max_workers=3) as pool:
            bands = list(pool.map(_read_one, ("red", "green", "blue")))
        stacked = np.stack(bands, axis=0)
        # Landsat C2 SR scaling (also works ok for MODIS-ish scaled ints after stretch)
        if float(np.nanmax(stacked)) > 2000:
            refl = np.clip(
                stacked * LANDSAT_C2_SR_SCALE + LANDSAT_C2_SR_OFFSET, 0, 1
            )
            return (refl * 10000).astype(np.float32)
        return stacked

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
            # Valid where any channel has real reflectance (not all-nan / all-zero fill)
            valid_mask = np.any(np.isfinite(stacked) & (stacked > 0), axis=0)
            stretched = np.zeros_like(stacked)
            if valid_mask.any():
                # Joint stretch keeps natural color balance for true-color tiles
                vals = stacked[:, valid_mask]
                lo = float(np.percentile(vals, 2))
                hi = float(np.percentile(vals, 98))
                # Soft-cap highlights (clouds) so land midtones stay visible
                if stacked.max() > 1.5:
                    # DN / reflectance*10000 path
                    hi = min(hi, max(lo + 1.0, float(np.percentile(vals, 90)) * 1.15))
                else:
                    hi = min(hi, max(lo + 0.04, 0.35 if stacked.max() <= 1.5 else hi))
                if hi <= lo:
                    hi = lo + 1e-6
                stretched = np.clip((stacked - lo) / (hi - lo), 0, 1)
                stretched = np.power(stretched, 1.0 / 1.15)
            rgb_u8 = (stretched * 255).astype(np.uint8)
            alpha = np.where(valid_mask, 255, 0).astype(np.uint8)

        if mask is not None:
            alpha = np.where(mask, alpha, 0).astype(np.uint8)

        rgba = np.dstack([rgb_u8[0], rgb_u8[1], rgb_u8[2], alpha])
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", **FAST_PNG_KWARGS)
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

    @staticmethod
    def analysis_grid_shape(
        bounds: list[float], max_edge: int = 1024
    ) -> tuple[int, int]:
        """Return (height, width) preserving AOI aspect ratio up to max_edge."""
        west, south, east, north = (float(v) for v in bounds)
        width_deg = max(east - west, 1e-9)
        height_deg = max(north - south, 1e-9)
        mid_lat = (south + north) / 2.0
        width_m = width_deg * max(0.2, float(np.cos(np.radians(mid_lat))))
        height_m = height_deg
        if width_m >= height_m:
            width = int(max_edge)
            height = max(64, int(round(max_edge * height_m / width_m)))
        else:
            height = int(max_edge)
            width = max(64, int(round(max_edge * width_m / height_m)))
        return height, width

    @staticmethod
    def _s2_boa_scale_offset(
        assets: dict[str, Any], props: dict[str, Any]
    ) -> tuple[float, float]:
        """Resolve Sentinel-2 L2A BOA scale/offset from STAC or processing baseline."""
        scale = SENTINEL2_L2A_SCALE
        offset = SENTINEL2_L2A_OFFSET
        for key in ("red", "nir", "blue", "green"):
            bands_meta = (assets.get(key) or {}).get("raster:bands") or []
            if bands_meta and isinstance(bands_meta[0], dict):
                try:
                    if bands_meta[0].get("scale") is not None:
                        scale = float(bands_meta[0]["scale"])
                    if bands_meta[0].get("offset") is not None:
                        offset = float(bands_meta[0]["offset"])
                    return scale, offset
                except (TypeError, ValueError):
                    break
        # ESA PB ≥ 04.00 introduced BOA_ADD_OFFSET (−1000 DN → −0.1 reflectance)
        pb_raw = str(props.get("s2:processing_baseline") or "")
        try:
            if pb_raw and float(pb_raw) < 4.0:
                offset = 0.0
        except ValueError:
            pass
        return scale, offset

    def read_band_grid(
        self,
        href: str,
        bounds: list[float],
        size: int = 1024,
        *,
        sign: str | None = None,
        reflectance_scale: str | None = None,
        out_shape: tuple[int, int] | None = None,
        categorical: bool = False,
        boa_scale: float | None = None,
        boa_offset: float | None = None,
        client: httpx.Client | None = None,
        high_quality: bool = False,
    ) -> np.ndarray:
        """Sample a COG band into an analysis grid covering [west,south,east,north]."""
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        url = self._s3_to_https(href)
        if sign == "planetary_computer":
            url = self._sign_pc(url, client)

        west, south, east, north = (float(v) for v in bounds)
        height, width = out_shape or (size, size)
        env = GDAL_ENV if sign != "planetary_computer" else {
            "GDAL_CACHEMAX": GDAL_ENV["GDAL_CACHEMAX"],
            "GDAL_NUM_THREADS": GDAL_ENV["GDAL_NUM_THREADS"],
            "VSI_CACHE": "TRUE",
            "VSI_CACHE_SIZE": GDAL_ENV["VSI_CACHE_SIZE"],
        }
        src_nodata: float | None = None
        with rasterio.Env(**env):
            with rasterio.open(url) as src:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, west, south, east, north
                )
                window = from_bounds(left, bottom, right, top, transform=src.transform)
                # Categorical (SCL/QA): always nearest. Else bilinear for interactive
                # previews (cubic is much slower and rarely visible at ≤1024).
                oversampling = float(window.width) < width or float(window.height) < height
                if categorical or oversampling:
                    resampling = Resampling.nearest
                elif high_quality:
                    resampling = Resampling.cubic
                else:
                    resampling = Resampling.bilinear
                try:
                    src_nodata = float(src.nodata) if src.nodata is not None else None
                except Exception:  # noqa: BLE001
                    src_nodata = None
                data = src.read(
                    1,
                    out_shape=(height, width),
                    window=window,
                    resampling=resampling,
                    boundless=True,
                    fill_value=0,
                ).astype(np.float32)

        # Mask true nodata before reflectance scaling; keep dark-but-valid pixels.
        nodata_mask = data == 0
        if src_nodata is not None:
            try:
                nodata_mask = nodata_mask | np.isclose(data, float(src_nodata))
            except Exception:  # noqa: BLE001
                pass

        if reflectance_scale == "landsat_c2_sr":
            # USGS C2 L2 surface reflectance: ρ = DN × 0.0000275 − 0.2
            data = data * LANDSAT_C2_SR_SCALE + LANDSAT_C2_SR_OFFSET
            data[nodata_mask | (data < 0)] = np.nan
            data = np.clip(data, 0, 1)
            data[nodata_mask | ~np.isfinite(data)] = np.nan
        elif reflectance_scale == "landsat_c2_st":
            # USGS C2 L2 surface temperature ST_B10: Kelvin = DN × 0.00341802 + 149
            # Valid DN range starts at 293; fill = 0.
            dn = data
            invalid = nodata_mask | (dn < 293) | ~np.isfinite(dn)
            kelvin = dn * LANDSAT_C2_ST_SCALE + LANDSAT_C2_ST_OFFSET
            celsius = kelvin - 273.15
            celsius[invalid] = np.nan
            data = celsius
        elif reflectance_scale == "sentinel2_l2a":
            # ESA L2A BOA: ρ = DN × scale + offset (PB≥04.00 → 0.0001, −0.1)
            finite = data[np.isfinite(data) & ~nodata_mask]
            if finite.size and float(np.nanmax(finite)) > 1.5:
                sc = SENTINEL2_L2A_SCALE if boa_scale is None else float(boa_scale)
                off = SENTINEL2_L2A_OFFSET if boa_offset is None else float(boa_offset)
                data = data * sc + off
            data[nodata_mask | (data < 0)] = np.nan
            data = np.clip(data, 0, 1)
            data[nodata_mask | ~np.isfinite(data)] = np.nan
        else:
            data[nodata_mask] = np.nan
        return data

    def clip_bounds_to_layer(
        self, layer: dict[str, Any], bbox: list[float] | None
    ) -> list[float]:
        """Intersect request bbox with the scene layer bounds.

        Callers that want the original image extent should pass the scene layer
        bounds (or omit bbox). A place-pin search window must not be used alone
        or processed overlays shrink to a small inset on the map.
        """
        scene = [float(x) for x in layer["bounds"]]
        if not bbox or len(bbox) != 4:
            return scene
        west = max(scene[0], float(bbox[0]))
        south = max(scene[1], float(bbox[1]))
        east = min(scene[2], float(bbox[2]))
        north = min(scene[3], float(bbox[3]))
        if east - west < 1e-5 or north - south < 1e-5:
            return scene
        return [west, south, east, north]

    def read_visual_rgb(
        self,
        scene_id: str,
        bounds: list[float],
        size: int = 1024,
    ) -> tuple[np.ndarray, list[float]] | None:
        """Read Sentinel-2 TCI / Landsat RGB visual over bounds → float RGB in [0,1], shape (H,W,3)."""
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        layer = self.get_layer(scene_id)
        if not layer:
            return None
        west, south, east, north = (float(v) for v in bounds)
        target_h, target_w = self.analysis_grid_shape(bounds, max_edge=size)
        try:
            if layer.get("source") == "sentinel1_grd":
                return None

            if layer.get("cog_urls"):
                # Landsat: read each SR band at exact AOI shape, then reflectance scale
                planes: list[np.ndarray] = []
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    signed = {
                        k: self._sign_pc(v, client)
                        for k, v in layer["cog_urls"].items()
                    }
                with rasterio.Env():
                    for name in ("red", "green", "blue"):
                        with rasterio.open(signed[name]) as src:
                            left, bottom, right, top = transform_bounds(
                                "EPSG:4326", src.crs, west, south, east, north
                            )
                            window = from_bounds(
                                left, bottom, right, top, transform=src.transform
                            )
                            oversampling = (
                                float(window.width) < target_w
                                or float(window.height) < target_h
                            )
                            resampling = (
                                Resampling.nearest if oversampling else Resampling.bilinear
                            )
                            arr = src.read(
                                1,
                                out_shape=(target_h, target_w),
                                window=window,
                                resampling=resampling,
                                boundless=True,
                                fill_value=0,
                            ).astype(np.float32)
                            planes.append(arr)
                stacked = np.stack(planes, axis=0)
                stacked = np.clip(stacked * 0.0000275 - 0.2, 0, 1)
                stacked[stacked <= 0] = 0
            elif layer.get("cog_url"):
                # Sentinel-2 TCI / visual — already display-balanced RGB
                url = self._s3_to_https(layer["cog_url"])
                with rasterio.Env(**GDAL_ENV):
                    with rasterio.open(url) as src:
                        left, bottom, right, top = transform_bounds(
                            "EPSG:4326", src.crs, west, south, east, north
                        )
                        window = from_bounds(
                            left, bottom, right, top, transform=src.transform
                        )
                        oversampling = (
                            float(window.width) < target_w
                            or float(window.height) < target_h
                        )
                        resampling = (
                            Resampling.nearest if oversampling else Resampling.bilinear
                        )
                        count = min(3, src.count)
                        data = src.read(
                            indexes=list(range(1, count + 1)),
                            out_shape=(count, target_h, target_w),
                            window=window,
                            resampling=resampling,
                            boundless=True,
                            fill_value=0,
                        ).astype(np.float32)
                        if count == 1:
                            data = np.repeat(data, 3, axis=0)
                        stacked = data
                if stacked.max() > 1.5:
                    stacked = stacked / 255.0
                stacked = np.clip(stacked, 0, 1)
            else:
                return None

            return np.transpose(stacked, (1, 2, 0)), bounds
        except Exception as exc:  # noqa: BLE001
            logger.warning("Visual RGB read failed for {}: {}", scene_id, exc)
            return None

    @staticmethod
    def resolve_requested_band_keys(
        analysis: dict[str, Any],
        band_names: Sequence[str] | None,
        *,
        include_masks: bool = True,
        is_landsat: bool = False,
        is_s2: bool = False,
    ) -> list[str]:
        """Pick analysis keys to fetch; expand aliases and optionally QA/SCL masks."""
        if not analysis:
            return []
        if band_names is None:
            names = [n for n in ANALYSIS_BAND_ORDER if n in analysis]
        else:
            names: list[str] = []
            seen: set[str] = set()
            for req in band_names:
                aliases = BAND_NAME_ALIASES.get(req, (req,))
                for alt in aliases:
                    if alt in analysis and alt not in seen:
                        names.append(alt)
                        seen.add(alt)
                        break
            # Prefer product keys when both alias forms exist in analysis
            for product, alias in (("swir16", "swir"), ("swir22", "swir2"), ("nir08", "nir")):
                if product in analysis and alias in analysis and alias in seen and product not in seen:
                    names.append(product)
                    seen.add(product)

        if include_masks:
            if is_landsat and "qa_pixel" in analysis and "qa_pixel" not in names:
                names.append("qa_pixel")
            if is_s2 and "scl" in analysis and "scl" not in names:
                names.append("scl")
        return names

    @staticmethod
    def group_band_keys_by_href(
        analysis: dict[str, Any], names: Sequence[str]
    ) -> list[tuple[str, list[str]]]:
        """Collapse alias keys that share one COG href into a single fetch."""
        by_href: dict[str, list[str]] = defaultdict(list)
        for name in names:
            href = analysis.get(name)
            if not href:
                continue
            by_href[str(href)].append(name)
        return [(href, keys) for href, keys in by_href.items()]

    def load_analysis_bands(
        self,
        scene_id: str,
        size: int = 1024,
        bounds: list[float] | None = None,
        band_names: Sequence[str] | None = None,
    ) -> tuple[dict[str, np.ndarray], list[float], dict[str, Any] | None, dict[str, Any]]:
        """Load optical analysis bands for a prepared scene (optional AOI bounds).

        Pass ``band_names`` (e.g. NDVI → red,nir) to avoid fetching unused COGs.
        Identical href aliases are fetched once and shared. Band reads run in parallel.
        """
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

        bounds = self.clip_bounds_to_layer(layer, bounds)
        analysis = layer.get("analysis_bands") or {}
        sign = layer.get("sign")
        is_landsat = layer.get("source") == "landsat_c2_l2"
        is_s2 = (
            layer.get("source") in {"sentinel2_l2a", "sentinel2_tci"}
            or layer.get("collection") == "SENTINEL-2"
        )
        scale = "landsat_c2_sr" if is_landsat else "sentinel2_l2a"
        boa_scale = layer.get("boa_scale")
        boa_offset = layer.get("boa_offset")
        # Cap interactive grids; callers can still request lower sizes
        size = max(64, min(int(size), 2048))
        out_shape = self.analysis_grid_shape(bounds, max_edge=size)

        wanted = self.resolve_requested_band_keys(
            analysis,
            band_names,
            include_masks=True,
            is_landsat=is_landsat,
            is_s2=is_s2,
        )
        href_groups = self.group_band_keys_by_href(analysis, wanted)

        bands: dict[str, np.ndarray] = {}
        if not href_groups:
            return bands, bounds, layer.get("footprint"), layer

        def _scale_for(name: str) -> tuple[str | None, bool]:
            if name in {"vv", "vh"}:
                return None, False
            if name == "thermal" and is_landsat:
                return "landsat_c2_st", False
            if name == "thermal":
                return None, False
            if name in {"qa_pixel", "scl"}:
                return None, True
            return scale, False

        def _fetch_group(
            href: str, names: list[str], client: httpx.Client | None
        ) -> tuple[list[str], np.ndarray | None, str | None]:
            primary = names[0]
            band_scale, categorical = _scale_for(primary)
            try:
                arr = self.read_band_grid(
                    href,
                    bounds,
                    size,
                    sign=sign,
                    reflectance_scale=band_scale,
                    out_shape=out_shape,
                    categorical=categorical,
                    boa_scale=float(boa_scale) if boa_scale is not None else None,
                    boa_offset=float(boa_offset) if boa_offset is not None else None,
                    client=client,
                    high_quality=False,
                )
                return names, arr, None
            except Exception as exc:  # noqa: BLE001
                return names, None, str(exc)

        owns_client = sign == "planetary_computer"
        client: httpx.Client | None = None
        if owns_client:
            client = httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            workers = min(8, max(1, len(href_groups)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_fetch_group, href, names, client)
                    for href, names in href_groups
                ]
                for fut in futures:
                    names, arr, err = fut.result()
                    if err:
                        logger.warning(
                            "Failed to load analysis band(s) {} for {}: {}",
                            ",".join(names),
                            scene_id,
                            err,
                        )
                        continue
                    if arr is None:
                        continue
                    for name in names:
                        bands[name] = arr
        finally:
            if client is not None:
                client.close()

        # Alias STAC common-name duplicates only (same physical band / array)
        if "swir" not in bands and "swir16" in bands:
            bands["swir"] = bands["swir16"]
        if "swir2" not in bands and "swir22" in bands:
            bands["swir2"] = bands["swir22"]
        if "nir" not in bands and "nir08" in bands:
            bands["nir"] = bands["nir08"]
        # Never substitute SWIR1 for SWIR2 — breaks NBR (S2 B11 vs B12 / L8 B6 vs B7)

        # Apply Landsat QA_PIXEL cloud / shadow / fill mask to optical + thermal
        qa = bands.get("qa_pixel")
        if qa is not None and is_landsat:
            try:
                invalid = (qa.astype(np.uint16) & LANDSAT_QA_INVALID_MASK) != 0
                for key, arr in list(bands.items()):
                    if key == "qa_pixel":
                        continue
                    if arr.shape != invalid.shape:
                        continue
                    masked = arr.astype(np.float32, copy=True)
                    masked[invalid] = np.nan
                    bands[key] = masked
            except Exception as exc:  # noqa: BLE001
                logger.warning("QA_PIXEL mask failed for {}: {}", scene_id, exc)

        # Apply Sentinel-2 SCL mask (cloud / shadow / snow / nodata / cirrus)
        scl = bands.get("scl")
        if scl is not None and is_s2:
            try:
                scl_i = np.rint(scl).astype(np.int16)
                invalid = np.isin(scl_i, list(S2_SCL_INVALID))
                for key, arr in list(bands.items()):
                    if key == "scl":
                        continue
                    if arr.shape != invalid.shape:
                        continue
                    masked = arr.astype(np.float32, copy=True)
                    masked[invalid] = np.nan
                    bands[key] = masked
            except Exception as exc:  # noqa: BLE001
                logger.warning("SCL mask failed for {}: {}", scene_id, exc)

        return bands, bounds, layer.get("footprint"), layer

    # Stable picker order for real STAC product keys
    DOWNLOAD_BAND_ORDER: tuple[str, ...] = (
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
        "scl",
        "lwir11",
        "qa_pixel",
        "vv",
        "vh",
        "visual",
    )

    def _resolve_download_bands(self, layer: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return real product-band metadata (filename + extension) for a layer."""
        stored = layer.get("download_bands") or {}
        if stored:
            return stored

        # Legacy layers: synthesize filenames from known product naming
        analysis = layer.get("analysis_bands") or {}
        source = layer.get("source") or ""
        fallbacks = S2_BAND_FILES
        if source == "sentinel1_grd":
            fallbacks = S1_BAND_FILES
        elif source == "landsat_c2_l2":
            fallbacks = LANDSAT_BAND_FILES

        # Skip index-only aliases when real product keys exist
        skip = set()
        if "swir16" in analysis:
            skip.add("swir")
        if "swir22" in analysis:
            skip.add("swir2")
        if "nir08" in analysis and "nir" in analysis and source == "landsat_c2_l2":
            skip.add("nir")
        if "lwir11" in analysis:
            skip.add("thermal")

        out: dict[str, dict[str, Any]] = {}
        for key, href in analysis.items():
            if key in skip or not href:
                continue
            fname = fallbacks.get(key, f"{key}.tif")
            out[key] = self._stac_band_meta(
                key,
                {"href": href, "title": key, "type": "image/tiff; application=geotiff"},
                fallback_filename=fname,
            )
        return out

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
        """Return selectable product bands with real filenames/extensions."""
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

        download_bands = self._resolve_download_bands(layer)
        sign = layer.get("sign")
        analysis = layer.get("analysis_bands") or {}

        # Probe full COG sizes (Content-Length) so the UI can show ~MB, not tiny windows
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _size_for(key: str) -> tuple[str, int | None]:
            meta = download_bands[key]
            if meta.get("size_bytes"):
                try:
                    return key, int(meta["size_bytes"])
                except (TypeError, ValueError):
                    pass
            href = analysis.get(key) or meta.get("href")
            if not href:
                return key, None
            return key, self._probe_asset_size(str(href), sign)

        sizes: dict[str, int | None] = {}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(download_bands)))) as pool:
            futures = [pool.submit(_size_for, key) for key in download_bands]
            for fut in as_completed(futures):
                key, nbytes = fut.result()
                sizes[key] = nbytes
                if nbytes:
                    download_bands[key]["size_bytes"] = nbytes
        # Persist probed sizes on the layer for later downloads
        if any(sizes.values()):
            layer["download_bands"] = download_bands
            self.save_layer(scene_id, layer)

        order = {k: i for i, k in enumerate(self.DOWNLOAD_BAND_ORDER)}
        available: list[dict[str, Any]] = []
        for key, meta in download_bands.items():
            nbytes = sizes.get(key) or meta.get("size_bytes")
            size_mb = round(float(nbytes) / (1024 * 1024), 1) if nbytes else None
            available.append(
                {
                    "id": key,
                    "label": meta.get("title") or key,
                    "code": meta.get("code") or key,
                    "filename": meta.get("filename") or f"{key}.tif",
                    "extension": meta.get("extension") or ".tif",
                    "format": meta.get("format") or "GeoTIFF",
                    "media_type": meta.get("media_type") or "image/tiff",
                    "group": "sar" if key in {"vv", "vh"} else "optical",
                    "size_bytes": nbytes,
                    "size_label": f"{size_mb} MB" if size_mb is not None else "full COG",
                    "full_resolution": True,
                }
            )
        available.sort(key=lambda b: order.get(b["id"], 999))

        # Default to a single full band — each file is tens of MB
        defaults = [b["id"] for b in available if b["id"] in {"red", "vv"}][:1]
        if not defaults and available:
            defaults = [available[0]["id"]]

        return {
            "scene_id": scene_id,
            "collection": layer.get("collection"),
            "stac_id": layer.get("stac_id"),
            "bounds": layer.get("bounds"),
            "bands": available,
            "default_bands": defaults,
            "formats": ["GeoTIFF", "ZIP"],
            "download_mode": "full_product_cog",
            "note": "Downloads are original full-resolution product band COGs (typically ~40–120 MB each), not preview windows.",
        }

    def _signed_asset_href(self, href: str, sign: str | None) -> str:
        """Return a fetchable HTTPS URL, signing Planetary Computer assets when needed."""
        url = self._s3_to_https(href)
        if sign == "planetary_computer":
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                url = self._sign_pc(url, client)
        return url

    def _probe_asset_size(self, href: str, sign: str | None) -> int | None:
        """Best-effort Content-Length for a full product band COG."""
        try:
            url = self._signed_asset_href(href, sign)
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.head(url)
                if resp.status_code >= 400:
                    # Some CDNs require GET for length; fall back lightly
                    with client.stream("GET", url) as streamed:
                        cl = streamed.headers.get("content-length")
                        streamed.close()
                        return int(cl) if cl else None
                cl = resp.headers.get("content-length")
                return int(cl) if cl else None
        except Exception:  # noqa: BLE001
            return None

    def _fetch_original_band_file(
        self,
        href: str,
        *,
        sign: str | None,
        dest: Path,
    ) -> int:
        """Download the original full-resolution band COG to disk. Returns bytes written."""
        url = self._signed_asset_href(href, sign)
        written = 0
        with httpx.Client(timeout=httpx.Timeout(30.0, read=900.0), follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise ExternalServiceError(
                        f"Failed to download band file ({resp.status_code})"
                    )
                with dest.open("wb") as out:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        if not chunk:
                            continue
                        out.write(chunk)
                        written += len(chunk)
        if written < 50_000:
            # Reject empty/error bodies; real 60 m COGs can be ~1 MB, 10 m ~40–100 MB
            raise ExternalServiceError(
                f"Band download too small ({written} bytes); expected a full product COG"
            )
        return written

    def _resolve_band_selection(
        self,
        layer: dict[str, Any],
        band_ids: list[str],
    ) -> list[str]:
        analysis = layer.get("analysis_bands") or {}
        download_bands = self._resolve_download_bands(layer)
        alias_map = {
            "swir": "swir16",
            "swir2": "swir22",
            "nir": "nir08" if "nir08" in download_bands and "nir" not in download_bands else "nir",
            "thermal": "lwir11",
        }
        resolved: list[str] = []
        for bid in band_ids:
            key = bid if bid in download_bands else alias_map.get(bid, bid)
            if key not in download_bands and key not in analysis:
                raise ValidationError(f"Band '{bid}' is not available for this scene")
            if key not in download_bands:
                download_bands[key] = self._stac_band_meta(
                    key,
                    {"href": analysis[key], "title": key},
                    fallback_filename=f"{key}.tif",
                )
                layer.setdefault("download_bands", {})[key] = download_bands[key]
            resolved.append(key)
        seen: set[str] = set()
        unique: list[str] = []
        for b in resolved:
            if b not in seen:
                seen.add(b)
                unique.append(b)
        return unique

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
    ) -> tuple[Path, str, str, bool]:
        """
        Fetch original full-resolution product band COGs (typically ~40–120 MB each).

        Returns (path, filename, media_type, cleanup) where cleanup=True means the
        caller should delete the temp path after the response is sent.
        """
        import tempfile
        import zipfile

        # `size` is ignored for full product downloads (kept for API compatibility)
        _ = size

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

        analysis = layer.get("analysis_bands") or {}
        download_bands = self._resolve_download_bands(layer)
        sign = layer.get("sign")
        unique = self._resolve_band_selection(layer, band_ids)

        tmp_dir = Path(tempfile.mkdtemp(prefix="ev_bands_"))
        try:
            saved: list[tuple[str, Path, int]] = []
            for name in unique:
                meta = download_bands[name]
                href = analysis.get(name) or meta["href"]
                filename = meta.get("filename") or f"{name}.tif"
                # Keep original extension from product (.tif / .tiff / .TIF)
                dest = tmp_dir / filename
                nbytes = self._fetch_original_band_file(href, sign=sign, dest=dest)
                logger.info("Fetched full band {} ({} bytes) for {}", filename, nbytes, scene_id)
                saved.append((filename, dest, nbytes))

            if len(saved) == 1:
                import os

                filename, dest, _nbytes = saved[0]
                media = "image/tiff"
                # Move single file out so we can remove the temp dir container later
                fd, single_str = tempfile.mkstemp(
                    prefix="ev_band_", suffix=Path(filename).suffix or ".tif"
                )
                os.close(fd)
                single = Path(single_str)
                dest.replace(single)
                return single, filename, media, True

            import os

            stac = (layer.get("stac_id") or scene_id)[:60].replace("/", "_")
            zip_name = f"{stac}_bands.zip"
            fd, zip_str = tempfile.mkstemp(prefix="ev_bands_", suffix=".zip")
            os.close(fd)
            zip_path = Path(zip_str)
            # STORE only — COGs are already compressed; avoids huge CPU/RAM re-encode
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
                used: set[str] = set()
                for filename, dest, _nbytes in saved:
                    out_name = filename
                    if out_name in used:
                        stem = Path(filename).stem
                        suffix = Path(filename).suffix or ".tif"
                        out_name = f"{stem}_{len(used)}{suffix}"
                    used.add(out_name)
                    zf.write(dest, arcname=out_name)
            return zip_path, zip_name, "application/zip", True
        finally:
            # Always drop per-band temp copies; final artifact is outside tmp_dir
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
