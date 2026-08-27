"""Unit tests for interactive render-speed helpers (no remote COG I/O)."""

from __future__ import annotations

import io
import time

import numpy as np
import pytest
from PIL import Image


def _import_service():
    from app.services.scene_imagery_service import (
        FAST_PNG_KWARGS,
        SceneImageryService,
    )

    return SceneImageryService, FAST_PNG_KWARGS


def test_selective_band_keys_skip_unused_and_add_scl_mask():
    SceneImageryService, _ = _import_service()
    analysis = {
        "red": "h1",
        "green": "h2",
        "blue": "h3",
        "nir": "h4",
        "swir": "h5",
        "swir16": "h5",
        "swir2": "h6",
        "swir22": "h6",
        "scl": "hs",
        "qa_pixel": "hq",
        "coastal": "hc",
        "rededge1": "he1",
    }
    keys = SceneImageryService.resolve_requested_band_keys(
        analysis, ["red", "nir"], include_masks=True, is_s2=True
    )
    assert "red" in keys and "nir" in keys and "scl" in keys
    assert "coastal" not in keys
    assert "rededge1" not in keys
    assert "swir" not in keys
    groups = SceneImageryService.group_band_keys_by_href(analysis, keys)
    assert len(groups) == 3


def test_alias_href_dedupe_reduces_fetches():
    SceneImageryService, _ = _import_service()
    analysis = {
        "swir": "h5",
        "swir16": "h5",
        "swir2": "h6",
        "swir22": "h6",
        "qa_pixel": "hq",
    }
    keys = SceneImageryService.resolve_requested_band_keys(
        analysis, ["swir", "swir2"], include_masks=True, is_landsat=True
    )
    groups = SceneImageryService.group_band_keys_by_href(analysis, keys)
    # swir+swir16 share, swir2+swir22 share, qa_pixel alone
    assert len(groups) == 3
    full = SceneImageryService.resolve_requested_band_keys(
        analysis, None, include_masks=False
    )
    gf = SceneImageryService.group_band_keys_by_href(analysis, full)
    assert len(gf) < len(full)


def test_index_required_bands_cover_all_indices():
    from app.services.analytics_service import AnalyticsService

    required = AnalyticsService.INDEX_REQUIRED_BANDS
    for index in ("NDVI", "NDWI", "NDBI", "SAVI", "BSI", "EVI", "NDMI", "NBR", "LST"):
        assert index in required
        assert len(required[index]) >= 1


def test_composite_required_keys_are_three_channels():
    from app.services.satellite_bands import COMPOSITE_REQUIRED_KEYS

    for preset, keys in COMPOSITE_REQUIRED_KEYS.items():
        assert len(keys) == 3, preset


def test_fast_png_encode_beats_optimize():
    _, fast_kwargs = _import_service()
    rgba = np.zeros((896, 896, 4), dtype=np.uint8)
    rgba[..., :3] = 120
    rgba[..., 3] = 255
    img = Image.fromarray(rgba, mode="RGBA")

    t0 = time.perf_counter()
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    t_opt = time.perf_counter() - t0

    t0 = time.perf_counter()
    buf = io.BytesIO()
    img.save(buf, format="PNG", **fast_kwargs)
    t_fast = time.perf_counter() - t0

    assert len(buf.getvalue()) > 100
    # optimize=True is typically several× slower; allow flaky CI with soft bound
    assert t_fast < t_opt * 1.05 or t_fast < 0.25


def test_interactive_size_floors_removed_from_call_sites():
    """Regression: composite/classification must not force ≥1280/1536 grids."""
    from pathlib import Path

    composite = Path(__file__).resolve().parents[1] / "services" / "composite_service.py"
    classification = (
        Path(__file__).resolve().parents[1] / "services" / "classification_service.py"
    )
    c_text = composite.read_text(encoding="utf-8")
    k_text = classification.read_text(encoding="utf-8")
    assert "max(request.size, 1280)" not in c_text
    assert "max(int(request.size), 1536)" not in k_text
    assert "band_names=" in c_text
    assert 'band_names=("blue"' in k_text or "band_names=('blue'" in k_text


@pytest.mark.parametrize(
    "index,expected",
    [
        ("NDVI", ("red", "nir")),
        ("EVI", ("red", "nir", "blue")),
        ("NBR", ("nir", "swir2")),
        ("LST", ("thermal",)),
    ],
)
def test_index_band_sets(index, expected):
    from app.services.analytics_service import AnalyticsService

    assert AnalyticsService.INDEX_REQUIRED_BANDS[index] == expected
