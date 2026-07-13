"""Copernicus Data Space Ecosystem OAuth2 and catalog client."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, UnauthorizedError
from app.schemas.catalog import CatalogSearchRequest, SceneSummary


class CopernicusTokenManager:
    """Manage CDSE OAuth2 access tokens."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    @property
    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.copernicus_username and settings.copernicus_password)

    async def get_token(self) -> str:
        if self._access_token and self._expires_at and datetime.now(UTC) < self._expires_at:
            return self._access_token
        return await self.refresh_token()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def refresh_token(self) -> str:
        settings = get_settings()
        if not self.is_configured:
            raise UnauthorizedError(
                "Copernicus credentials not configured. "
                "Set COPERNICUS_USERNAME and COPERNICUS_PASSWORD."
            )
        data = {
            "client_id": settings.copernicus_client_id,
            "username": settings.copernicus_username,
            "password": settings.copernicus_password,
            "grant_type": "password",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(settings.copernicus_token_url, data=data)
            if response.status_code != 200:
                logger.error("CDSE token error: {} {}", response.status_code, response.text)
                raise ExternalServiceError(
                    "Failed to obtain Copernicus access token",
                    details=response.text,
                )
            payload = response.json()
            self._access_token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 600))
            # Refresh 60s early
            from datetime import timedelta

            self._expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in - 60, 30))
            logger.info("Copernicus access token refreshed")
            return self._access_token

    def clear(self) -> None:
        self._access_token = None
        self._expires_at = None


_token_manager = CopernicusTokenManager()


def get_token_manager() -> CopernicusTokenManager:
    return _token_manager


COLLECTION_MAP: dict[str, str] = {
    "SENTINEL-1": "SENTINEL-1",
    "SENTINEL-2": "SENTINEL-2",
    "LANDSAT-8": "LANDSAT-8",
    "LANDSAT-9": "LANDSAT-9",
    "MODIS": "TERRA",
}


