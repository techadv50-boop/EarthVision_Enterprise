"""GIS geocoding, measurement, and conversion services."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from shapely.geometry import mapping, shape
from shapely.ops import transform
from pyproj import Transformer

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, ValidationError
from app.schemas.gis import (
    GeocodeRequest,
    GeocodeResult,
    MeasurementRequest,
    MeasurementResponse,
)


class GISService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def geocode(self, request: GeocodeRequest) -> list[GeocodeResult]:
        url = f"{self.settings.nominatim_url}/search"
        params = {
            "q": request.query,
            "format": "json",
            "limit": request.limit,
            "addressdetails": 1,
        }
        headers = {"User-Agent": "EarthVisionEnterprise/1.0 (commercial-eo-platform)"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    raise ExternalServiceError("Geocoding service unavailable")
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Geocode failed, using offline fallback: {}", exc)
            return self._offline_geocode(request.query)

        results: list[GeocodeResult] = []
        for item in data:
            bbox = None
            if "boundingbox" in item:
                # Nominatim: [south, north, west, east]
                bb = item["boundingbox"]
                bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
            results.append(
                GeocodeResult(
                    display_name=item.get("display_name", request.query),
                    longitude=float(item["lon"]),
                    latitude=float(item["lat"]),
                    bounding_box=bbox,
                    place_type=item.get("type"),
                    importance=float(item.get("importance", 0)),
                )
            )
        if not results:
            return self._offline_geocode(request.query)
        return results

    def _offline_geocode(self, query: str) -> list[GeocodeResult]:
        """Built-in gazetteer for common locations when Nominatim is unavailable."""
        gazetteer: dict[str, tuple[str, float, float]] = {
            "lahore": ("Lahore, Punjab, Pakistan", 74.3587, 31.5204),
            "karachi": ("Karachi, Sindh, Pakistan", 67.0011, 24.8607),
            "islamabad": ("Islamabad, Pakistan", 73.0479, 33.6844),
            "rawalpindi": ("Rawalpindi, Pakistan", 73.0479, 33.5651),
            "faisalabad": ("Faisalabad, Pakistan", 73.1350, 31.4504),
            "paris": ("Paris, France", 2.3522, 48.8566),
            "london": ("London, United Kingdom", -0.1276, 51.5074),
            "new york": ("New York, USA", -74.006, 40.7128),
            "tokyo": ("Tokyo, Japan", 139.6917, 35.6895),
            "sydney": ("Sydney, Australia", 151.2093, -33.8688),
            "cairo": ("Cairo, Egypt", 31.2357, 30.0444),
            "rio": ("Rio de Janeiro, Brazil", -43.1729, -22.9068),
            "nairobi": ("Nairobi, Kenya", 36.8219, -1.2921),
            "beijing": ("Beijing, China", 116.4074, 39.9042),
            "moscow": ("Moscow, Russia", 37.6173, 55.7558),
            "berlin": ("Berlin, Germany", 13.405, 52.52),
            "dubai": ("Dubai, UAE", 55.2708, 25.2048),
            "singapore": ("Singapore", 103.8198, 1.3521),
            "los angeles": ("Los Angeles, USA", -118.2437, 34.0522),
            "mumbai": ("Mumbai, India", 72.8777, 19.076),
            "cape town": ("Cape Town, South Africa", 18.4241, -33.9249),
            "amazon": ("Amazon Basin, Brazil", -60.0, -3.0),
            "sahara": ("Sahara Desert", 10.0, 23.0),
            "himalaya": ("Himalayas", 86.925, 27.988),
            "great barrier reef": ("Great Barrier Reef, Australia", 147.7, -18.2871),
        }
        q = query.lower().strip()
        results = []
        for key, (name, lon, lat) in gazetteer.items():
            if key in q or q in key:
                results.append(
                    GeocodeResult(
                        display_name=name,
                        longitude=lon,
                        latitude=lat,
                        bounding_box=[lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5],
                        place_type="city",
                        importance=0.8,
                    )
                )
        if not results:
            # Try coordinate parse: "48.85, 2.35" or "2.35 48.85"
            import re

            nums = re.findall(r"[-+]?\d*\.?\d+", query)
            if len(nums) >= 2:
                a, b = float(nums[0]), float(nums[1])
                # Heuristic: if first is within lat range and second lon-ish
                if -90 <= a <= 90 and -180 <= b <= 180:
                    lat, lon = a, b
                else:
                    lon, lat = a, b
                results.append(
                    GeocodeResult(
                        display_name=f"Coordinates ({lat:.5f}, {lon:.5f})",
                        longitude=lon,
                        latitude=lat,
                        place_type="coordinate",
                        importance=1.0,
                    )
                )
        return results

    async def reverse_geocode(self, longitude: float, latitude: float) -> GeocodeResult:
        url = f"{self.settings.nominatim_url}/reverse"
        params = {"lon": longitude, "lat": latitude, "format": "json"}
        headers = {"User-Agent": "EarthVisionEnterprise/1.0"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return GeocodeResult(
                        display_name=data.get("display_name", f"{latitude}, {longitude}"),
                        longitude=longitude,
                        latitude=latitude,
                        place_type=data.get("type"),
                    )
        except httpx.HTTPError:
            pass
        return GeocodeResult(
            display_name=f"{latitude:.5f}°, {longitude:.5f}°",
            longitude=longitude,
            latitude=latitude,
            place_type="coordinate",
        )

    def measure(self, request: MeasurementRequest) -> MeasurementResponse:
        try:
            geom = shape(request.geometry)
        except Exception as exc:
            raise ValidationError("Invalid geometry", details=str(exc)) from exc

        # Project to equal-area for accurate measurements
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        projected = transform(transformer.transform, geom)

        length_m = None
        area_m2 = None
        perimeter_m = None

        if geom.geom_type in ("LineString", "MultiLineString"):
            length_m = float(projected.length)
        elif geom.geom_type in ("Polygon", "MultiPolygon"):
            area_m2 = float(projected.area)
            perimeter_m = float(projected.length)
        elif geom.geom_type == "Point":
            length_m = 0.0
            area_m2 = 0.0

        unit = request.unit
        display = ""
        if area_m2 is not None:
            if unit == "hectares":
                display = f"{area_m2 / 10_000:.2f} ha"
            elif unit == "acres":
                display = f"{area_m2 / 4046.8564224:.2f} ac"
            elif unit == "kilometers":
                display = f"{area_m2 / 1_000_000:.4f} km²"
            elif unit == "miles":
                display = f"{area_m2 / 2_589_988.110336:.4f} mi²"
            else:
                display = f"{area_m2:.2f} m²"
        elif length_m is not None:
            if unit == "kilometers":
                display = f"{length_m / 1000:.3f} km"
            elif unit == "miles":
                display = f"{length_m / 1609.344:.3f} mi"
            else:
                display = f"{length_m:.2f} m"

        return MeasurementResponse(
            length_meters=length_m,
            area_sq_meters=area_m2,
            perimeter_meters=perimeter_m,
            display_value=display,
            unit=unit,
        )

    def geojson_to_kml(self, geojson: dict[str, Any]) -> str:
        """Convert GeoJSON FeatureCollection to KML."""
        features = geojson.get("features", [geojson] if geojson.get("type") == "Feature" else [])
        placemarks = []
        for i, feat in enumerate(features):
            geom = feat.get("geometry", {})
            name = (feat.get("properties") or {}).get("name", f"Feature {i+1}")
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            if gtype == "Point":
                lon, lat = coords[0], coords[1]
                alt = coords[2] if len(coords) > 2 else 0
                placemarks.append(
                    f"<Placemark><name>{name}</name>"
                    f"<Point><coordinates>{lon},{lat},{alt}</coordinates></Point>"
                    f"</Placemark>"
                )
            elif gtype == "Polygon":
                ring = coords[0] if coords else []
                coord_str = " ".join(f"{c[0]},{c[1]},0" for c in ring)
                placemarks.append(
                    f"<Placemark><name>{name}</name><Polygon>"
                    f"<outerBoundaryIs><LinearRing><coordinates>{coord_str}</coordinates>"
                    f"</LinearRing></outerBoundaryIs></Polygon></Placemark>"
                )
            elif gtype == "LineString":
                coord_str = " ".join(f"{c[0]},{c[1]},0" for c in coords)
                placemarks.append(
                    f"<Placemark><name>{name}</name>"
                    f"<LineString><coordinates>{coord_str}</coordinates></LineString>"
                    f"</Placemark>"
                )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            + "".join(placemarks)
            + "</Document></kml>"
        )

    def validate_geojson(self, geojson: dict[str, Any]) -> dict[str, Any]:
        try:
            geom = shape(geojson if "coordinates" in geojson else geojson.get("geometry", geojson))
            if not geom.is_valid:
                raise ValidationError("Invalid geometry topology")
            return mapping(geom)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError("Unable to parse GeoJSON", details=str(exc)) from exc


    def geojson_to_shapefile_zip(self, geojson: dict[str, Any]) -> bytes:
        """Export GeoJSON features to a zipped Shapefile."""
        import io
        import zipfile
        import tempfile
        from pathlib import Path as P

        import shapefile

        features = geojson.get("features", [geojson] if geojson.get("type") == "Feature" else [])
        with tempfile.TemporaryDirectory() as tmp:
            base = P(tmp) / "export"
            # Detect geometry type from first feature
            gtype = (features[0].get("geometry") or {}).get("type", "Polygon") if features else "Polygon"
            shape_type = {
                "Point": shapefile.POINT,
                "LineString": shapefile.POLYLINE,
                "Polygon": shapefile.POLYGON,
            }.get(gtype, shapefile.POLYGON)
            with shapefile.Writer(str(base), shapeType=shape_type) as w:
                w.field("name", "C", size=100)
                for feat in features:
                    props = feat.get("properties") or {}
                    geom = feat.get("geometry") or {}
                    coords = geom.get("coordinates")
                    name = str(props.get("name", "feature"))[:100]
                    if geom.get("type") == "Point":
                        w.point(coords[0], coords[1])
                    elif geom.get("type") == "LineString":
                        w.line([coords])
                    elif geom.get("type") == "Polygon":
                        w.poly(coords)
                    else:
                        continue
                    w.record(name)
            # Write .prj
            (P(tmp) / "export.prj").write_text(
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
            )
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in P(tmp).iterdir():
                    zf.write(f, f.name)
            return buf.getvalue()

    def shapefile_zip_to_geojson(self, content: bytes) -> dict[str, Any]:
        """Import a zipped Shapefile into GeoJSON FeatureCollection."""
        import io
        import zipfile
        import tempfile
        from pathlib import Path as P

        import shapefile

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                zf.extractall(tmp)
            shp = next(P(tmp).rglob("*.shp"), None)
            if shp is None:
                raise ValidationError("No .shp file found in archive")
            reader = shapefile.Reader(str(shp))
            features = []
            fields = [f[0] for f in reader.fields[1:]]
            for sr in reader.shapeRecords():
                geom = sr.shape.__geo_interface__
                props = dict(zip(fields, sr.record, strict=False))
                features.append({"type": "Feature", "geometry": geom, "properties": props})
            return {"type": "FeatureCollection", "features": features}
