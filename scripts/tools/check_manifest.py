#!/usr/bin/env python3
"""Validate tools/manifest.json against the frontend toolbox catalog.

Exit 0 on success; non-zero on inconsistency.
Does not deploy or touch production.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "manifest.json"
CATALOG = ROOT / "frontend" / "src" / "toolbox" / "catalog.ts"


def catalog_entries() -> list[tuple[str, str]]:
    text = CATALOG.read_text(encoding="utf-8")
    return re.findall(r"\{\s*id:\s*'([^']+)'\s*,\s*label:\s*'((?:\\'|[^'])*)'", text)


def main() -> int:
    errors: list[str] = []
    if not MANIFEST.is_file():
        print(f"ERROR: missing {MANIFEST}", file=sys.stderr)
        return 2
    if not CATALOG.is_file():
        print(f"ERROR: missing {CATALOG}", file=sys.stderr)
        return 2

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tools = data.get("tools") or []
    cat = catalog_entries()

    if len(cat) != 151:
        errors.append(f"catalog entry count expected 151, got {len(cat)}")
    if len(tools) != len(cat):
        errors.append(f"manifest tools ({len(tools)}) != catalog entries ({len(cat)})")

    unique_ids = {t for t, _ in cat}
    if len(unique_ids) != 148:
        errors.append(f"unique catalog ids expected 148, got {len(unique_ids)}")

    counts = data.get("counts") or {}
    if counts.get("catalog_entries") != len(tools):
        errors.append("counts.catalog_entries mismatch")
    if counts.get("unique_ids") != len({t.get("id") for t in tools}):
        errors.append("counts.unique_ids mismatch")

    if data.get("deploy_branch") != "cursor/scene-download-eye-5d6d":
        errors.append("deploy_branch must remain cursor/scene-download-eye-5d6d")
    if data.get("deployment_model") != "full_app_only":
        errors.append("deployment_model must be full_app_only (honesty constraint)")

    # PoC invariants
    poc = data.get("poc") or {}
    if poc.get("primary_tool") != "true_color":
        errors.append("poc.primary_tool must be true_color")
    if poc.get("regression_canary") != "ship_detection":
        errors.append("poc.regression_canary must be ship_detection")

    tc = next((t for t in tools if t.get("id") == "true_color"), None)
    if not tc or tc.get("status") != "approved":
        errors.append("true_color must be status=approved in Stage C")
    if not tc or not tc.get("approved_version") or not tc.get("approved_commit"):
        errors.append("true_color must have approved_version and approved_commit")
    if not tc or not tc.get("tests") or not tc.get("paths"):
        errors.append("true_color must declare tests[] and paths[]")

    ship = next((t for t in tools if t.get("id") == "ship_detection"), None)
    if not ship or ship.get("regression_role") != "canary":
        errors.append("ship_detection must be regression canary")
    if not ship or not ship.get("tests"):
        errors.append("ship_detection must declare tests[]")

    # Every catalog id present in manifest
    manifest_ids = [t.get("id") for t in tools]
    cat_ids = [t for t, _ in cat]
    if sorted(manifest_ids) != sorted(cat_ids):
        errors.append("manifest tool ids do not match catalog ids (multiset)")

    required_statuses = {"development", "testing", "approved", "deprecated"}
    for t in tools:
        if t.get("status") not in required_statuses:
            errors.append(f"invalid status for {t.get('registry_key')}: {t.get('status')}")
        if not t.get("registry_key") or not t.get("id") or not t.get("version"):
            errors.append(f"tool missing registry_key/id/version: {t}")

    if errors:
        print("MANIFEST CHECK FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        "MANIFEST OK:",
        f"entries={len(tools)} unique={len({t['id'] for t in tools})} "
        f"approved={sum(1 for t in tools if t['status']=='approved')} "
        f"canary=ship_detection deploy_branch={data.get('deploy_branch')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