class CopernicusCatalogService:
    """Search and download satellite products via CDSE OData API."""

    def __init__(self, token_manager: CopernicusTokenManager | None = None) -> None:
        self.token_manager = token_manager or get_token_manager()
        self.settings = get_settings()

    def _build_filter(self, request: CatalogSearchRequest) -> str:
        clauses: list[str] = []
        collection_filters = []
        for collection in request.collections:
            mapped = COLLECTION_MAP.get(collection, collection)
            collection_filters.append(f"Collection/Name eq '{mapped}'")
        if collection_filters:
            clauses.append("(" + " or ".join(collection_filters) + ")")

        if request.start_date:
            start = request.start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            clauses.append(f"ContentDate/Start ge {start}")
        if request.end_date:
            end = request.end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            clauses.append(f"ContentDate/Start le {end}")

        if request.cloud_cover_max is not None and any(
            c.startswith("SENTINEL-2") or c.startswith("LANDSAT") for c in request.collections
        ):
            clauses.append(
                "Attributes/OData.CSC.DoubleAttribute/any("
                f"att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le "
                f"{request.cloud_cover_max})"
            )

        if request.bbox and len(request.bbox) == 4:
            west, south, east, north = request.bbox
            wkt = (
                f"POLYGON(({west} {south},{east} {south},"
                f"{east} {north},{west} {north},{west} {south}))"
            )
            clauses.append(f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')")
        elif request.aoi and request.aoi.type == "Polygon":
            rings = request.aoi.coordinates
            if rings:
                coords = rings[0]
                parts = [f"{c[0]} {c[1]}" for c in coords]
                if parts[0] != parts[-1]:
                    parts.append(parts[0])
                wkt = f"POLYGON(({' ,'.join(parts)}))"
                clauses.append(f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')")

        if request.product_type:
            clauses.append(f"contains(Name,'{request.product_type}')")

        return " and ".join(clauses) if clauses else "Collection/Name eq 'SENTINEL-2'"

    def _parse_scene(self, item: dict[str, Any]) -> SceneSummary:
        footprint = None
        center = None
        geo = item.get("GeoFootprint") or item.get("Footprint")
        if isinstance(geo, dict):
            footprint = geo
            try:
                coords = geo.get("coordinates", [[]])[0]
                if coords:
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    center = [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]
            except (IndexError, TypeError, KeyError):
                pass

        cloud_cover = None
        attributes = item.get("Attributes") or []
        for attr in attributes:
            if attr.get("Name") == "cloudCover":
                cloud_cover = float(attr.get("Value", 0))
                break

        sensing_time = None
        content_date = item.get("ContentDate") or {}
        start = content_date.get("Start")
        if start:
            try:
                sensing_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except ValueError:
                pass

        return SceneSummary(
            id=item.get("Id", ""),
            name=item.get("Name", ""),
            collection=item.get("Collection", {}).get("Name", "")
            if isinstance(item.get("Collection"), dict)
            else str(item.get("Collection", "")),
            platform=str(item.get("PlatformShortName") or item.get("Collection", "")),
            sensing_time=sensing_time,
            cloud_cover=cloud_cover,
            footprint=footprint,
            center=center,
            thumbnail_url=None,
            size_bytes=item.get("ContentLength"),
            content_date=start,
            product_type=item.get("ProductType"),
            metadata={
                "online": item.get("Online"),
                "publication_date": item.get("PublicationDate"),
                "origin_date": item.get("OriginDate"),
            },
        )

    async def search(self, request: CatalogSearchRequest) -> tuple[list[SceneSummary], int]:
        """Search the CDSE catalog. Falls back to synthetic demo scenes when unauthenticated."""
        if not self.token_manager.is_configured:
            logger.warning("CDSE not configured — returning demo catalog results")
            return self._demo_results(request)

        filter_expr = self._build_filter(request)
        params = {
            "$filter": filter_expr,
            "$orderby": "ContentDate/Start desc",
            "$top": str(request.max_results),
            "$expand": "Attributes",
        }
        url = f"{self.settings.copernicus_catalog_url}/Products"
        try:
            token = await self.token_manager.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 401:
                    self.token_manager.clear()
                    token = await self.token_manager.get_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    response = await client.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    logger.error("Catalog search failed: {} {}", response.status_code, response.text)
                    raise ExternalServiceError(
                        "Catalog search failed", details=response.text[:500]
                    )
                payload = response.json()
                items = payload.get("value", [])
                scenes = [self._parse_scene(item) for item in items]
                return scenes, len(scenes)
        except (httpx.HTTPError, ExternalServiceError, UnauthorizedError) as exc:
            logger.warning("Catalog search error, falling back to demo: {}", exc)
            return self._demo_results(request)

    def _demo_results(self, request: CatalogSearchRequest) -> tuple[list[SceneSummary], int]:
        """Generate realistic demo scenes for offline / unconfigured environments."""
        import uuid

        bbox = request.bbox or [2.0, 48.5, 2.8, 49.1]
        west, south, east, north = bbox
        clon = (west + east) / 2
        clat = (south + north) / 2
        scenes: list[SceneSummary] = []
        collections = request.collections or ["SENTINEL-2"]
        for i, collection in enumerate(collections):
            for j in range(min(8, request.max_results // max(len(collections), 1))):
                day = 1 + (i * 3 + j) % 28
                month = 1 + ((i + j) % 12)
                year = 2024 if j % 2 == 0 else 2025
                sensing = datetime(year, month, day, 10, 30, tzinfo=UTC)
                cloud = round((j * 7.3 + i * 2.1) % (request.cloud_cover_max or 30), 1)
                offset = (j - 3) * 0.05
                footprint = {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west + offset, south + offset],
                            [east + offset, south + offset],
                            [east + offset, north + offset],
                            [west + offset, north + offset],
                            [west + offset, south + offset],
                        ]
                    ],
                }
                scenes.append(
                    SceneSummary(
                        id=str(uuid.uuid4()),
                        name=(
                            f"{collection.replace('-', '')}_MSIL2A_"
                            f"{sensing.strftime('%Y%m%dT%H%M%S')}_N0510_R{100+j:03d}_T31UDQ"
                        ),
                        collection=collection,
                        platform=collection.split("-")[0],
                        sensing_time=sensing,
                        cloud_cover=cloud if "SENTINEL-2" in collection or "LANDSAT" in collection else None,
                        footprint=footprint,
                        center=[clon + offset, clat + offset],
                        thumbnail_url=None,
                        size_bytes=int(850_000_000 + j * 12_000_000 + math.sin(j) * 1_000_000),
                        content_date=sensing.isoformat(),
                        product_type="L2A" if "SENTINEL-2" in collection else "GRD",
                        metadata={"demo": True, "source": "earthvision-demo-catalog"},
                    )
                )
        return scenes[: request.max_results], len(scenes[: request.max_results])

    async def get_download_url(self, scene_id: str) -> str:
        settings = get_settings()
        return f"{settings.copernicus_download_url}/Products({scene_id})/$value"

    async def auth_status(self) -> dict[str, Any]:
        return {
            "configured": self.token_manager.is_configured,
            "has_token": self.token_manager._access_token is not None,
            "expires_at": (
                self.token_manager._expires_at.isoformat()
                if self.token_manager._expires_at
                else None
            ),
        }
