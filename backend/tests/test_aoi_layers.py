"""Admin-managed shapefile layers for Predict AOIs."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from httpx import AsyncClient


def _zip_shapefile(tmp_path, names, polygons) -> bytes:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    gdf = gpd.GeoDataFrame(
        {"district": names},
        geometry=[Polygon(ring) for ring in polygons],
        crs="EPSG:4326",
    )
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf.to_file(shp_dir / "districts.shp")
    zip_bytes = BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        for path in shp_dir.iterdir():
            zf.write(path, path.name)
    return zip_bytes.getvalue()


@pytest.fixture
def layer_dir(tmp_path, monkeypatch):
    from app.core.config import get_settings

    dest = tmp_path / "aoi_layers"
    dest.mkdir()
    monkeypatch.setattr(get_settings(), "aoi_layer_dir", dest)
    return dest


@pytest.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Admin@123456"},
    )
    if resp.status_code != 200:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "operator@satpass.xdgen.com", "password": "pak123"},
        )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


KARACHI = [(66.8, 24.7), (67.3, 24.7), (67.3, 25.1), (66.8, 25.1)]
LAHORE = [(74.1, 31.3), (74.6, 31.3), (74.6, 31.7), (74.1, 31.7)]


@pytest.mark.asyncio
async def test_user_cannot_upload_or_delete_layer(client, auth_headers, layer_dir, tmp_path):
    raw = _zip_shapefile(tmp_path, ["Karachi"], [KARACHI])
    created = await client.post(
        "/api/v1/aoi-layers",
        headers=auth_headers,
        files={"file": ("districts.zip", raw, "application/zip")},
        data={"name": "Pakistan districts"},
    )
    assert created.status_code == 403, created.text


@pytest.mark.asyncio
async def test_admin_upload_list_select_and_user_read(
    client, auth_headers, admin_headers, layer_dir, tmp_path
):
    raw = _zip_shapefile(tmp_path, ["Karachi", "Lahore"], [KARACHI, LAHORE])
    created = await client.post(
        "/api/v1/aoi-layers",
        headers=admin_headers,
        files={"file": ("districts.zip", raw, "application/zip")},
        data={"name": "Pakistan districts"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["feature_count"] == 2
    assert body["name"] == "Pakistan districts"
    layer_id = body["id"]

    listed = await client.get("/api/v1/aoi-layers", headers=auth_headers)
    assert listed.status_code == 200
    assert any(row["id"] == layer_id for row in listed.json())

    detail = await client.get(f"/api/v1/aoi-layers/{layer_id}", headers=auth_headers)
    assert detail.status_code == 200
    names = {f["name"] for f in detail.json()["features"]}
    assert names == {"Karachi", "Lahore"}

    geo = await client.get(f"/api/v1/aoi-layers/{layer_id}/geojson", headers=auth_headers)
    assert geo.status_code == 200
    assert geo.json()["features"][0]["geometry"]["type"] == "Polygon"

    exported = await client.post(
        f"/api/v1/aoi-layers/{layer_id}/export-aoi",
        headers=auth_headers,
        json={"feature_ids": ["0"]},
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/zip")
    assert exported.content[:2] == b"PK"

    denied = await client.delete(f"/api/v1/aoi-layers/{layer_id}", headers=auth_headers)
    assert denied.status_code == 403

    deleted = await client.delete(f"/api/v1/aoi-layers/{layer_id}", headers=admin_headers)
    assert deleted.status_code == 204

    gone = await client.get(f"/api/v1/aoi-layers/{layer_id}", headers=auth_headers)
    assert gone.status_code == 404
