"""Unit tests for optical ship detection (GEE NIR≥threshold, no remote I/O)."""

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
    """Bright white decks over water must NOT be cloud-masked."""
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 96
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.05, dtype=np.float64)
    blue = np.full((h, w), 0.04, dtype=np.float64)
    red = np.full((h, w), 0.03, dtype=np.float64)
    # Bright white ship + wake (NIR well above GEE 0.10)
    nir[40:48, 55:70] = 0.42
    green[40:48, 55:70] = 0.45
    blue[40:48, 55:70] = 0.48
    red[40:48, 55:70] = 0.44
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
    cents = [
        f
        for f in out["geojson"]["features"]
        if f["properties"].get("geom_role") == "centroid"
    ]
    assert cents and cents[0]["properties"].get("contact_id") == 1
    assert any(f["geometry"]["type"] == "Point" for f in out["geojson"]["features"])
    assert any(f["geometry"]["type"] == "Polygon" for f in out["geojson"]["features"])
    assert out["overlay"] is not None
    # Morph outline only — some red pixels with high alpha
    assert int((out["overlay"][:, :, 3] > 0).sum()) > 0


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


def test_nir_ge_threshold_finds_metal_deck():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 64
    nir = np.full((h, w), 0.02, dtype=np.float64)
    green = np.full((h, w), 0.12, dtype=np.float64)
    blue = np.full((h, w), 0.06, dtype=np.float64)
    red = np.full((h, w), 0.04, dtype=np.float64)
    # Inland cloud patch (large) — should be ignored if outside water logic;
    # still in search when no AOI, but size > max_px drops huge sheets
    blue[2:10, 2:10] = 0.4
    nir[2:10, 2:10] = 0.35
    green[2:10, 2:10] = 0.35
    # Metal ship deck on water — NIR > 0.10
    nir[30:34, 40:48] = 0.28
    green[30:34, 40:48] = 0.06
    red[30:34, 40:48] = 0.08
    blue[30:34, 40:48] = 0.05

    bands = {"nir": nir, "green": green, "blue": blue, "red": red}
    bounds = [74.0, 31.0, 74.5, 31.4]
    out = detect_ships_optical_nir(bands, bounds, confidence_min=0.15, collection="SENTINEL-2")
    assert out["count"] >= 1
    formula = out["formula"].lower()
    assert "nir" in formula and ("0.10" in formula or "opt" in formula or "threshold" in formula)
    assert out["overlay"] is not None
    assert out["overlay"].shape == (h, w, 4)


def test_two_open_sea_hulls_above_nir_threshold():
    """Two bright hulls (NIR≥0.10) on dark open water → two contacts."""
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 96
    nir = np.full((h, w), 0.035, dtype=np.float64)
    green = np.full((h, w), 0.04, dtype=np.float64)
    blue = np.full((h, w), 0.045, dtype=np.float64)
    red = np.full((h, w), 0.03, dtype=np.float64)
    # Ship A
    nir[30:34, 20:28] = 0.32
    red[30:34, 20:28] = 0.28
    green[30:34, 20:28] = 0.26
    blue[30:34, 20:28] = 0.24
    # Ship B
    nir[55:59, 50:58] = 0.30
    red[55:59, 50:58] = 0.25
    green[55:59, 50:58] = 0.22
    blue[55:59, 50:58] = 0.20

    out = detect_ships_optical_nir(
        {"nir": nir, "green": green, "blue": blue, "red": red},
        [52.8, 26.8, 52.9, 26.9],
        confidence_min=0.10,
        collection="SENTINEL-2",
        nir_threshold=0.10,
    )
    assert out["count"] >= 2, out["message"]
    cents = [
        f
        for f in out["geojson"]["features"]
        if f["properties"].get("geom_role") == "centroid"
    ]
    assert len(cents) >= 2


def test_faint_open_sea_ships_caught_with_sensitive_threshold():
    """Hulls at NIR≈0.07 (below old 0.10) must become contacts."""
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 96
    nir = np.full((h, w), 0.030, dtype=np.float64)
    # Three faint ships that 0.10 would miss
    nir[20:23, 15:20] = 0.072
    nir[40:43, 40:46] = 0.068
    nir[60:64, 55:62] = 0.085
    # Soft wake trail
    nir[41:42, 46:58] = 0.050

    out = detect_ships_optical_nir(
        {"nir": nir},
        [52.2, 26.3, 52.4, 26.5],
        confidence_min=0.08,
        collection="SENTINEL-2",
    )
    assert out["count"] >= 3, out["message"]
    assert out["overlay"] is not None


def test_water_pixels_below_threshold_are_not_ships():
    from app.services.optical_ship_detection import detect_ships_optical_nir

    h = w = 48
    nir = np.full((h, w), 0.025, dtype=np.float64)  # clear open-sea water
    out = detect_ships_optical_nir(
        {"nir": nir, "green": nir + 0.01, "blue": nir, "red": nir},
        [52.0, 26.0, 52.1, 26.1],
        confidence_min=0.08,
        collection="SENTINEL-2",
        nir_threshold=0.055,
    )
    assert out["count"] == 0


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
