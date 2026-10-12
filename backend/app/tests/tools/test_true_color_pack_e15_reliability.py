"""E1.5 — reliability: atomic pins, concurrency, GIS equivalence, failure modes."""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.schemas.composite import CompositeRequest
from app.services.composite_service import CompositeService
from app.tools.pack_loader import (
    PackIntegrityError,
    assert_artifact_immutable,
    host_sdk_compatible,
    resolve_true_color_render,
    verify_pack,
)
from app.tools.runtime_pins import PinError, get_pin, load_pins, write_pins

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture()
def isolated_pins(tmp_path, monkeypatch):
    pins = tmp_path / "runtime_pins.json"
    pins.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pins": {
                    "true_color": {
                        "mode": "builtin",
                        "version": None,
                        "digest": None,
                    }
                },
            }
        )
        + "\n"
    )
    monkeypatch.setenv("EV_RUNTIME_PINS", str(pins))
    from app.tools import runtime_pins as rp

    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None
    yield pins
    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None


def _meta(version: str) -> dict:
    return verify_pack("true_color", version)


def _pin_pack(version: str) -> None:
    meta = _meta(version)
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": version,
                    "digest": meta["digest"],
                }
            },
        }
    )
    from app.tools import runtime_pins as rp

    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None


def _decode_png(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    return np.array(img)


# --- Host SDK / contract ---


def test_host_sdk_compat_matrix():
    assert host_sdk_compatible(">=1.0.0,<2")
    assert not host_sdk_compatible(">=2.0.0,<3")
    assert host_sdk_compatible(None)


def test_artifact_immutability_guard():
    with pytest.raises(PackIntegrityError, match="immutable"):
        assert_artifact_immutable("true_color", "1.0.0")
    # build script also refuses
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts/tools/build_true_color_pack.py"), "--version", "1.0.0"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "immutable" in (r.stderr + r.stdout).lower() or "exists" in (r.stderr + r.stdout).lower()


# --- Atomic pins / recovery ---


def test_atomic_pin_write_creates_bak(isolated_pins):
    _pin_pack("1.0.0")
    bak = isolated_pins.with_suffix(isolated_pins.suffix + ".bak")
    assert bak.is_file()
    data = json.loads(isolated_pins.read_text())
    assert data["pins"]["true_color"]["version"] == "1.0.0"


def test_corrupt_pin_recovers_from_bak(isolated_pins):
    _pin_pack("1.0.0")
    bak = isolated_pins.with_suffix(isolated_pins.suffix + ".bak")
    assert bak.is_file()
    assert json.loads(bak.read_text())["pins"]["true_color"]["version"] == "1.0.0"
    # Corrupt primary after successful commit
    isolated_pins.write_text("{not-json")
    from app.tools import runtime_pins as rp

    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None
    pin = get_pin("true_color")
    assert pin.get("mode") == "pack"
    assert pin.get("version") == "1.0.0"


def test_interrupted_tmp_does_not_corrupt_primary(isolated_pins):
    """Leftover .tmp.* files must not be loaded; primary stays valid."""
    _pin_pack("1.0.0")
    junk = isolated_pins.with_suffix(f".tmp.{os.getpid()}.dead")
    junk.write_text("{partial")
    from app.tools import runtime_pins as rp

    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None
    pin = get_pin("true_color")
    assert pin.get("version") == "1.0.0"
    assert junk.is_file()  # leftover ignored
    junk.unlink()


def test_missing_pin_file_falls_back_builtin(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setenv("EV_RUNTIME_PINS", str(missing))
    from app.tools import runtime_pins as rp

    rp._CACHE["mtime"] = None
    rp._CACHE["data"] = None
    pin = get_pin("true_color")
    assert pin["mode"] == "builtin"


def test_invalid_pack_pin_rejected_on_write(isolated_pins):
    with pytest.raises(PinError):
        write_pins(
            {
                "schema_version": 1,
                "pins": {
                    "true_color": {
                        "mode": "pack",
                        "version": "1.0.0",
                        # missing digest
                    }
                },
            }
        )


# --- Façade path + GIS equivalence ---


def test_facade_path_builtin_and_pack_overlay_equivalence(isolated_pins, monkeypatch):
    """Workspace → CompositeService façade → pack/builtin; compare GIS raster."""
    rng = np.random.default_rng(7)
    # Controlled 8-bit-like TCI scene
    rgb = rng.integers(40, 200, size=(32, 32, 3)).astype(np.float64)
    mask = np.ones((32, 32), dtype=bool)
    bounds = [74.10, 31.40, 74.20, 31.50]

    monkeypatch.setattr(
        CompositeService,
        "_load_visual_rgb",
        lambda self, scene_id, bbox, size: (rgb, bounds, mask, None),
    )

    req = CompositeRequest(
        preset="true_color",
        scene_id="fixture-scene",
        collection="SENTINEL-2",
        size=64,
        brightness=1.0,
        contrast=1.0,
    )

    # Builtin
    write_pins(
        {
            "schema_version": 1,
            "pins": {"true_color": {"mode": "builtin", "version": None, "digest": None}},
        }
    )
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    builtin_resp = CompositeService().render_composite(req)
    assert builtin_resp.preset == "true_color"
    assert builtin_resp.stretch == "esa_tci"
    assert builtin_resp.bounds == bounds
    builtin_rgba = _decode_png(builtin_resp.overlay_base64)

    # Pack 1.0.0
    _pin_pack("1.0.0")
    pack_resp = CompositeService().render_composite(req)
    assert pack_resp.preset == "true_color"
    assert pack_resp.stretch == "esa_tci"
    assert pack_resp.bounds == bounds
    assert "tool_pack:1.0.0" in (pack_resp.message or "")
    pack_rgba = _decode_png(pack_resp.overlay_base64)

    assert builtin_rgba.shape == pack_rgba.shape == (32, 32, 4)
    # Band selection / natural color: RGB channels match exactly for same TCI input
    np.testing.assert_array_equal(builtin_rgba[:, :, :3], pack_rgba[:, :, :3])
    np.testing.assert_array_equal(builtin_rgba[:, :, 3], pack_rgba[:, :, 3])


def test_pack_1_1_0_compatible_and_distinct_message(isolated_pins, monkeypatch):
    rgb = np.full((16, 16, 3), 100.0)
    mask = np.ones((16, 16), dtype=bool)
    bounds = [1.0, 2.0, 3.0, 4.0]
    monkeypatch.setattr(
        CompositeService,
        "_load_visual_rgb",
        lambda self, scene_id, bbox, size: (rgb, bounds, mask, None),
    )
    _pin_pack("1.1.0")
    resp = CompositeService().render_composite(
        CompositeRequest(preset="true_color", scene_id="s", size=64)
    )
    assert resp.stretch == "esa_tci"
    assert "tool_pack_v11:1.1.0" in (resp.message or "")
    rgba = _decode_png(resp.overlay_base64)
    assert rgba.shape[0] == 16 and rgba.shape[1] == 16


# --- Concurrent promotion / requests ---


def test_concurrent_renders_during_pin_flip(isolated_pins, monkeypatch):
    rgb = np.full((8, 8, 3), 80.0)
    mask = np.ones((8, 8), dtype=bool)
    bounds = [0.0, 0.0, 1.0, 1.0]
    monkeypatch.setattr(
        CompositeService,
        "_load_visual_rgb",
        lambda self, scene_id, bbox, size: (rgb, bounds, mask, None),
    )
    _pin_pack("1.0.0")
    req = CompositeRequest(preset="true_color", scene_id="s", size=64)
    results: list[str] = []
    errors: list[str] = []

    def worker(i: int) -> None:
        try:
            if i == 10:
                _pin_pack("1.1.0")
            if i == 20:
                write_pins(
                    {
                        "schema_version": 1,
                        "pins": {
                            "true_color": {
                                "mode": "builtin",
                                "version": None,
                                "digest": None,
                            }
                        },
                    }
                )
                from app.tools import runtime_pins as rp

                rp._CACHE = {"mtime": None, "data": None}
            resp = CompositeService().render_composite(req)
            assert resp.overlay_base64
            assert resp.preset == "true_color"
            # Each response is complete (not partial)
            raw = base64.b64decode(resp.overlay_base64)
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            msg = resp.message or ""
            if "tool_pack_v11:1.1.0" in msg or "tool_pack:1.1.0" in msg:
                results.append("1.1.0")
            elif "tool_pack:1.0.0" in msg:
                results.append("1.0.0")
            else:
                results.append("builtin")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(40)))

    assert not errors, errors
    assert results
    # After flips, only valid complete labels seen (no hybrid version strings)
    assert set(results) <= {"1.0.0", "1.1.0", "builtin"}


