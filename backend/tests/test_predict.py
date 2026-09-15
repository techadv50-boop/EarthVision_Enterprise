"""SatPass Predict geometry parse + report export."""

import json
import zipfile
from io import BytesIO

import pytest


def _kml_point() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Islamabad</name>
      <Point><coordinates>73.0479,33.6844,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""


def _kml_polygon() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>Test AOI</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
            73.0,33.6,0 73.2,33.6,0 73.2,33.8,0 73.0,33.8,0 73.0,33.6,0
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</kml>
"""


@pytest.mark.asyncio
async def test_geometry_requires_auth(client):
    resp = await client.post("/api/v1/satellites/predict/geometry")
    assert resp.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_parse_geojson_point(client, auth_headers):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Islamabad"},
                "geometry": {"type": "Point", "coordinates": [73.0479, 33.6844]},
            }
        ],
    }
    resp = await client.post(
        "/api/v1/satellites/predict/geometry",
        headers=auth_headers,
        files={"files": ("target.geojson", json.dumps(geojson).encode("utf-8"), "application/geo+json")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["feature_count"] == 1
    assert body["geojson"]["features"][0]["geometry"]["type"] == "Point"


@pytest.mark.asyncio
async def test_parse_kml_point_and_polygon(client, auth_headers):
    point = await client.post(
        "/api/v1/satellites/predict/geometry",
        headers=auth_headers,
        files={"files": ("point.kml", _kml_point(), "application/vnd.google-earth.kml+xml")},
    )
    assert point.status_code == 200, point.text
    assert point.json()["feature_count"] >= 1
    assert point.json()["geojson"]["features"][0]["geometry"]["type"] == "Point"

    poly = await client.post(
        "/api/v1/satellites/predict/geometry",
        headers=auth_headers,
        files={"files": ("area.kml", _kml_polygon(), "application/vnd.google-earth.kml+xml")},
    )
    assert poly.status_code == 200, poly.text
    assert poly.json()["geojson"]["features"][0]["geometry"]["type"] == "Polygon"


@pytest.mark.asyncio
async def test_export_csv_xlsx_pdf(client, auth_headers):
    payload = {
        "title": "satpass-prediction",
        "headers": ["Satellite Name", "Start Tracking Time", "End Tracking Time"],
        "rows": [["ISS (ZARYA)", "2026-09-11 10:00:00 UTC", "2026-09-11 10:08:00 UTC"]],
    }
    csv_resp = await client.post(
        "/api/v1/satellites/predict/export",
        headers=auth_headers,
        json={**payload, "format": "csv"},
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert b"ISS (ZARYA)" in csv_resp.content
    assert csv_resp.headers["content-type"].startswith("text/csv")

    xlsx = await client.post(
        "/api/v1/satellites/predict/export",
        headers=auth_headers,
        json={**payload, "format": "xlsx"},
    )
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content[:2] == b"PK"

    pdf = await client.post(
        "/api/v1/satellites/predict/export",
        headers=auth_headers,
        json={**payload, "format": "pdf"},
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")


def test_parse_kml_simple_helper():
    from app.routers.predict import _parse_kml_simple

    fc = _parse_kml_simple(_kml_polygon())
    assert fc["features"][0]["geometry"]["type"] == "Polygon"
    ring = fc["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]


@pytest.mark.asyncio
async def test_parse_shapefile_zip(client, auth_headers, tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    gdf = gpd.GeoDataFrame(
        {"name": ["AOI"]},
        geometry=[Polygon([(73.0, 33.6), (73.2, 33.6), (73.2, 33.8), (73.0, 33.8)])],
        crs="EPSG:4326",
    )
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf.to_file(shp_dir / "aoi.shp")
    zip_bytes = BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        for path in shp_dir.iterdir():
            zf.write(path, path.name)
    zip_bytes.seek(0)
    resp = await client.post(
        "/api/v1/satellites/predict/geometry",
        headers=auth_headers,
        files={"files": ("aoi.zip", zip_bytes.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["geojson"]["features"][0]["geometry"]["type"] == "Polygon"
