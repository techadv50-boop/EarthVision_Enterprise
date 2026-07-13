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
    SpatialOpRequest,
    SpatialOpResponse,
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

    def buffer_geometry(self, geometry: dict[str, Any], distance_meters: float, segments: int = 32) -> dict[str, Any]:
        """Buffer a GeoJSON geometry by distance in metres (EPSG:6933)."""
        from app.schemas.terrain import BufferResponse

        try:
            geom = shape(geometry if geometry.get("type") != "Feature" else geometry["geometry"])
        except Exception as exc:
            raise ValidationError("Invalid geometry", details=str(exc)) from exc

        to_m = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        to_ll = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)
        projected = transform(to_m.transform, geom)
        buffered = projected.buffer(distance_meters, resolution=max(segments // 4, 2))
        result = transform(to_ll.transform, buffered)
        minx, miny, maxx, maxy = result.bounds
        area = float(buffered.area) if not buffered.is_empty else None
        return BufferResponse(
            geometry=mapping(result),
            distance_meters=distance_meters,
            area_sq_meters=area,
            bounds=[minx, miny, maxx, maxy],
        ).model_dump()

    # ------------------------------------------------------------------
    # Spatial operations
    # ------------------------------------------------------------------

    def spatial_op(self, request: SpatialOpRequest) -> SpatialOpResponse:
        geoms, props = self._parse_geometries(request.geometries)
        if not geoms:
            raise ValidationError("No valid geometries provided")
        op = request.operation
        dist = request.distance_meters

        if op == "intersect":
            result_geoms, result_props = self._op_intersect(geoms, props)
        elif op == "union":
            result_geoms, result_props = self._op_union(geoms, props)
        elif op == "clip":
            result_geoms, result_props = self._op_clip(geoms, props)
        elif op == "dissolve":
            result_geoms, result_props = self._op_dissolve(geoms, props)
        elif op == "merge":
            result_geoms, result_props = self._op_merge(geoms, props)
        elif op == "convex_hull":
            result_geoms, result_props = self._op_convex_hull(geoms, props)
        elif op in ("voronoi", "thiessen"):
            result_geoms, result_props = self._op_voronoi(geoms, props)
        elif op == "nearest":
            result_geoms, result_props = self._op_nearest(geoms, props, dist)
        elif op in ("density", "hotspot"):
            result_geoms, result_props = self._op_density(geoms, props, dist, hotspot=op == "hotspot")
        else:
            raise ValidationError(f"Unsupported spatial operation: {op}")

        features = []
        for i, (g, p) in enumerate(zip(result_geoms, result_props, strict=False)):
            if g is None or g.is_empty:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {**(p or {}), "operation": op, "index": i},
                    "geometry": mapping(g),
                }
            )
        fc = {"type": "FeatureCollection", "features": features}
        bounds = None
        if features:
            from shapely.geometry import shape as shp_shape
            from shapely.ops import unary_union

            try:
                combined = unary_union([shp_shape(f["geometry"]) for f in features])
                minx, miny, maxx, maxy = combined.bounds
                bounds = [minx, miny, maxx, maxy]
            except Exception:  # noqa: BLE001
                bounds = None
        return SpatialOpResponse(
            operation=op,
            geojson=fc,
            count=len(features),
            message=f"{op}: {len(features)} feature(s)",
            bounds=bounds,
        )

    def _parse_geometries(
        self, items: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        from shapely.geometry import shape as shp_shape

        geoms: list[Any] = []
        props: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Allow passing a FeatureCollection as a single list element
            if item.get("type") == "FeatureCollection":
                for feat in item.get("features") or []:
                    try:
                        g = shp_shape(feat.get("geometry") or feat)
                        geoms.append(g)
                        props.append(dict(feat.get("properties") or {}))
                    except Exception:  # noqa: BLE001
                        continue
                continue
            try:
                if item.get("type") == "Feature":
                    g = shp_shape(item["geometry"])
                    geoms.append(g)
                    props.append(dict(item.get("properties") or {}))
                elif "coordinates" in item:
                    g = shp_shape(item)
                    geoms.append(g)
                    props.append({})
                elif "geometry" in item:
                    g = shp_shape(item["geometry"])
                    geoms.append(g)
                    props.append(dict(item.get("properties") or {}))
            except Exception:  # noqa: BLE001
                continue
        return geoms, props

    def _op_intersect(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        if len(geoms) < 2:
            raise ValidationError("intersect requires at least 2 geometries")
        result = geoms[0]
        for g in geoms[1:]:
            result = result.intersection(g)
        return [result], [{"name": "intersection"}]

    def _op_union(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        from shapely.ops import unary_union

        return [unary_union(geoms)], [{"name": "union"}]

    def _op_clip(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Clip geometries[1:] by geometries[0] (clip mask)."""
        if len(geoms) < 2:
            raise ValidationError("clip requires mask + at least one target geometry")
        mask = geoms[0]
        out_g, out_p = [], []
        for g, p in zip(geoms[1:], props[1:], strict=False):
            clipped = g.intersection(mask)
            if not clipped.is_empty:
                out_g.append(clipped)
                out_p.append(p)
        return out_g, out_p

    def _op_dissolve(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        from shapely.ops import unary_union

        return [unary_union(geoms)], [{"name": "dissolved", "n_input": len(geoms)}]

    def _op_merge(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Merge into a GeometryCollection / keep as Multi* when possible."""
        from shapely.geometry import GeometryCollection
        from shapely.ops import unary_union

        types = {g.geom_type for g in geoms}
        if len(types) == 1:
            return [unary_union(geoms)], [{"name": "merged", "n_input": len(geoms)}]
        return [GeometryCollection(geoms)], [{"name": "merged", "n_input": len(geoms)}]

    def _op_convex_hull(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        from shapely.ops import unary_union

        hull = unary_union(geoms).convex_hull
        return [hull], [{"name": "convex_hull"}]

    def _op_voronoi(
        self, geoms: list[Any], props: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        from shapely.geometry import MultiPoint, Point
        from shapely.ops import unary_union, voronoi_diagram

        points = []
        for g in geoms:
            if g.geom_type == "Point":
                points.append(g)
            elif g.geom_type == "MultiPoint":
                points.extend(list(g.geoms))
            else:
                points.append(Point(g.centroid.x, g.centroid.y))
        if len(points) < 2:
            raise ValidationError("voronoi/thiessen requires at least 2 points")
        mp = MultiPoint(points)
        envelope = unary_union(geoms).envelope.buffer(
            max(unary_union(geoms).bounds[2] - unary_union(geoms).bounds[0], 0.01) * 0.1
        )
        diagram = voronoi_diagram(mp, envelope=envelope)
        cells = list(diagram.geoms) if hasattr(diagram, "geoms") else [diagram]
        out_g, out_p = [], []
        for i, cell in enumerate(cells):
            out_g.append(cell)
            out_p.append({"name": f"cell_{i}", "site_index": i})
        return out_g, out_p

    def _op_nearest(
        self,
        geoms: list[Any],
        props: list[dict[str, Any]],
        distance_meters: float | None,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Nearest-neighbour links from each geometry to the closest other."""
        from shapely.geometry import LineString

        if len(geoms) < 2:
            raise ValidationError("nearest requires at least 2 geometries")
        to_m = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        projected = [transform(to_m.transform, g) for g in geoms]
        out_g, out_p = [], []
        max_d = distance_meters if distance_meters and distance_meters > 0 else None
        for i, a in enumerate(projected):
            best_j, best_d = None, float("inf")
            for j, b in enumerate(projected):
                if i == j:
                    continue
                d = a.distance(b)
                if d < best_d:
                    best_d, best_j = d, j
            if best_j is None:
                continue
            if max_d is not None and best_d > max_d:
                continue
            c0 = geoms[i].centroid
            c1 = geoms[best_j].centroid
            out_g.append(LineString([(c0.x, c0.y), (c1.x, c1.y)]))
            out_p.append(
                {
                    "from_index": i,
                    "to_index": best_j,
                    "distance_meters": float(best_d),
                }
            )
        return out_g, out_p

    def _op_density(
        self,
        geoms: list[Any],
        props: list[dict[str, Any]],
        distance_meters: float | None,
        *,
        hotspot: bool = False,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Simple point-density: count neighbours within radius, emit buffered circles."""
        radius = distance_meters if distance_meters and distance_meters > 0 else 500.0
        to_m = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        to_ll = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)
        projected = [transform(to_m.transform, g) for g in geoms]
        centroids = [g.centroid for g in projected]
        counts = []
        for i, c in enumerate(centroids):
            n = sum(1 for j, o in enumerate(centroids) if i != j and c.distance(o) <= radius)
            counts.append(n)
        threshold = 0
        if hotspot and counts:
            import numpy as np

            threshold = float(np.percentile(counts, 75)) if max(counts) > 0 else 0
        out_g, out_p = [], []
        for i, (c, n) in enumerate(zip(centroids, counts, strict=False)):
            if hotspot and n < threshold:
                continue
            buffered = c.buffer(radius * (0.35 + 0.1 * min(n, 5)))
            out_g.append(transform(to_ll.transform, buffered))
            out_p.append(
                {
                    "density": int(n),
                    "radius_meters": radius,
                    "hotspot": bool(hotspot and n >= threshold),
                    **(props[i] if i < len(props) else {}),
                }
            )
        return out_g, out_p