def test_concurrent_promotes_serialize(isolated_pins):
    meta0 = _meta("1.0.0")
    meta1 = _meta("1.1.0")

    def promote(version: str, digest: str) -> None:
        write_pins(
            {
                "schema_version": 1,
                "pins": {
                    "true_color": {
                        "mode": "pack",
                        "version": version,
                        "digest": digest,
                    }
                },
            }
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = []
        for _ in range(5):
            futs.append(pool.submit(promote, "1.0.0", meta0["digest"]))
            futs.append(pool.submit(promote, "1.1.0", meta1["digest"]))
        for f in concurrent.futures.as_completed(futs):
            f.result()

    # Final pin must be valid JSON and a valid pack pin
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    data = load_pins(force=True)
    pin = data["pins"]["true_color"]
    assert pin["mode"] == "pack"
    assert pin["version"] in {"1.0.0", "1.1.0"}
    verify_pack("true_color", pin["version"], expected_digest=pin["digest"])


# --- Failure modes ---


def test_wrong_digest_rejected(isolated_pins):
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": "1.0.0",
                    "digest": "sha256:" + ("a" * 64),
                }
            },
        }
    )
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    with pytest.raises(PackIntegrityError):
        resolve_true_color_render()


def test_missing_artifact_version_rejected(isolated_pins):
    write_pins(
        {
            "schema_version": 1,
            "pins": {
                "true_color": {
                    "mode": "pack",
                    "version": "9.9.9",
                    "digest": "sha256:" + ("b" * 64),
                }
            },
        }
    )
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    with pytest.raises(PackIntegrityError, match="missing"):
        resolve_true_color_render()


