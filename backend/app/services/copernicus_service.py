"""Copernicus Data Space Ecosystem OAuth2 and catalog client."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, UnauthorizedError
from app.schemas.catalog import CatalogSearchRequest, SceneSummary

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"

# Map UI collection names → (STAC endpoint, STAC collection ids, optional platform filter)
STAC_COLLECTION_MAP: dict[str, tuple[str, list[str], str | None]] = {
    "SENTINEL-2": (EARTH_SEARCH_URL, ["sentinel-2-l2a"], None),
    "SENTINEL-1": (EARTH_SEARCH_URL, ["sentinel-1-grd"], None),
    "LANDSAT-9": (PC_STAC_URL, ["landsat-c2-l2"], "landsat-9"),
    "LANDSAT-8": (PC_STAC_URL, ["landsat-c2-l2"], "landsat-8"),
    "LANDSAT-7": (PC_STAC_URL, ["landsat-c2-l2"], "landsat-7"),
}


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
    "SENTINEL-3": "SENTINEL-3",
    "SENTINEL-5P": "SENTINEL-5P",
    "LANDSAT-7": "LANDSAT-7",
    "LANDSAT-8": "LANDSAT-8",
    "LANDSAT-9": "LANDSAT-9",
    "MODIS": "TERRAAQUA",
    "TERRAAQUA": "TERRAAQUA",
    "TERRA": "TERRA",
    "AQUA": "AQUA",
    "SMOS": "SMOS",
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

    def _resolve_date_window(
        self, request: CatalogSearchRequest
    ) -> tuple[datetime, datetime]:
        """Return timezone-aware [start, end] from the UI date range."""
        end = request.end_date or datetime.now(UTC)
        start = request.start_date or (end - timedelta(days=90))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        else:
            start = start.astimezone(UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        else:
            end = end.astimezone(UTC)
        if start > end:
            start, end = end, start
        return start, end

    async def search(self, request: CatalogSearchRequest) -> tuple[list[SceneSummary], int]:
        """Search the CDSE catalog. Falls back to STAC (date-aware) then demo scenes."""
        if not self.token_manager.is_configured:
            logger.warning("CDSE not configured — searching public STAC with requested dates")
            stac = await self._stac_results(request)
            if stac[0]:
                return stac
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
            logger.warning("Catalog search error, falling back to STAC/demo: {}", exc)
            stac = await self._stac_results(request)
            if stac[0]:
                return stac
            return self._demo_results(request)

    async def _stac_results(
        self, request: CatalogSearchRequest
    ) -> tuple[list[SceneSummary], int]:
        """Search Element84 / Planetary Computer STAC using the UI date range."""
        start, end = self._resolve_date_window(request)
        bbox = request.bbox
        if not bbox or len(bbox) != 4:
            logger.warning("STAC catalog search skipped — bbox required to apply date range")
            return [], 0

        collections = list(request.collections or ["SENTINEL-2"])
        limit = max(1, min(request.max_results, 20))
        cloud_max = request.cloud_cover_max
        start_s = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_s = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        scenes: list[SceneSummary] = []

        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                for coll in collections:
                    mapping = STAC_COLLECTION_MAP.get(coll)
                    if not mapping:
                        continue
                    url, stac_collections, platform = mapping
                    body: dict[str, Any] = {
                        "collections": stac_collections,
                        "bbox": [float(x) for x in bbox],
                        "datetime": f"{start_s}/{end_s}",
                        "limit": limit,
                        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
                    }
                    query: dict[str, Any] = {}
                    if cloud_max is not None and (
                        coll.startswith("SENTINEL-2") or coll.startswith("LANDSAT")
                    ):
                        query["eo:cloud_cover"] = {"lt": float(cloud_max) + 0.01}
                    if query:
                        body["query"] = query

                    response = await client.post(url, json=body)
                    if response.status_code != 200:
                        logger.warning(
                            "STAC catalog {} → {} {}",
                            coll,
                            response.status_code,
                            response.text[:200],
                        )
                        continue

                    for feat in response.json().get("features") or []:
                        scene = self._parse_stac_feature(feat, coll, platform)
                        if scene is None:
                            continue
                        # Enforce the UI date window strictly
                        if scene.sensing_time is not None:
                            st = scene.sensing_time
                            if st.tzinfo is None:
                                st = st.replace(tzinfo=UTC)
                            else:
                                st = st.astimezone(UTC)
                            if st < start or st > end:
                                continue
                        scenes.append(scene)
                        if len(scenes) >= limit:
                            break
                    if len(scenes) >= limit:
                        break
        except httpx.HTTPError as exc:
            logger.warning("STAC catalog search failed: {}", exc)
            return [], 0

        scenes.sort(
            key=lambda s: s.sensing_time or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        scenes = scenes[:limit]
        if scenes:
            logger.info(
                "STAC catalog returned {} scene(s) for {} → {}",
                len(scenes),
                start_s,
                end_s,
            )
        return scenes, len(scenes)

    def _parse_stac_feature(
        self,
        feat: dict[str, Any],
        ui_collection: str,
        platform_filter: str | None,
    ) -> SceneSummary | None:
        props = feat.get("properties") or {}
        plat = str(props.get("platform") or "").lower().replace("_", "-")
        if platform_filter:
            wanted = platform_filter.lower().replace("_", "-")
            # Accept "landsat-8", "landsat_8", or bare "8"/"9" in platform string
            if wanted not in plat and wanted.split("-")[-1] not in plat:
                return None

        dt_raw = props.get("datetime") or props.get("start_datetime")
        sensing_time = None
        if isinstance(dt_raw, str):
            try:
                sensing_time = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
            except ValueError:
                sensing_time = None

        geom = feat.get("geometry")
        center = None
        if isinstance(geom, dict) and geom.get("type") == "Polygon":
            try:
                ring = geom["coordinates"][0]
                lons = [c[0] for c in ring]
                lats = [c[1] for c in ring]
                center = [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]
            except (IndexError, TypeError, KeyError):
                center = None
        elif feat.get("bbox") and len(feat["bbox"]) == 4:
            bb = feat["bbox"]
            center = [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]

        cloud = props.get("eo:cloud_cover")
        try:
            cloud_cover = float(cloud) if cloud is not None else None
        except (TypeError, ValueError):
            cloud_cover = None

        stac_id = str(feat.get("id") or uuid.uuid4())
        name = str(props.get("s2:product_uri") or props.get("landsat:scene_id") or stac_id)

        return SceneSummary(
            id=stac_id,
            name=name,
            collection=ui_collection,
            platform=str(props.get("platform") or ui_collection.split("-")[0]),
            sensing_time=sensing_time,
            cloud_cover=cloud_cover,
            footprint=geom if isinstance(geom, dict) else None,
            center=center,
            thumbnail_url=(feat.get("assets") or {}).get("thumbnail", {}).get("href"),
            size_bytes=None,
            content_date=dt_raw if isinstance(dt_raw, str) else None,
            product_type=str(props.get("s2:product_type") or props.get("instruments") or "L2"),
            metadata={
                "source": "stac-catalog",
                "stac_id": stac_id,
                "stac_collection": (feat.get("collection") or ""),
            },
        )

    def _demo_results(self, request: CatalogSearchRequest) -> tuple[list[SceneSummary], int]:
        """Generate demo scenes constrained to the requested From/To date range."""
        bbox = request.bbox or [2.0, 48.5, 2.8, 49.1]
        west, south, east, north = bbox
        clon = (west + east) / 2
        clat = (south + north) / 2
        collections = list(request.collections or ["SENTINEL-2"])
        if not collections:
            collections = ["SENTINEL-2"]

        product_types = {
            "SENTINEL-1": "GRD",
            "SENTINEL-2": "L2A",
            "LANDSAT-8": "L2SP",
            "LANDSAT-9": "L2SP",
            "MODIS": "MOD09GA",
        }

        start, end = self._resolve_date_window(request)
        span_seconds = max((end - start).total_seconds(), 86400.0)
        # ~one scene every 5 days inside the window, capped by max_results
        approx_count = max(1, int(span_seconds / (5 * 86400)) + 1)
        limit = max(1, min(request.max_results, 20, approx_count))

        scenes: list[SceneSummary] = []
        for j in range(limit):
            collection = collections[j % len(collections)]
            # Most recent first, evenly spaced inside [start, end]
            frac = j / max(limit - 1, 1)
            sensing = end - timedelta(seconds=span_seconds * frac)
            if sensing < start:
                sensing = start
            cloud_cap = request.cloud_cover_max if request.cloud_cover_max is not None else 80.0
            cloud = round((j * 4.7) % max(cloud_cap, 1.0), 1)
            # Footprints: Landsat/S1 are orbit-tilted parallelograms; S2 closer to rectangular tile
            ox = ((j % 5) - 2) * 0.02
            oy = ((j % 3) - 1) * 0.02
            w = (east - west) * 0.55
            h = (north - south) * 0.55
            cx, cy = clon + ox, clat + oy
            if collection.startswith("LANDSAT") or collection == "SENTINEL-1":
                # ~12–18° orbit skew (WRS / IW swath style)
                skew = 0.18 if collection.startswith("LANDSAT") else 0.28
                footprint = {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [cx - w - skew * h, cy - h],
                            [cx + w - skew * h, cy - h],
                            [cx + w + skew * h, cy + h],
                            [cx - w + skew * h, cy + h],
                            [cx - w - skew * h, cy - h],
                        ]
                    ],
                }
            else:
                footprint = {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west + ox, south + oy],
                            [east + ox, south + oy],
                            [east + ox, north + oy],
                            [west + ox, north + oy],
                            [west + ox, south + oy],
                        ]
                    ],
                }
            tile = f"T{43 + (j % 3)}R{66 + (j % 9):02d}"
            scenes.append(
                SceneSummary(
                    id=str(uuid.uuid4()),
                    name=(
                        f"{collection.replace('-', '')}_{product_types.get(collection, 'L2')}_"
                        f"{sensing.strftime('%Y%m%dT%H%M%S')}_N0510_R{100 + j:03d}_{tile}"
                    ),
                    collection=collection,
                    platform=collection.split("-")[0],
                    sensing_time=sensing,
                    cloud_cover=(
                        cloud
                        if collection.startswith("SENTINEL-2") or collection.startswith("LANDSAT")
                        else None
                    ),
                    footprint=footprint,
                    center=[cx, cy],
                    thumbnail_url=None,
                    size_bytes=int(720_000_000 + j * 18_000_000 + abs(math.sin(j)) * 2_000_000),
                    content_date=sensing.isoformat(),
                    product_type=product_types.get(collection, "L2"),
                    metadata={
                        "demo": True,
                        "source": "earthvision-demo-catalog",
                        "rank": j + 1,
                        "date_from": start.isoformat(),
                        "date_to": end.isoformat(),
                    },
                )
            )
        return scenes, len(scenes)

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
