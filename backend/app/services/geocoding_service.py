"""Geocoding and location search service."""

import httpx
from loguru import logger

from app.schemas.geo import LocationSearchResult


class GeocodingService:
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    async def search_location(self, query: str, limit: int = 10) -> list[LocationSearchResult]:
        params = {
            "q": query,
            "format": "json",
            "limit": limit,
            "addressdetails": 1,
            "accept-language": "en",
        }
        headers = {"User-Agent": "EarthVision-Enterprise/1.0", "Accept-Language": "en"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.NOMINATIM_URL, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error(f"Geocoding search failed: {exc}")
            return []

        results: list[LocationSearchResult] = []
        for item in data:
            bbox = None
            if "boundingbox" in item:
                bb = item["boundingbox"]
                bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]

            display = item.get("display_name") or ""
            raw_name = item.get("name") or ""
            name = raw_name if raw_name.isascii() and any(c.isalpha() for c in raw_name) else (
                display.split(",")[0].strip() if display else raw_name or query
            )
            results.append(
                LocationSearchResult(
                    name=name,
                    display_name=display,
                    longitude=float(item["lon"]),
                    latitude=float(item["lat"]),
                    bounding_box=bbox,
                    place_type=item.get("type"),
                )
            )
        return results

    async def reverse_geocode(self, longitude: float, latitude: float) -> LocationSearchResult | None:
        params = {
            "lat": latitude,
            "lon": longitude,
            "format": "json",
        }
        headers = {"User-Agent": "EarthVision-Enterprise/1.0"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                item = response.json()
        except httpx.HTTPError as exc:
            logger.error(f"Reverse geocoding failed: {exc}")
            return None

        return LocationSearchResult(
            name=item.get("name", "Unknown"),
            display_name=item.get("display_name", ""),
            longitude=longitude,
            latitude=latitude,
            place_type=item.get("type"),
        )
