"""USGS/Esri band recipes for True Color + false-color Image tools."""

from __future__ import annotations

from app.services.satellite_bands import COMPOSITE_BAND_CODES, COMPOSITE_REQUIRED_KEYS


def test_true_color_uses_red_green_blue_per_sensor():
    assert COMPOSITE_REQUIRED_KEYS["true_color"] == ("red", "green", "blue")
    assert COMPOSITE_BAND_CODES["true_color"]["SENTINEL-2"]["codes"] == "B04-B03-B02"
    assert COMPOSITE_BAND_CODES["true_color"]["LANDSAT-8"]["codes"] == "B4-B3-B2"
    assert COMPOSITE_BAND_CODES["true_color"]["LANDSAT-9"]["codes"] == "B4-B3-B2"
    assert COMPOSITE_BAND_CODES["true_color"]["LANDSAT-7"]["codes"] == "B3-B2-B1"


def test_false_color_infrared_is_nir_red_green():
    assert COMPOSITE_REQUIRED_KEYS["false_color_infrared"] == ("nir", "red", "green")
    assert COMPOSITE_BAND_CODES["false_color_infrared"]["SENTINEL-2"]["codes"] == "B08-B04-B03"
    assert COMPOSITE_BAND_CODES["false_color_infrared"]["LANDSAT-8"]["codes"] == "B5-B4-B3"
    assert COMPOSITE_BAND_CODES["false_color_infrared"]["LANDSAT-9"]["codes"] == "B5-B4-B3"


def test_agriculture_urban_swir_match_usgs_esri_tables():
    # Agriculture 6-5-2 / B11-B08-B02
    assert COMPOSITE_REQUIRED_KEYS["false_color_agriculture"] == ("swir", "nir", "blue")
    assert COMPOSITE_BAND_CODES["false_color_agriculture"]["SENTINEL-2"]["codes"] == "B11-B08-B02"
    assert COMPOSITE_BAND_CODES["false_color_agriculture"]["LANDSAT-8"]["codes"] == "B6-B5-B2"

    # Urban 7-6-4 / B12-B11-B04
    assert COMPOSITE_REQUIRED_KEYS["false_color_urban"] == ("swir2", "swir", "red")
    assert COMPOSITE_BAND_CODES["false_color_urban"]["SENTINEL-2"]["codes"] == "B12-B11-B04"
    assert COMPOSITE_BAND_CODES["false_color_urban"]["LANDSAT-8"]["codes"] == "B7-B6-B4"

    # SWIR 7-5-4 / B12-B08-B04
    assert COMPOSITE_REQUIRED_KEYS["swir_composite"] == ("swir2", "nir", "red")
    assert COMPOSITE_BAND_CODES["swir_composite"]["SENTINEL-2"]["codes"] == "B12-B08-B04"
    assert COMPOSITE_BAND_CODES["swir_composite"]["LANDSAT-8"]["codes"] == "B7-B5-B4"
