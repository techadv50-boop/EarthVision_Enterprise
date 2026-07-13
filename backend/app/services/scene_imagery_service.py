"""Resolve real Sentinel-2 true-color (TCI) COGs and serve sharp XYZ tiles."""

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

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"

GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
}


class SceneImageryService:
    """Map catalog scenes to Sentinel-2 L2A visual (TCI) COGs and XYZ tiles."""

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

    def get_layer(self, scene_id: str) -> dict[str, Any] | None:
        path = self._registry_path(scene_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_bytes())
        except Exception:  # noqa: BLE001
            return None

    def save_layer(self, scene_id: str, layer: dict[str, Any]) -> dict[str, Any]:
        path = self._registry_path(scene_id)
        path.write_text(json.dumps(layer), encoding="utf-8")
        return layer

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
        if bbox and len(bbox) == 4:
            return [float(x) for x in bbox]
        from_fp = self._bbox_from_footprint(footprint)
        if from_fp:
            return from_fp
        return [74.15, 31.35, 74.55, 31.7]

    def _parse_sensing_time(self, sensing_time: str | None) -> datetime | None:
        if not sensing_time:
            return None
        try:
            return datetime.fromisoformat(sensing_time.replace("Z", "+00:00"))
        except ValueError:
            return None

    def find_sentinel2_visual(
        self,
        bbox: list[float],
        sensing_time: str | None = None,
        cloud_cover_max: float | None = 40.0,
    ) -> dict[str, Any]:
        """Find a Sentinel-2 L2A visual (true-color TCI) COG covering the AOI."""
        west, south, east, north = bbox
        dt = self._parse_sensing_time(sensing_time)
        # Prefer imagery near the scene date; expand if needed (demo dates may be future)
        windows: list[tuple[str, str]] = []
        if dt:
            for days in (7, 30, 90, 365):
                start = (dt - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
                end = (dt + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59Z")
                windows.append((start, end))
        # Always include a recent global window as final fallback
        now = datetime.now(UTC)
        windows.append(
            (
                (now - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z"),
                now.strftime("%Y-%m-%dT23:59:59Z"),
            )
        )

        cloud_q = min(float(cloud_cover_max if cloud_cover_max is not None else 40.0), 80.0)
        last_error: str | None = None

        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            for start, end in windows:
                body = {
                    "collections": ["sentinel-2-l2a"],
                    "bbox": [west, south, east, north],
                    "datetime": f"{start}/{end}",
                    "limit": 12,
                    "query": {"eo:cloud_cover": {"lt": cloud_q}},
                    "sortby": [{"field": "properties.datetime", "direction": "desc"}],
                }
                try:
                    resp = client.post(EARTH_SEARCH_URL, json=body)
                    if resp.status_code != 200:
                        last_error = f"STAC {resp.status_code}: {resp.text[:200]}"
                        continue
                    features = resp.json().get("features") or []
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    logger.warning("Earth Search failed: {}", exc)
                    continue

                def _coverage(feat: dict[str, Any]) -> float:
                    ib = feat.get("bbox") or []
                    if len(ib) != 4:
                        return 0.0
                    ix0 = max(west, float(ib[0]))
                    iy0 = max(south, float(ib[1]))
                    ix1 = min(east, float(ib[2]))
                    iy1 = min(north, float(ib[3]))
                    if ix1 <= ix0 or iy1 <= iy0:
                        return 0.0
                    inter = (ix1 - ix0) * (iy1 - iy0)
                    area = max((east - west) * (north - south), 1e-12)
                    return inter / area

                # Prefer max AOI coverage, then lowest cloud cover
                features = sorted(
                    features,
                    key=lambda f: (
                        -_coverage(f),
                        float(f.get("properties", {}).get("eo:cloud_cover") or 99),
                    ),
                )
                for feat in features:
                    if _coverage(feat) < 0.15:
                        continue
                    assets = feat.get("assets") or {}
                    visual = assets.get("visual") or assets.get("overview")
                    if not visual or not visual.get("href"):
                        continue
                    item_bbox = feat.get("bbox") or bbox
                    props = feat.get("properties") or {}
                    return {
                        "stac_id": feat.get("id"),
                        "cog_url": visual["href"],
                        "bbox": [float(x) for x in item_bbox],
                        "datetime": props.get("datetime"),
                        "cloud_cover": props.get("eo:cloud_cover"),
                        "platform": props.get("platform") or "sentinel-2",
                        "collection": "sentinel-2-l2a",
                        "thumbnail_url": (assets.get("thumbnail") or {}).get("href"),
                        "coverage": _coverage(feat),
                    }

        raise NotFoundError(
            "No Sentinel-2 true-color (TCI) imagery found for this area/date. "
            f"Last error: {last_error or 'empty result'}"
        )

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
        """Resolve + register a scene imagery layer; return tile metadata for the map."""
        existing = self.get_layer(scene_id)
        if existing and existing.get("cog_url"):
            return existing

        bounds = self.resolve_bounds(bbox, footprint)
        # For non-optical collections, still show S2 optical context over the AOI
        cloud_max = 40.0
        if cloud_cover is not None:
            cloud_max = max(float(cloud_cover) + 15.0, 25.0)

        match = self.find_sentinel2_visual(
            bounds,
            sensing_time=sensing_time,
            cloud_cover_max=cloud_max,
        )
        # Keep the requested AOI as display bounds so the map centers on the place
        display = bounds

        layer = {
            "scene_id": scene_id,
            "collection": collection or "SENTINEL-2",
            "source": "sentinel2_tci",
            "composite": "true_color_RGB",
            "bands": {"R": "B04 Red", "G": "B03 Green", "B": "B02 Blue"},
            "cog_url": match["cog_url"],
            "stac_id": match["stac_id"],
            "bounds": display,
            "scene_bbox": match["bbox"],
            "acquisition_date": match.get("datetime"),
            "cloud_cover": match.get("cloud_cover"),
            "coverage": match.get("coverage"),
            "thumbnail_url": match.get("thumbnail_url"),
            "tile_url_template": f"/api/v1/catalog/scenes/{scene_id}/tiles/{{z}}/{{x}}/{{y}}.png",
        }
        return self.save_layer(scene_id, layer)

    def _mercator_bounds(self, z: int, x: int, y: int) -> tuple[float, float, float, float]:
        n = 2.0**z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return lon_min, lat_min, lon_max, lat_max

    def _empty_tile(self) -> bytes:
        img = Image.new("RGBA", (self.TILE_SIZE, self.TILE_SIZE), (0, 0, 0, 0))
        import io

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
        if not layer or not layer.get("cog_url"):
            raise NotFoundError("Scene imagery layer not prepared — open the eye overlay first")

        cache_path = self.tile_cache / scene_id / str(z) / str(x) / f"{y}.png"
        # sanitize path segments
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", scene_id)[:180]
            cache_path = self.tile_cache / safe / str(z) / str(x) / f"{y}.png"
            cache_path.parent.mkdir(parents=True, exist_ok=True)

        if cache_path.exists():
            return cache_path.read_bytes()

        # Skip tiles fully outside display bounds
        lon_min, lat_min, lon_max, lat_max = self._mercator_bounds(z, x, y)
        west, south, east, north = layer["bounds"]
        if lon_max < west or lon_min > east or lat_max < south or lat_min > north:
            data = self._empty_tile()
            cache_path.write_bytes(data)
            return data

        try:
            import rasterio
            from rasterio.enums import Resampling
            from rasterio.warp import transform_bounds
            from rasterio.windows import from_bounds
        except ImportError as exc:
            raise ValidationError("rasterio is required for scene tiles") from exc

        cog_url = layer["cog_url"]
        try:
            with rasterio.Env(**GDAL_ENV):
                with rasterio.open(cog_url) as src:
                    left, bottom, right, top = transform_bounds(
                        "EPSG:4326", src.crs, lon_min, lat_min, lon_max, lat_max
                    )
                    window = from_bounds(left, bottom, right, top, transform=src.transform)
                    count = min(3, src.count)
                    # Nearest when oversampling (zoomed past ~10 m) keeps edges crisp;
                    # bilinear when many source pixels → one tile pixel.
                    oversampling = float(window.width) < self.TILE_SIZE or float(window.height) < self.TILE_SIZE
                    resampling = Resampling.nearest if oversampling else Resampling.bilinear
                    data = src.read(
                        indexes=list(range(1, count + 1)),
                        out_shape=(count, self.TILE_SIZE, self.TILE_SIZE),
                        window=window,
                        resampling=resampling,
                        boundless=True,
                        fill_value=0,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scene tile read failed {}/{}/{}/{}: {}", scene_id, z, x, y, exc)
            return self._empty_tile()

        if data.shape[0] == 1:
            rgb = np.stack([data[0], data[0], data[0]], axis=0)
        else:
            rgb = data[:3]

        # TCI is already uint8 true-color. Apply a joint contrast stretch only
        # (shared across R/G/B) so colors stay natural but features pop.
        rgb_f = rgb.astype(np.float32)
        mask = np.any(rgb > 0, axis=0)
        valid = rgb_f[:, mask]
        if valid.size:
            lo = float(np.percentile(valid, 1))
            hi = float(np.percentile(valid, 99))
            if hi > lo:
                rgb_f = np.clip((rgb_f - lo) / (hi - lo), 0, 1) * 255.0
        rgb_u8 = rgb_f.astype(np.uint8)
        alpha = np.where(mask, 255, 0).astype(np.uint8)
        rgba = np.dstack([rgb_u8[0], rgb_u8[1], rgb_u8[2], alpha])
        img = Image.fromarray(rgba, mode="RGBA")
        import io

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
        cache_path.write_bytes(png)
        return png
