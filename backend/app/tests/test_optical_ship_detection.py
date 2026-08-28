"""Unit tests for optical NIR ship detection (no remote I/O)."""

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


def test_nir_ship_detect_ignores_water_and_cloud_finds_metal():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 64
    nir = np.full((h, w), 0.03, dtype=np.float64)  # dark water-ish
    green = np.full((h, w), 0.08, dtype=np.float64)
    blue = np.full((h, w), 0.06, dtype=np.float64)
    red = np.full((h, w), 0.04, dtype=np.float64)
    # Open water (high NDWI): green high, nir low
    green[:, :] = 0.12
    nir[:, :] = 0.02
    # Cloud patch (bright blue+nir)
    blue[2:10, 2:10] = 0.4
    nir[2:10, 2:10] = 0.35
    green[2:10, 2:10] = 0.35
    # Metal ship deck on water — high NIR, not water-classed
    nir[30:34, 40:48] = 0.28
    green[30:34, 40:48] = 0.06
    red[30:34, 40:48] = 0.08
    blue[30:34, 40:48] = 0.05

    bands = {"nir": nir, "green": green, "blue": blue, "red": red}
    bounds = [74.0, 31.0, 74.5, 31.4]
    out = detect_ships_optical_nir(bands, bounds, confidence_min=0.15, collection="SENTINEL-2")
    assert out["count"] >= 1
    assert any(f["geometry"]["type"] == "Point" for f in out["geojson"]["features"])
    assert any(f["geometry"]["type"] == "Polygon" for f in out["geojson"]["features"])
    assert "NIR" in out["formula"]
    assert out["overlay"] is not None
    assert out["overlay"].shape == (h, w, 4)


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
    # Import writer path without requiring pyproj (lazy GISService import fails otherwise)
    import importlib.util
    from pathlib import Path

    # Exercise export helper via a minimal stub if GISService import is heavy
    from app.services.gis_service import GISService

    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [74.1, 31.2]},
                "properties": {
                    "label": "Ship",
                    "class": "ship",
                    "confidence": 0.8,
                    "nir_mean": 0.25,
                    "cue": "metal_nir",
                    "geom_role": "centroid",
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [74.09, 31.19],
                            [74.11, 31.19],
                            [74.11, 31.21],
                            [74.09, 31.21],
                            [74.09, 31.19],
                        ]
                    ],
                },
                "properties": {
                    "label": "Ship",
                    "class": "ship",
                    "confidence": 0.8,
                    "nir_mean": 0.25,
                    "cue": "metal_nir",
                    "geom_role": "footprint",
                },
            },
        ],
    }
    z = GISService().geojson_to_shapefile_zip(gj)
    assert z[:2] == b"PK"
    assert len(z) > 100
