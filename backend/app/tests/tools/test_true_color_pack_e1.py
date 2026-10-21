"""E0/E1 — true_color Tool Pack integrity, promote, rollback, rejection."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from app.schemas.composite import CompositeRequest
from app.services.composite_service import CompositeService
from app.tools.pack_loader import PackIntegrityError, resolve_true_color_render, verify_pack
from app.tools.runtime_pins import get_pin, load_pins, write_pins

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture()
def pins_backup(tmp_path, monkeypatch):
    pins_file = tmp_path / "runtime_pins.json"
    pins_file.write_text(
        json.dumps({"schema_version": 1, "pins": {"true_color": {"mode": "builtin"}}})
        + "\n"
    )
    monkeypatch.setenv("EV_RUNTIME_PINS", str(pins_file))
    # Clear pin cache
    from app.tools import runtime_pins

    runtime_pins._CACHE["mtime"] = None
    runtime_pins._CACHE["data"] = None
    yield pins_file
    runtime_pins._CACHE["mtime"] = None
    runtime_pins._CACHE["data"] = None


def _ensure_artifacts_built():
    art = REPO / "tools" / "artifacts" / "true_color"
    if not (art / "1.0.0" / "pack.json").is_file():
        pytest.skip("true_color@1.0.0 artifact not built yet")


def test_verify_pack_1_0_0():
    _ensure_artifacts_built()
    meta = verify_pack("true_color", "1.0.0")
    assert meta["tool_id"] == "true_color"
    assert meta["version"] == "1.0.0"
    assert str(meta["digest"]).startswith("sha256:")


def test_reject_tampered_plugin(tmp_path, monkeypatch):
    _ensure_artifacts_built()
    src = REPO / "tools" / "artifacts" / "true_color" / "1.0.0"
    dest_root = tmp_path / "artifacts" / "true_color" / "1.0.0"
    shutil.copytree(src, dest_root)
    plugin = dest_root / "backend" / "plugin.py"
    plugin.write_text(plugin.read_text() + "\n# tampered\n")

    import app.tools.pack_loader as pl

    monkeypatch.setattr(pl, "artifacts_root", lambda: tmp_path / "artifacts")
    with pytest.raises(PackIntegrityError, match="digest mismatch"):
        verify_pack("true_color", "1.0.0")


def test_builtin_pin_uses_in_tree(pins_backup):
    source, fn = resolve_true_color_render()
    assert source == "builtin"
    assert fn is None
    assert get_pin("true_color")["mode"] == "builtin"


def test_promote_and_render_via_pack(pins_backup, monkeypatch):
    _ensure_artifacts_built()
    meta = verify_pack("true_color", "1.0.0")
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": "1.0.0",
                    "digest": meta["digest"],
                }
            },
        }
    )
    from app.tools import runtime_pins

    runtime_pins._CACHE["mtime"] = None
    runtime_pins._CACHE["data"] = None

    source, fn = resolve_true_color_render()
    assert source == "pack:1.0.0"
    assert fn is not None

    # Synthetic host path: monkeypatch visual load inside CompositeService host port
    svc = CompositeService()
    rgb = np.full((8, 8, 3), 0.35)
    mask = np.ones((8, 8), dtype=bool)
    bounds = [74.0, 31.0, 74.1, 31.1]

    monkeypatch.setattr(
        svc,
        "_load_visual_rgb",
        lambda scene_id, bbox, size: (rgb, bounds, mask, None),
    )
    # Host port constructs its own CompositeService — patch class method used by port
    monkeypatch.setattr(
        CompositeService,
        "_load_visual_rgb",
        lambda self, scene_id, bbox, size: (rgb, bounds, mask, None),
    )

    resp = fn(CompositeRequest(preset="true_color", scene_id="s1", size=64))
    assert resp.preset == "true_color"
    assert resp.stretch == "esa_tci"
    assert "tool_pack:1.0.0" in (resp.message or "")


def test_wrong_digest_rejected(pins_backup):
    _ensure_artifacts_built()
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": "1.0.0",
                    "digest": "sha256:" + ("0" * 64),
                }
            },
        }
    )
    from app.tools import runtime_pins

    runtime_pins._CACHE["mtime"] = None
    runtime_pins._CACHE["data"] = None
    with pytest.raises(PackIntegrityError):
        resolve_true_color_render()


def test_rollback_to_builtin(pins_backup):
    _ensure_artifacts_built()
    meta = verify_pack("true_color", "1.0.0")
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": "1.0.0",
                    "digest": meta["digest"],
                }
            },
        }
    )
    from app.tools import runtime_pins

    runtime_pins._CACHE["mtime"] = None
    write_pins(
        {
            "schema_version": 1,
            "pins": {"true_color": {"mode": "builtin", "version": None, "digest": None}},
        }
    )
    runtime_pins._CACHE["mtime"] = None
    runtime_pins._CACHE["data"] = None
    source, fn = resolve_true_color_render()
    assert source == "builtin"
    assert fn is None
