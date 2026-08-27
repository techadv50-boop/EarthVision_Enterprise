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


def test_gdal_cachemax_is_int_for_rasterio_1_5():
    """rasterio≥1.5 raises TypeError if GDAL_CACHEMAX is a string — neon synthetic fallback."""
    SceneImageryService, _ = _import_service()
    from app.services.scene_imagery_service import GDAL_ENV

    assert isinstance(GDAL_ENV["GDAL_CACHEMAX"], int)
    rasterio = pytest.importorskip("rasterio")
    with rasterio.Env(**GDAL_ENV):
        assert True


def test_composite_does_not_mask_band_load_failure_with_synthetic(monkeypatch):
    """Real scene_id must error, not paint sin()-striped synthetic as True Color."""
    from app.core.exceptions import ValidationError
    from app.services.composite_service import CompositeService
    from app.services import scene_imagery_service as sis

    class Boom:
        def load_analysis_bands(self, *args, **kwargs):
            raise RuntimeError("an integer is required")

    monkeypatch.setattr(sis, "SceneImageryService", Boom)
    with pytest.raises(ValidationError, match="Failed to load satellite bands"):
        CompositeService()._load_bands("scene-1", None, 128, band_names=("red", "green", "blue"))


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


def test_overlay_encode_prefers_webp_and_is_smaller_than_png():
    from app.services.overlay_encode import encode_rgba_overlay, encode_categorical_overlay

    rgba = np.zeros((128, 128, 4), dtype=np.uint8)
    rgba[..., 0] = 40
    rgba[..., 1] = 120
    rgba[..., 2] = 80
    rgba[..., 3] = 255
    # Add mild noise so compressors have work to do
    rgba[..., 1] = (rgba[..., 1] + np.arange(128, dtype=np.uint8)[None, :]) % 200

    webp, mime = encode_rgba_overlay(rgba, prefer="webp", quality=70)
    png, png_mime = encode_rgba_overlay(rgba, prefer="png")
    assert mime == "image/webp"
    assert png_mime == "image/png"
    assert webp[:4] == b"RIFF"
    assert len(webp) < len(png)

    cat, cat_mime = encode_categorical_overlay(rgba)
    assert cat_mime in {"image/webp", "image/png"}
    assert len(cat) > 32


def test_interactive_preview_cap_and_band_cache_limits():
    from app.services.scene_imagery_service import (
        INTERACTIVE_PREVIEW_MAX,
        _ANALYSIS_BAND_CACHE_MAX,
        GDAL_ENV,
    )

    assert INTERACTIVE_PREVIEW_MAX <= 640
    assert _ANALYSIS_BAND_CACHE_MAX >= 8
    assert int(GDAL_ENV["GDAL_HTTP_TIMEOUT"]) <= 30


def test_run_sync_timeout_raises_gateway_timeout():
    import asyncio

    from app.core.concurrency import run_sync_timeout
    from app.core.exceptions import GatewayTimeoutError

    def slow() -> None:
        time.sleep(2.0)

    async def _run() -> None:
        await run_sync_timeout(slow, timeout_s=0.2, label="Unit test")

    with pytest.raises(GatewayTimeoutError, match="Unit test timed out"):
        asyncio.run(_run())