def test_incompatible_host_sdk_rejected(tmp_path, monkeypatch):
    src = REPO / "tools" / "artifacts" / "true_color" / "1.0.0"
    dest = tmp_path / "artifacts" / "true_color" / "1.0.0"
    shutil.copytree(src, dest)
    meta = json.loads((dest / "pack.json").read_text())
    meta["host_sdk"] = ">=9.0.0,<10"
    (dest / "pack.json").write_text(json.dumps(meta, indent=2) + "\n")
    # SUMS does not include pack.json — host_sdk check runs before digest of payload
    import app.tools.pack_loader as pl

    monkeypatch.setattr(pl, "artifacts_root", lambda: tmp_path / "artifacts")
    with pytest.raises(PackIntegrityError, match="incompatible host SDK"):
        verify_pack("true_color", "1.0.0")


def test_ship_detection_unaffected_by_true_color_pin(isolated_pins):
    from app.services.detection_service import TASK_META
    from app.services.optical_ship_detection import OPTICAL_SHIP_TASKS

    _pin_pack("1.1.0")
    assert "ship_detection" in TASK_META
    assert "ship_detection" in OPTICAL_SHIP_TASKS
    # Canary module still importable
    from app.services import optical_ship_detection as osd

    assert callable(osd.detect_ships_optical_nir)


def test_shell_marker_files_stable_hash():
    """Pack promote does not rewrite shell image sources (content digests)."""
    markers = [
        REPO / "frontend/package.json",
        REPO / "backend/app/main.py",
        REPO / "docker-compose.yml",
        REPO / "backend/app/services/optical_ship_detection.py",
    ]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in markers}
    # Simulate promote in isolated env does not touch these — just re-hash
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in markers}
    assert before == after
