"""Optical FCC / spectral-index plugin packs + Host SDK 1.5 contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.plugins.host_sdk_contract import (
    HOST_SDK_METHODS,
    PLUGIN_HOST_SDK_VERSION,
    assert_method_allowed,
)
from app.plugins.permissions import validate_permissions

REPO = Path(__file__).resolve().parents[4]
OPTICAL_IDS = (
    "optical_false_color",
    "optical_ndvi",
    "optical_ndwi",
    "optical_ndbi",
    "optical_spectral_indices",
)


@pytest.mark.parametrize("plugin_id", OPTICAL_IDS)
def test_optical_plugin_artifact_layout(plugin_id: str):
    art = REPO / "tools" / "plugins" / plugin_id / "artifacts" / "1.0.0"
    if not art.is_dir():
        pytest.skip(f"{plugin_id} artifact missing — run build_optical_indices_plugins.py")
    pack = json.loads((art / "pack.json").read_text(encoding="utf-8"))
    meta = json.loads((art / "ui" / "tool-meta.json").read_text(encoding="utf-8"))
    assert pack["plugin_id"] == plugin_id
    assert pack["digest"].startswith("sha256:")
    assert meta["map_presentation"] == "processed_preview"
    assert meta["optical_only"] is True
    for sat in ("SENTINEL-2", "LANDSAT-7", "LANDSAT-8", "LANDSAT-9"):
        assert sat in meta["applicable_satellites"]
    perms = validate_permissions(meta["permissions"])
    if plugin_id == "optical_false_color":
        assert "host.sdk.render_composite" in perms
    else:
        assert "host.sdk.render_index" in perms


def test_host_sdk_15_composite_index_methods():
    assert PLUGIN_HOST_SDK_VERSION == "1.5.0"
    assert HOST_SDK_METHODS["host.renderComposite"] == "host.sdk.render_composite"
    assert HOST_SDK_METHODS["host.renderIndex"] == "host.sdk.render_index"
    assert_method_allowed(
        "host.renderComposite",
        ["host.sdk.render_composite"],
    )
    assert_method_allowed(
        "host.renderIndex",
        ["host.sdk.render_index"],
    )
    with pytest.raises(Exception):
        assert_method_allowed("host.renderComposite", ["host.sdk.render_true_color"])


def test_false_color_and_ndvi_backend_metadata():
    import importlib.util

    for plugin_id, key in (
        ("optical_false_color", "presets"),
        ("optical_ndvi", "indices"),
    ):
        path = (
            REPO
            / "tools"
            / "plugins"
            / plugin_id
            / "artifacts"
            / "1.0.0"
            / "backend"
            / "plugin.py"
        )
        if not path.is_file():
            pytest.skip("artifact missing")
        spec = importlib.util.spec_from_file_location(plugin_id, path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        out = mod.render({"family": "LANDSAT-8"})
        assert out["plugin_id"] == plugin_id
        assert out["optical_only"] is True
        assert key in out
