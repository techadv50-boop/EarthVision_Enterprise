"""Store and serve admin-uploaded district/city shapefile layers."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.core.config import get_settings

NAME_KEYS = (
    "name",
    "NAME",
    "Name",
    "district",
    "DISTRICT",
    "District",
    "city",
    "CITY",
    "City",
    "ADM2_EN",
    "ADM1_EN",
    "NAME_2",
    "NAME_1",
    "DIST_NAME",
    "CITY_NAME",
    "shapeName",
    "admin_name",
    "TEHSIL",
    "tehsil",
)


def layer_dir(layer_id: int) -> Path:
    root = get_settings().aoi_layer_dir
    root.mkdir(parents=True, exist_ok=True)
    path = root / str(layer_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def zip_path(layer_id: int) -> Path:
    return layer_dir(layer_id) / "source.zip"


def geojson_path(layer_id: int) -> Path:
    return layer_dir(layer_id) / "features.geojson"


def index_path(layer_id: int) -> Path:
    return layer_dir(layer_id) / "index.json"


def pick_name_field(properties: dict[str, Any]) -> str | None:
    keys = list(properties.keys())
    for wanted in NAME_KEYS:
        if wanted in properties and properties[wanted] not in (None, ""):
            return wanted
    for key in keys:
        if key.startswith("_"):
            continue
        val = properties.get(key)
        if isinstance(val, str) and val.strip():
            return key
    return None


def feature_name(props: dict[str, Any], name_field: str | None, fallback: str) -> str:
    if name_field and props.get(name_field) not in (None, ""):
        return str(props[name_field]).strip()
    for key in NAME_KEYS:
        if props.get(key) not in (None, ""):
            return str(props[key]).strip()
    return fallback


def parse_shapefile_zip(raw: bytes) -> dict[str, Any]:
    import geopandas as gpd

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "upload.zip"
        zpath.write_bytes(raw)
        gdf = gpd.read_file(zpath)
        if gdf.empty:
            raise ValueError("The shapefile contained no features.")
        if gdf.crs and str(gdf.crs).upper() not in {"EPSG:4326", "WGS84"}:
            gdf = gdf.to_crs(4326)
        return json.loads(gdf.to_json())


def annotate_features(fc: dict[str, Any]) -> tuple[dict[str, Any], str | None, list[dict[str, Any]]]:
    features = [f for f in fc.get("features") or [] if f.get("geometry")]
    if not features:
        raise ValueError("The shapefile contained no features.")
    sample_props = features[0].get("properties") or {}
    name_field = pick_name_field(sample_props)
    index: list[dict[str, Any]] = []
    out_features: list[dict[str, Any]] = []
    for i, feat in enumerate(features):
        props = dict(feat.get("properties") or {})
        fid = str(i)
        props["_satpass_id"] = fid
        name = feature_name(props, name_field, f"Feature {i + 1}")
        props["_satpass_name"] = name
        geom = feat["geometry"]
        out_features.append({"type": "Feature", "properties": props, "geometry": geom})
        index.append({"id": fid, "name": name})
    annotated = {"type": "FeatureCollection", "features": out_features}
    return annotated, name_field, index


def write_layer_files(layer_id: int, zip_bytes: bytes, geojson: dict[str, Any], index: list[dict[str, Any]]) -> None:
    dest = layer_dir(layer_id)
    zip_path(layer_id).write_bytes(zip_bytes)
    geojson_path(layer_id).write_text(json.dumps(geojson), encoding="utf-8")
    index_path(layer_id).write_text(json.dumps(index), encoding="utf-8")
    dest.mkdir(parents=True, exist_ok=True)


def read_geojson(layer_id: int) -> dict[str, Any]:
    path = geojson_path(layer_id)
    if not path.exists():
        raise FileNotFoundError(f"Layer {layer_id} has no stored GeoJSON.")
    return json.loads(path.read_text(encoding="utf-8"))


def read_index(layer_id: int) -> list[dict[str, Any]]:
    path = index_path(layer_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    fc = read_geojson(layer_id)
    return [
        {
            "id": str(f.get("properties", {}).get("_satpass_id", i)),
            "name": str(f.get("properties", {}).get("_satpass_name") or f"Feature {i + 1}"),
        }
        for i, f in enumerate(fc.get("features") or [])
    ]


def features_by_ids(layer_id: int, ids: list[str]) -> list[dict[str, Any]]:
    wanted = {str(i) for i in ids}
    fc = read_geojson(layer_id)
    out = []
    for feat in fc.get("features") or []:
        fid = str((feat.get("properties") or {}).get("_satpass_id", ""))
        if fid in wanted:
            out.append(feat)
    return out


def delete_layer_files(layer_id: int) -> None:
    dest = get_settings().aoi_layer_dir / str(layer_id)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def export_features_zip(features: list[dict[str, Any]], filename_stem: str = "aoi") -> bytes:
    import tempfile

    import geopandas as gpd

    if not features:
        raise ValueError("No features selected.")
    fc = {"type": "FeatureCollection", "features": features}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")
        shp = tmp_path / f"{filename_stem}.shp"
        gdf.to_file(shp)
        buf_path = tmp_path / f"{filename_stem}.zip"
        with zipfile.ZipFile(buf_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp_path.iterdir():
                if path.suffix in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
                    zf.write(path, path.name)
        return buf_path.read_bytes()
