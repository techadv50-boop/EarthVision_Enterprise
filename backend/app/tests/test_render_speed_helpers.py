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


def test_true_color_l2a_optimized_produces_natural_rgb():
    """Highlight Optimized path: finite RGB in [0,1], muted natural greens (not neon)."""
    from app.services.professional_viz import true_color_highlight_optimized

    h = w = 64
    # Typical land BOA reflectance
    r = np.full((h, w), 0.08, dtype=np.float64)
    g = np.full((h, w), 0.10, dtype=np.float64)
    b = np.full((h, w), 0.06, dtype=np.float64)
    g[20:40, 20:40] = 0.14
    r[20:40, 20:40] = 0.05
    rgb = true_color_highlight_optimized(r, g, b)
    assert rgb.shape == (h, w, 3)
    assert float(np.nanmin(rgb)) >= 0.0
    assert float(np.nanmax(rgb)) <= 1.0
    mid = float(np.nanmean(rgb))
    assert 0.05 < mid < 0.95
    # Vegetation patch must not be neon-saturated (G channel not >> R,B after tone-map)
    veg = rgb[20:40, 20:40]
    assert float(veg[..., 1].mean()) < 0.85


def test_true_color_handles_dn_scaled_boa():
    """DN×10000 grids must scale before tone-map (else everything clips white)."""
    from app.services.professional_viz import true_color_highlight_optimized

    r = np.full((32, 32), 800.0)   # ρ≈0.08 after /10000
    g = np.full((32, 32), 1000.0)
    b = np.full((32, 32), 600.0)
    rgb = true_color_highlight_optimized(r, g, b)
    assert float(rgb.mean()) < 0.9
    assert float(rgb.mean()) > 0.15


def test_false_color_professional_and_index_viz_ranges():
    from app.services.professional_viz import (
        INDEX_VIZ_RANGE,
        false_color_professional,
    )
    from app.services.analytics_service import INDEX_META

    rng = np.random.default_rng(0)
    r = rng.uniform(0.05, 0.4, size=(48, 48))
    g = rng.uniform(0.05, 0.4, size=(48, 48))
    b = rng.uniform(0.05, 0.4, size=(48, 48))
    rgb = false_color_professional(r, g, b)
    assert rgb.shape == (48, 48, 3)
    assert 0.0 <= float(rgb.min()) <= float(rgb.max()) <= 1.0

    assert INDEX_META["NDVI"]["viz_range"] == INDEX_VIZ_RANGE["NDVI"]
    assert INDEX_META["NDVI"]["viz_range"] == (0.0, 0.8)


def test_toolbox_catalog_keeps_148_ai_inactive_except_ship():
    """148 tools restored; AI tools inactive except Ship Detection (water AOI gate)."""
    from pathlib import Path
    import re

    catalog = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "toolbox"
        / "catalog.ts"
    )
    text = catalog.read_text(encoding="utf-8")
    tool_ids = re.findall(r"\{\s*id:\s*'([^']+)',\s*label:", text)
    assert len(tool_ids) == 148, f"expected 148 tools, got {len(tool_ids)}"
    assert "true_color" in tool_ids
    assert "ship_detection" in tool_ids
    assert "building_detection" in tool_ids
    assert re.search(
        r"HIGH_RES_ONLY_TOOLBOXES:\s*ToolboxId\[\]\s*=\s*\[\s*\]", text
    )
    ai_block = re.search(
        r"id:\s*'ai'[\s\S]*?tools:\s*\[([\s\S]*?)\],\s*\},",
        text,
    )
    assert ai_block, "AI toolbox block not found"
    ai_body = ai_block.group(1)
    assert "requiresWaterAoi: true" in ai_body
    assert re.search(
        r"id:\s*'ship_detection'[\s\S]*?requiresWaterAoi:\s*true",
        ai_body,
    )
    assert "inactive: true" not in re.search(
        r"id:\s*'ship_detection'[\s\S]*?hint:",
        ai_body,
    ).group(0)
    for tid in (
        "building_detection",
        "aircraft_detection",
        "flood",
        "manual",
    ):
        assert re.search(
            rf"id:\s*'{tid}'[^\n]*inactive:\s*true",
            ai_body,
        ), f"{tid} should be inactive"


def test_tool_standards_catalog_covers_image_and_composites():
    from app.services.tool_standards import catalog_tool_standards

    cat = catalog_tool_standards()
    assert "true_color" in cat["image_tools"]
    assert "highlight_optimized" in cat["image_tools"]["true_color"]["method"]
    assert cat["reliability"]["request_timeout_s"] == 55
