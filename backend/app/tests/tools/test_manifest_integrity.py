"""Manifest integrity — catalog sync and Stage C PoC invariants."""

from __future__ import annotations

import re
from pathlib import Path

from app.tools.manifest_loader import approved_tools, load_manifest, manifest_path, tool_by_id


REPO = Path(__file__).resolve().parents[4]


def test_manifest_file_exists_and_loads():
    assert manifest_path().is_file()
    data = load_manifest()
    assert data["schema_version"] == 1
    assert data["deploy_branch"] == "cursor/scene-download-eye-5d6d"
    assert data["deployment_model"] == "full_app_only"
    assert "independent" not in (data.get("deployment_model") or "")


def test_manifest_matches_catalog_counts():
    catalog = REPO / "frontend" / "src" / "toolbox" / "catalog.ts"
    text = catalog.read_text(encoding="utf-8")
    tool_ids = re.findall(r"\{\s*id:\s*'([^']+)',\s*label:", text)
    data = load_manifest()
    assert len(tool_ids) == 151
    assert len(data["tools"]) == 151
    assert len({t for t in tool_ids}) == 148
    assert data["counts"]["catalog_entries"] == 151
    assert data["counts"]["unique_ids"] == 148


def test_true_color_is_approved_poc():
    data = load_manifest()
    assert data["poc"]["primary_tool"] == "true_color"
    tc = tool_by_id("true_color", toolbox="image")
    assert tc is not None
    assert tc["status"] == "approved"
    assert tc["approved_version"] == "1.0.0"
    assert tc["approved_commit"]
    assert tc["paths"]
    assert any("test_true_color_poc" in t for t in tc["tests"])
    approved = approved_tools()
    assert any(t["id"] == "true_color" for t in approved)


def test_ship_detection_is_unrelated_canary():
    data = load_manifest()
    assert data["poc"]["regression_canary"] == "ship_detection"
    ship = tool_by_id("ship_detection")
    assert ship is not None
    assert ship["toolbox"] == "ai"
    assert ship["regression_role"] == "canary"
    assert ship["toolbox"] != tool_by_id("true_color")["toolbox"]
    assert ship["tests"]
