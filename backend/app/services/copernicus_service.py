"""Copernicus Data Space Ecosystem integration service."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.copernicus import CopernicusToken
from app.schemas.imagery import SceneMetadata, SceneSearchRequest, SceneSearchResponse

CDSE_ZIPPER_URL = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({id})/$value"

# Default SF Bay Area footprint when no AOI is provided
SF_BAY_BOUNDS = (-122.5, 37.5, -122.0, 38.0)


class CopernicusService:
    COLLECTIONS = {
        "SENTINEL-1": "SENTINEL-1",
        "SENTINEL-2": "SENTINEL-2",
        "LANDSAT": "LANDSAT-8-9",
        "MODIS": "MODIS",
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.copernicus_client_id,
            "response_type": "code",
            "redirect_uri": self.settings.copernicus_redirect_uri,
            "scope": "openid",
            "state": state,
        }
        return f"{self.settings.copernicus_auth_url}?{urlencode(params)}"

    async def persist_oauth_state(self, user_id: int, state: str, ttl_minutes: int = 15) -> str:
        """Store OAuth CSRF state on the user's CopernicusToken row (creates stub if needed)."""
        result = await self.db.execute(
            select(CopernicusToken).where(CopernicusToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()
        expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

        if token:
            token.oauth_state = state
            token.oauth_state_expires_at = expires
        else:
            token = CopernicusToken(
                user_id=user_id,
                access_token="",
                expires_at=datetime.now(timezone.utc),
                oauth_state=state,
                oauth_state_expires_at=expires,
            )
            self.db.add(token)

        await self.db.flush()
        return state

    async def validate_and_clear_oauth_state(self, user_id: int, state: str | None) -> None:
        """Raise ValueError if state is missing/invalid/expired; clear on success."""
        if not state:
            raise ValueError("Missing OAuth state parameter")

        result = await self.db.execute(
            select(CopernicusToken).where(CopernicusToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()
        if token is None or not token.oauth_state:
            raise ValueError("No pending OAuth state for this user")
        if token.oauth_state != state:
            raise ValueError("Invalid OAuth state")
        if not token.is_oauth_state_valid:
            raise ValueError("OAuth state expired")

        token.oauth_state = None
        token.oauth_state_expires_at = None
        await self.db.flush()

    async def exchange_code(self, user_id: int, code: str, state: str | None = None) -> CopernicusToken:
        await self.validate_and_clear_oauth_state(user_id, state)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.copernicus_redirect_uri,
            "client_id": self.settings.copernicus_client_id,
            "client_secret": self.settings.copernicus_client_secret,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.settings.copernicus_token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 3600))

        result = await self.db.execute(
            select(CopernicusToken).where(CopernicusToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()

        if token:
            token.access_token = token_data["access_token"]
            token.refresh_token = token_data.get("refresh_token")
            token.expires_at = expires_at
        else:
            token = CopernicusToken(
                user_id=user_id,
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_at=expires_at,
            )
            self.db.add(token)

        await self.db.flush()
        return token

    async def get_token(self, user_id: int) -> CopernicusToken | None:
        result = await self.db.execute(
            select(CopernicusToken).where(CopernicusToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()
        if token is None or not token.access_token:
            return None
        if token.is_expired and token.refresh_token:
            token = await self._refresh_token(token)
        return token

    async def _refresh_token(self, token: CopernicusToken) -> CopernicusToken:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": self.settings.copernicus_client_id,
            "client_secret": self.settings.copernicus_client_secret,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.settings.copernicus_token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

        token.access_token = token_data["access_token"]
        if "refresh_token" in token_data:
            token.refresh_token = token_data["refresh_token"]
        token.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )
        await self.db.flush()
        return token

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def wkt_to_geojson(wkt: str) -> Optional[dict[str, Any]]:
        """Convert a WKT polygon/multipolygon string into a GeoJSON geometry dict."""
        try:
            from shapely import wkt as shapely_wkt

            geom = shapely_wkt.loads(wkt)
            return json.loads(json.dumps(geom.__geo_interface__))
        except Exception as exc:
            logger.warning(f"Failed to parse WKT footprint: {exc}")
            return None

    @staticmethod
    def extract_footprint_geojson(product: dict[str, Any]) -> Optional[str]:
        """Parse footprint from CDSE OData product GeoJson / Footprint fields."""
        geojson_field = product.get("GeoJson") or product.get("GeoJSON")
        if geojson_field:
            if isinstance(geojson_field, str):
                try:
                    parsed = json.loads(geojson_field)
                    return json.dumps(parsed)
                except json.JSONDecodeError:
                    # May be WKT embedded in GeoJson field
                    geom = CopernicusService.wkt_to_geojson(geojson_field)
                    if geom:
                        return json.dumps(geom)
            elif isinstance(geojson_field, dict):
                return json.dumps(geojson_field)

        footprint = product.get("Footprint")
        if footprint and isinstance(footprint, str):
            # CDSE often returns geography'POLYGON((...))' or plain WKT
            cleaned = footprint
            if "POLYGON" in cleaned.upper() or "MULTIPOLYGON" in cleaned.upper():
                # Strip geography'...' wrapper if present
                if cleaned.lower().startswith("geography"):
                    start = cleaned.find("'")
                    end = cleaned.rfind("'")
                    if start != -1 and end > start:
                        cleaned = cleaned[start + 1 : end]
                geom = CopernicusService.wkt_to_geojson(cleaned)
                if geom:
                    return json.dumps(geom)
            else:
                try:
                    parsed = json.loads(footprint)
                    return json.dumps(parsed)
                except json.JSONDecodeError:
                    pass

        # Nested geometry under Assets / Locations
        for key in ("Geometry", "geometry", "footprint"):
            val = product.get(key)
            if isinstance(val, dict):
                return json.dumps(val)
            if isinstance(val, str):
                geom = CopernicusService.wkt_to_geojson(val)
                if geom:
                    return json.dumps(geom)

        return None

    @staticmethod
    def _load_aoi_geometry(aoi_geojson: Optional[str]):
        if not aoi_geojson:
            return None
        try:
            from shapely.geometry import shape

            data = json.loads(aoi_geojson)
            if data.get("type") == "Feature":
                return shape(data["geometry"])
            if data.get("type") == "FeatureCollection":
                from shapely.geometry import GeometryCollection

                geoms = [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]
                if not geoms:
                    return None
                if len(geoms) == 1:
                    return geoms[0]
                return GeometryCollection(geoms)
            return shape(data)
        except Exception as exc:
            logger.warning(f"Invalid AOI GeoJSON: {exc}")
            return None

    @staticmethod
    def _footprint_intersects_aoi(footprint_geojson: Optional[str], aoi_geom) -> bool:
        if aoi_geom is None:
            return True
        if not footprint_geojson:
            return False
        try:
            from shapely.geometry import shape

            fp = shape(json.loads(footprint_geojson))
            return bool(fp.intersects(aoi_geom))
        except Exception:
            return False

    @staticmethod
    def _aoi_centroid_and_half_extent(aoi_geojson: Optional[str]) -> tuple[float, float, float, float]:
        """Return (lon, lat, half_width_deg, half_height_deg) for mock footprints."""
        aoi = CopernicusService._load_aoi_geometry(aoi_geojson)
        if aoi is None or aoi.is_empty:
            west, south, east, north = SF_BAY_BOUNDS
            return ((west + east) / 2, (south + north) / 2, (east - west) / 2, (north - south) / 2)

        minx, miny, maxx, maxy = aoi.bounds
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2
        half_w = max((maxx - minx) / 2, 0.05)
        half_h = max((maxy - miny) / 2, 0.05)
        return cx, cy, half_w, half_h

    @staticmethod
    def _make_footprint_around(cx: float, cy: float, half_w: float, half_h: float, jitter: float = 0.0) -> str:
        jx = random.uniform(-jitter, jitter) if jitter else 0.0
        jy = random.uniform(-jitter, jitter) if jitter else 0.0
        west = cx - half_w + jx
        east = cx + half_w + jx
        south = cy - half_h + jy
        north = cy + half_h + jy
        geom = {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        }
        return json.dumps(geom)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_scenes(
        self, user_id: int, request: SceneSearchRequest
    ) -> SceneSearchResponse:
        token = await self.get_token(user_id)
        if token is None:
            return self._mock_search(request)

        collection = self.COLLECTIONS.get(request.collection.upper(), request.collection)
        filters = [
            f"Collection/Name eq '{collection}'",
            f"ContentDate/Start ge {request.start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')}",
            f"ContentDate/Start le {request.end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')}",
        ]

        if request.cloud_cover_max is not None and request.collection.upper() in ("SENTINEL-2", "LANDSAT"):
            filters.append(
                f"Attributes/OData.CSC.DoubleAttribute/any("
                f"a:a/Name eq 'cloudCover' and a/OData.CSC.DoubleAttribute/Value le {request.cloud_cover_max})"
            )

        # Spatial filter via OData Intersects when AOI provided
        aoi_geom = self._load_aoi_geometry(request.aoi_geojson)
        if aoi_geom is not None and not aoi_geom.is_empty:
            minx, miny, maxx, maxy = aoi_geom.bounds
            filters.append(
                f"OData.CSC.Intersects(area=geography'SRID=4326;POLYGON(("
                f"{minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))')"
            )

        filter_str = " and ".join(filters)
        params = {
            "$filter": filter_str,
            "$top": request.limit,
            "$skip": request.offset,
            "$orderby": "ContentDate/Start desc",
            "$expand": "Attributes",
        }

        headers = {"Authorization": f"Bearer {token.access_token}"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.settings.copernicus_api_url}/Products",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error(f"Copernicus search failed: {exc}")
            return self._mock_search(request)

        scenes: list[SceneMetadata] = []
        for product in data.get("value", []):
            cloud_cover = None
            for attr in product.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = attr.get("Value")

            footprint = self.extract_footprint_geojson(product)
            if aoi_geom is not None and not self._footprint_intersects_aoi(footprint, aoi_geom):
                continue

            product_id = product.get("Id")
            scenes.append(
                SceneMetadata(
                    scene_id=product.get("Name", product_id or ""),
                    collection=request.collection,
                    platform=product.get("PlatformShortName", collection),
                    acquisition_date=datetime.fromisoformat(
                        product["ContentDate"]["Start"].replace("Z", "+00:00")
                    ),
                    cloud_cover=cloud_cover,
                    footprint_geojson=footprint,
                    preview_url=product.get("Quicklook"),
                    download_url=(
                        CDSE_ZIPPER_URL.format(id=product_id) if product_id else None
                    ),
                    metadata={
                        "id": product_id,
                        "size": product.get("ContentLength"),
                        "name": product.get("Name"),
                    },
                )
            )

        return SceneSearchResponse(
            total=len(scenes),
            scenes=scenes,
            offset=request.offset,
            limit=request.limit,
        )

    def _mock_search(self, request: SceneSearchRequest) -> SceneSearchResponse:
        """Return realistic mock data when Copernicus credentials are not configured."""
        cx, cy, half_w, half_h = self._aoi_centroid_and_half_extent(request.aoi_geojson)
        aoi_geom = self._load_aoi_geometry(request.aoi_geojson)

        scenes: list[SceneMetadata] = []
        current = request.start_date
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        end = request.end_date
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        idx = 0
        while current <= end and idx < request.limit:
            cloud = random.uniform(0, request.cloud_cover_max or 100)
            footprint = self._make_footprint_around(
                cx, cy, half_w * 1.1, half_h * 1.1, jitter=half_w * 0.15
            )
            if aoi_geom is not None and not self._footprint_intersects_aoi(footprint, aoi_geom):
                # Force intersection by using non-jittered footprint centered on AOI
                footprint = self._make_footprint_around(cx, cy, half_w * 1.05, half_h * 1.05)

            product_id = f"mock-{request.collection}-{current.strftime('%Y%m%d')}-{idx:03d}"
            scenes.append(
                SceneMetadata(
                    scene_id=f"{request.collection}_{current.strftime('%Y%m%d')}_{idx:03d}",
                    collection=request.collection,
                    platform=(
                        request.collection.split("-")[0]
                        if "-" in request.collection
                        else request.collection
                    ),
                    acquisition_date=current,
                    cloud_cover=round(cloud, 2),
                    footprint_geojson=footprint,
                    preview_url=None,
                    download_url=None,
                    metadata={"mock": True, "index": idx, "id": product_id},
                )
            )
            current += timedelta(days=5)
            idx += 1

        return SceneSearchResponse(
            total=len(scenes),
            scenes=scenes,
            offset=request.offset,
            limit=request.limit,
        )

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_product(
        self,
        user_id: int,
        product_id: str,
        destination: Path,
    ) -> Optional[Path]:
        """
        Download a product ZIP from the CDSE zipstream API.

        Returns the path to the downloaded file, or None if credentials/token
        are unavailable or the download fails.
        """
        if not product_id or product_id.startswith("mock-"):
            return None

        token = await self.get_token(user_id)
        if token is None or not token.access_token:
            logger.info("No Copernicus token available; skipping real product download")
            return None

        if not self.settings.copernicus_client_id and not self.settings.copernicus_client_secret:
            # Token alone may still work if previously stored; continue
            pass

        url = CDSE_ZIPPER_URL.format(id=product_id)
        headers = {"Authorization": f"Bearer {token.access_token}"}
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = destination.with_suffix(destination.suffix + ".part")

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                async with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
                    if response.status_code in (401, 403):
                        logger.error(f"CDSE download unauthorized for product {product_id}")
                        return None
                    response.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
            tmp_path.replace(destination)
            logger.info(f"Downloaded CDSE product {product_id} -> {destination}")
            return destination
        except httpx.HTTPError as exc:
            logger.error(f"CDSE product download failed for {product_id}: {exc}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None
        except Exception as exc:
            logger.error(f"Unexpected error downloading product {product_id}: {exc}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None
