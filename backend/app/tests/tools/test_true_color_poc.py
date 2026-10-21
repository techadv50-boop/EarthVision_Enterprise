"""Stage C PoC — genuine automated protection for approved tool `true_color`.

These tests lock the Natural Color contract (bands, stretch recipe, encode path,
catalog wiring). They must fail if a later change silently regresses True Color.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import numpy as np
import pytest

from app.schemas.composite import CompositeRequest
from app.services.composite_service import COMPOSITE_PRESETS, CompositeService
from app.services.overlay_encode import encode_rgb_mask_overlay
from app.services.professional_viz import (
    PROFESSIONAL_COMPOSITE_NOTES,
    prepare_tci_display,
    true_color_highlight_optimized,
)
from app.services.satellite_bands import COMPOSITE_BAND_CODES, COMPOSITE_REQUIRED_KEYS
from app.tools.manifest_loader import tool_by_id

REPO = Path(__file__).resolve().parents[4]


def test_true_color_band_contract_locked():
    assert COMPOSITE_REQUIRED_KEYS["true_color"] == ("red", "green", "blue")
    assert COMPOSITE_PRESETS["true_color"]["keys"] == ("red", "green", "blue")
    assert COMPOSITE_BAND_CODES["true_color"]["SENTINEL-2"]["codes"] == "B04-B03-B02"
    assert COMPOSITE_BAND_CODES["true_color"]["LANDSAT-8"]["codes"] == "B4-B3-B2"
    assert COMPOSITE_BAND_CODES["true_color"]["LANDSAT-9"]["codes"] == "B4-B3-B2"
    assert "TCI" in PROFESSIONAL_COMPOSITE_NOTES["true_color"] or "highlight" in (
        PROFESSIONAL_COMPOSITE_NOTES["true_color"].lower()
    )


def test_true_color_highlight_optimized_is_natural_not_neon():
    """Highlight-optimized path must keep midtones natural (not blown neon)."""
    rng = np.random.default_rng(42)
    # Typical L2A land reflectance
    r = rng.uniform(0.04, 0.18, size=(64, 64))
    g = rng.uniform(0.05, 0.20, size=(64, 64))
    b = rng.uniform(0.03, 0.15, size=(64, 64))
    rgb = true_color_highlight_optimized(r, g, b)
    assert rgb.shape == (64, 64, 3)
    assert float(rgb.min()) >= 0.0
    assert float(rgb.max()) <= 1.0
    # Mean should stay in a displayable mid range for land ρ
    mean = float(rgb.mean())
    assert 0.15 <= mean <= 0.85


def test_true_color_tci_prepare_preserves_display_balance():
    # Simulate 8-bit TCI
    tci = np.zeros((32, 32, 3), dtype=np.float64)
    tci[..., 0] = 120
    tci[..., 1] = 110
    tci[..., 2] = 90
    out = prepare_tci_display(tci)
    assert out.shape == (32, 32, 3)
    assert 0.0 <= float(out.min()) <= float(out.max()) <= 1.0
    # Near 120/255 without aggressive re-stretch
    assert abs(float(out[..., 0].mean()) - (120 / 255)) < 0.02


def test_true_color_overlay_encode_uses_lossless_png_at_high_quality():
    rgb = np.clip(np.random.default_rng(0).random((48, 48, 3)), 0, 1)
    mask = np.ones((48, 48), dtype=bool)
    data, mime = encode_rgb_mask_overlay(rgb, mask, quality=95)
    assert mime == "image/png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # Round-trip size sanity
    assert len(data) > 100


def test_true_color_request_schema_allows_sharp_grid():
    req = CompositeRequest(preset="true_color", size=2048)
    assert req.preset == "true_color"
    assert req.size == 2048


def test_true_color_render_prefers_visual_tci_when_available(monkeypatch):
    """When visual RGB is available, render_composite must use esa_tci path."""
    svc = CompositeService()
    h, w = 16, 16
    fake_rgb = np.full((h, w, 3), 0.4, dtype=np.float64)
    fake_mask = np.ones((h, w), dtype=bool)
    bounds = [74.0, 31.0, 74.2, 31.2]

    monkeypatch.setattr(
        svc,
        "_load_visual_rgb",
        lambda scene_id, bbox, size: (fake_rgb, bounds, fake_mask, None),
    )

    # Ensure band path is NOT used when TCI succeeds
    def _boom(*_a, **_k):
        raise AssertionError("band path must not run when visual TCI is available")

    monkeypatch.setattr(svc, "_load_bands", _boom)

    resp = svc.render_composite(
        CompositeRequest(preset="true_color", scene_id="scene-poc", size=128)
    )
    assert resp.preset == "true_color"
    assert resp.stretch == "esa_tci"
    assert resp.bounds == bounds
    raw = base64.b64decode(resp.overlay_base64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_true_color_catalog_wiring_unchanged():
    catalog = (REPO / "frontend" / "src" / "toolbox" / "catalog.ts").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r"id:\s*'true_color'[\s\S]*?action:\s*\{\s*type:\s*'process'\s*,\s*op:\s*'true_color'",
        catalog,
    )
    # Workspace still routes true_color → runComposite('true_color')
    page = (REPO / "frontend" / "src" / "pages" / "WorkspacePage.tsx").read_text(
        encoding="utf-8"
    )
    assert "runComposite('true_color')" in page


def test_true_color_manifest_protection_metadata():
    tc = tool_by_id("true_color")
    assert tc is not None
    assert tc["status"] == "approved"
    assert "backend/app/services/composite_service.py" in tc["paths"]
    assert tc["approved_version"] == "1.0.0"
