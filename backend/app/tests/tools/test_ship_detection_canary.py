"""Stage C regression canary — unrelated to true_color (detection family).

If a True Color / shared-imagery change breaks Ship Detection wiring or the
optical NIR detector contract, these tests must fail so approved-tool work
cannot silently damage this canary.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from app.services.detection_service import TASK_META, DetectionService
from app.tools.manifest_loader import tool_by_id

REPO = Path(__file__).resolve().parents[4]


def test_ship_detection_catalog_not_inactive():
    catalog = (REPO / "frontend" / "src" / "toolbox" / "catalog.ts").read_text(
        encoding="utf-8"
    )
    m = re.search(
        r"id:\s*'ship_detection'([\s\S]*?)(?=\n\s*\{\s*id:|\n\s*\],)",
        catalog,
    )
    assert m, "ship_detection missing from catalog"
    block = m.group(0)
    assert "inactive: true" not in block
    assert "requiresWaterAoi: true" in block
    assert re.search(r"task:\s*'ship_detection'", block)


def test_ship_detection_registered_in_task_meta():
    assert "ship_detection" in TASK_META
    meta = TASK_META["ship_detection"]
    assert isinstance(meta, dict)
    # Must remain a real detection entry (label/algorithm present)
    assert meta.get("label") or meta.get("title") or meta.get("algorithm")


def test_ship_detection_optical_module_importable():
    from app.services import optical_ship_detection as osd

    assert "ship_detection" in osd.OPTICAL_SHIP_TASKS
    assert callable(osd.detect_ships_optical_nir)
    assert callable(osd.collection_is_optical_landsat_or_s2)
    assert osd.collection_is_optical_landsat_or_s2("SENTINEL-2")
    assert osd.collection_is_optical_landsat_or_s2("LANDSAT-8")
    assert not osd.collection_is_optical_landsat_or_s2("SENTINEL-1")


def test_detection_service_lists_ship_task():
    tasks = DetectionService().list_tasks()
    ids = {t.get("id") for t in tasks}
    assert "ship_detection" in ids


def test_ship_canary_manifest_role():
    ship = tool_by_id("ship_detection")
    assert ship is not None
    assert ship["regression_role"] == "canary"
    assert ship["toolbox"] == "ai"
    assert ship["status"] in {"testing", "approved", "development"}
    # Unrelated to image/true_color family
    assert ship["toolbox"] != "image"


def test_optical_ship_nir_threshold_helpers_stable():
    """Smoke NIR threshold helper with a tiny synthetic field."""
    from app.services.optical_ship_detection import _optimum_nir_threshold, _scale_nir_reflectance

    nir = np.full((32, 32), 0.03, dtype=np.float32)
    nir[10:12, 10:12] = 0.2
    search = np.ones((32, 32), dtype=bool)
    scaled = _scale_nir_reflectance(nir, "SENTINEL-2")
    assert scaled.shape == nir.shape
    thr = _optimum_nir_threshold(scaled, search)
    assert 0.01 <= float(thr) <= 0.5


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/services/optical_ship_detection.py",
        "backend/app/services/detection_service.py",
    ],
)
def test_ship_owned_paths_exist(path: str):
    assert (REPO / path).is_file()
