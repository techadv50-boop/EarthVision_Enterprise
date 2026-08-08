"""Ingest vector files (point / line / polygon) for SAT EYE offline use."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

VECTOR_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".geojson",
        ".json",
        ".zip",  # shapefile zip
        ".kml",
        ".kmz",
        ".gpx",
        ".gml",
        ".shp",
    }
)

ACCEPT_ATTRIBUTE = ",".join(sorted(VECTOR_EXTENSIONS))


class VectorIngestService:
    @staticmethod
    def supported_formats() -> dict[str, Any]:
        return {
            "extensions": sorted(VECTOR_EXTENSIONS),
            "accept": ACCEPT_ATTRIBUTE,
            "geometry_types": ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"],
            "notes": "SAT EYE supports point, line, and polygon vector data offline.",
        }

    @classmethod
    def is_supported(cls, filename: str) -> bool:
        return Path(filename).suffix.lower() in VECTOR_EXTENSIONS

    def ingest(self, source_path: Path, dest_dir: Path, *, original_filename: str | None = None) -> dict[str, Any]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = original_filename or source_path.name
        if not self.is_supported(name):
            raise ValueError(
                f"Unsupported vector format '{Path(name).suffix}'. "
                f"Accepted: {', '.join(sorted(VECTOR_EXTENSIONS))}"
            )

        safe = Path(name).name
        stored = dest_dir / f"user_{safe}"
        if source_path.resolve() != stored.resolve():
            shutil.copy2(source_path, stored)

        geojson = self._load_as_geojson(stored)
        stats = self._geometry_stats(geojson)
        out_geojson = dest_dir / f"{stored.stem}.geojson"
        out_geojson.write_text(json.dumps(geojson))

        return {
            "original_path": str(stored),
            "geojson_path": str(out_geojson),
            "original_format": Path(name).suffix.lower(),
            "feature_count": stats["feature_count"],
            "geometry_counts": stats["geometry_counts"],
            "bbox": stats["bbox"],
            "geojson": geojson,
        }

    def _load_as_geojson(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()

        if suffix in {".geojson", ".json"}:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._as_feature_collection(data)

        if suffix == ".zip" or suffix == ".shp":
            return self._read_with_geopandas(path)

        if suffix in {".kml", ".kmz", ".gpx", ".gml"}:
            return self._read_with_geopandas(path)

        raise ValueError(f"Cannot parse vector file: {path.name}")

    def _read_with_geopandas(self, path: Path) -> dict[str, Any]:
        try:
            import geopandas as gpd
        except ImportError as exc:
            raise ValueError("geopandas is required for this vector format") from exc

        target = path
        tmp_extract: Path | None = None
        if path.suffix.lower() == ".zip":
            tmp_extract = path.parent / f"_extract_{path.stem}"
            if tmp_extract.exists():
                shutil.rmtree(tmp_extract, ignore_errors=True)
            tmp_extract.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(tmp_extract)
            # Prefer .shp inside archive
            shps = list(tmp_extract.rglob("*.shp"))
            if shps:
                target = shps[0]
            else:
                # try any readable layer
                target = tmp_extract

        try:
            gdf = gpd.read_file(str(target))
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            else:
                gdf = gdf.to_crs("EPSG:4326")
            data = json.loads(gdf.to_json())
            return self._as_feature_collection(data)
        finally:
            if tmp_extract is not None:
                shutil.rmtree(tmp_extract, ignore_errors=True)

    @staticmethod
    def _as_feature_collection(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("type") == "FeatureCollection":
            return data
        if data.get("type") == "Feature":
            return {"type": "FeatureCollection", "features": [data]}
        # bare geometry
        if data.get("type") in {
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        }:
            return {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {}, "geometry": data}],
            }
        raise ValueError("Unrecognized GeoJSON structure")

    @staticmethod
    def _geometry_stats(geojson: dict[str, Any]) -> dict[str, Any]:
        counts: dict[str, int] = {
            "Point": 0,
            "MultiPoint": 0,
            "LineString": 0,
            "MultiLineString": 0,
            "Polygon": 0,
            "MultiPolygon": 0,
            "Other": 0,
        }
        xs: list[float] = []
        ys: list[float] = []

        def walk_coords(coords: Any) -> None:
            if not coords:
                return
            if isinstance(coords[0], (int, float)) and len(coords) >= 2:
                xs.append(float(coords[0]))
                ys.append(float(coords[1]))
                return
            for c in coords:
                walk_coords(c)

        features = geojson.get("features") or []
        for f in features:
            geom = (f or {}).get("geometry") or {}
            gtype = geom.get("type") or "Other"
            if gtype in counts:
                counts[gtype] += 1
            else:
                counts["Other"] += 1
            walk_coords(geom.get("coordinates"))

        bbox = None
        if xs and ys:
            bbox = [min(xs), min(ys), max(xs), max(ys)]

        return {
            "feature_count": len(features),
            "geometry_counts": counts,
            "bbox": bbox,
            "has_points": counts["Point"] + counts["MultiPoint"] > 0,
            "has_lines": counts["LineString"] + counts["MultiLineString"] > 0,
            "has_polygons": counts["Polygon"] + counts["MultiPolygon"] > 0,
        }
