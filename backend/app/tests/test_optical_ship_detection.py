"""Unit tests for optical ship detection (no remote I/O)."""

from __future__ import annotations

import numpy as np
import pytest


def test_collection_gate_landsat_s2_only():
    from app.services.optical_ship_detection import collection_is_optical_landsat_or_s2

    assert collection_is_optical_landsat_or_s2("SENTINEL-2")
    assert collection_is_optical_landsat_or_s2("sentinel-2-l2a")
    assert collection_is_optical_landsat_or_s2("LANDSAT-8")
    assert collection_is_optical_landsat_or_s2("landsat-c2-l2")
    assert not collection_is_optical_landsat_or_s2("SENTINEL-1")
    assert not collection_is_optical_landsat_or_s2("SENTINEL-3")
    assert not collection_is_optical_landsat_or_s2(None)


def test_open_sea_bright_ship_not_masked_as_cloud():
    """Bright white decks over water must NOT be cloud-masked (live Asaluyeh bug)."""
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 96
    # Dark open water
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.05, dtype=np.float64)
    blue = np.full((h, w), 0.04, dtype=np.float64)
    red = np.full((h, w), 0.03, dtype=np.float64)
    # Bright white ship + wake (high VIS+NIR) — old code treated as cloud
    nir[40:48, 55:70] = 0.42
    green[40:48, 55:70] = 0.45
    blue[40:48, 55:70] = 0.48
    red[40:48, 55:70] = 0.44
    # Wake trail
    nir[44:47, 30:55] = 0.18
    green[44:47, 30:55] = 0.22
    blue[44:47, 30:55] = 0.25
    red[44:47, 30:55] = 0.20

    out = detect_ships_optical_nir(
        {"nir": nir, "green": green, "blue": blue, "red": red},
        [52.8, 26.5, 53.0, 26.7],
        confidence_min=0.15,
        collection="SENTINEL-2",
    )
    assert out["count"] >= 1, out["message"]
    assert any(f["geometry"]["type"] == "Point" for f in out["geojson"]["features"])
    assert any(f["geometry"]["type"] == "Polygon" for f in out["geojson"]["features"])
    assert out["overlay"] is not None


def test_open_sea_bright_ship_respects_water_aoi():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 96
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.05, dtype=np.float64)
    blue = np.full((h, w), 0.04, dtype=np.float64)
    red = np.full((h, w), 0.03, dtype=np.float64)
    nir[40:48, 55:70] = 0.42
    green[40:48, 55:70] = 0.45
    blue[40:48, 55:70] = 0.48
    red[40:48, 55:70] = 0.44
    bounds = [52.8, 26.5, 53.0, 26.7]
    # AOI covering the ship cell
    aoi = {
        "type": "Polygon",
        "coordinates": [
            [
                [52.88, 26.58],
                [52.95, 26.58],
                [52.95, 26.64],
                [52.88, 26.64],
                [52.88, 26.58],
            ]
        ],
    }
    out = detect_ships_optical_nir(
        {"nir": nir, "green": green, "blue": blue, "red": red},
        bounds,
        confidence_min=0.15,
        collection="SENTINEL-2",
        aoi_polygon=aoi,
    )
    assert out["count"] >= 1
    # AOI far from ship → zero
    aoi_miss = {
        "type": "Polygon",
        "coordinates": [
            [
                [52.80, 26.50],
                [52.82, 26.50],
                [52.82, 26.52],
                [52.80, 26.52],
                [52.80, 26.50],
            ]
        ],
    }
    out0 = detect_ships_optical_nir(
        {"nir": nir, "green": green, "blue": blue, "red": red},
        bounds,
        confidence_min=0.15,
        collection="SENTINEL-2",
        aoi_polygon=aoi_miss,
    )
    assert out0["count"] == 0


def test_nir_ship_detect_ignores_water_and_cloud_finds_metal():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 64
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.12, dtype=np.float64)
    blue = np.full((h, w), 0.06, dtype=np.float64)
    red = np.full((h, w), 0.04, dtype=np.float64)
    # Inland cloud patch
    blue[2:10, 2:10] = 0.4
    nir[2:10, 2:10] = 0.35
    green[2:10, 2:10] = 0.35
    # Metal ship deck on water
    nir[30:34, 40:48] = 0.28
    green[30:34, 40:48] = 0.06
    red[30:34, 40:48] = 0.08
    blue[30:34, 40:48] = 0.05

    bands = {"nir": nir, "green": green, "blue": blue, "red": red}
    bounds = [74.0, 31.0, 74.5, 31.4]
    out = detect_ships_optical_nir(bands, bounds, confidence_min=0.15, collection="SENTINEL-2")
    assert out["count"] >= 1
    assert "reflectance" in out["formula"].lower() or "NIR" in out["formula"] or "CFAR" in out["formula"]
    assert out["overlay"] is not None
    assert out["overlay"].shape == (h, w, 4)


def test_nir_ship_detect_default_confidence_keeps_metal():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 64
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.12, dtype=np.float64)
    blue = np.full((h, w), 0.06, dtype=np.float64)
    red = np.full((h, w), 0.04, dtype=np.float64)
    nir[30:34, 40:48] = 0.28
    green[30:34, 40:48] = 0.06
    red[30:34, 40:48] = 0.08
    blue[30:34, 40:48] = 0.05

    out = detect_ships_optical_nir(
        {"nir": nir, "green": green, "blue": blue, "red": red},
        [74.0, 31.0, 74.5, 31.4],
        confidence_min=0.22,
        collection="SENTINEL-2",
    )
    assert out["count"] >= 1


def test_ship_detect_requires_nir():
    from app.core.exceptions import ValidationError
    from app.services.optical_ship_detection import detect_ships_optical_nir

    with pytest.raises(ValidationError, match="NIR"):
        detect_ships_optical_nir({"green": np.zeros((8, 8))}, [0, 0, 1, 1], collection="SENTINEL-2")


def test_ship_detect_rejects_sar_collection():
    from app.core.exceptions import ValidationError
    from app.services.optical_ship_detection import detect_ships_optical_nir

    bands = {"nir": np.ones((8, 8)) * 0.2, "green": np.ones((8, 8)) * 0.1}
    with pytest.raises(ValidationError, match="Landsat or Sentinel-2"):
        detect_ships_optical_nir(bands, [0, 0, 1, 1], collection="SENTINEL-1")


def test_mixed_geometry_shapefile_zip():
    pyshp = pytest.importorskip("shapefile")
    del pyshp
    from app.services.gis_service import GISService

    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [52.88, 26.61]},
                "properties": {"class": "ship", "geom_role": "centroid"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [52.879, 26.611],
                            [52.881, 26.611],
                            [52.881, 26.609],
                            [52.879, 26.609],
                            [52.879, 26.611],
                        ]
                    ],
                },
                "properties": {"class": "ship", "geom_role": "footprint"},
            },
        ],
    }
    data = GISService().geojson_to_shapefile_zip(gj)
    assert data[:2] == b"PK"
    assert len(data) > 200
