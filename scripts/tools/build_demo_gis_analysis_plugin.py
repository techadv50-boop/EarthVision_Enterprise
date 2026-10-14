#!/usr/bin/env python3
"""Build immutable demo_gis_analysis plugin artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "plugins" / "demo_gis_analysis" / "src"
OUT_ROOT = ROOT / "tools" / "plugins" / "demo_gis_analysis" / "artifacts"

HASHED_RELS = (
    "backend/plugin.py",
    "ui/tool-meta.json",
    "ui/synthetic.json",
    "ui/panel.html",
    "ui/plugin.js",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    version = args.version
    if not SRC.is_dir():
        print(f"ERROR: missing {SRC}", file=sys.stderr)
        return 2
    dest = OUT_ROOT / version
    if dest.exists() and any(dest.iterdir()) and not args.force:
        print(f"ERROR: immutable {dest}", file=sys.stderr)
        return 1
    if dest.exists() and args.force:
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in HASHED_RELS:
        src_f = SRC / rel
        if not src_f.is_file():
            print(f"ERROR: missing {src_f}", file=sys.stderr)
            return 2
        out_f = dest / rel
        out_f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_f, out_f)

    plugin = dest / "backend" / "plugin.py"
    text = plugin.read_text(encoding="utf-8")
    text = text.replace('PACK_VERSION = "1.0.0"', f'PACK_VERSION = "{version}"')
    plugin.write_text(text, encoding="utf-8")

    syn = json.loads((dest / "ui" / "synthetic.json").read_text(encoding="utf-8"))
    syn["version"] = version
    (dest / "ui" / "synthetic.json").write_text(json.dumps(syn, indent=2) + "\n", encoding="utf-8")

    lines = [f"{sha256_file(dest / rel)}  {rel}" for rel in HASHED_RELS]
    sums = dest / "SHA256SUMS"
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pack_digest = "sha256:" + sha256_file(sums)
    pack_meta = {
        "plugin_id": "demo_gis_analysis",
        "tool_id": "demo_gis_analysis",
        "name": "Demo GIS Analysis",
        "description": "Practical GIS analysis demo using permitted Host SDK APIs only.",
        "version": version,
        "digest": pack_digest,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_sdk": ">=1.1.0,<2",
        "compatible_host_api": ">=1.1.0,<2",
        "ui_strategy": "sandboxed_iframe",
        "frontend_slot": "right_analysis_panel",
        "permissions": [
            "synthetic_data",
            "ui.slot.right_analysis_panel",
            "host.sdk.read_meta",
            "host.sdk.read_aoi",
            "host.sdk.set_analysis_result",
            "host.sdk.read_analysis_result",
        ],
        "entry": {
            "backend": "backend/plugin.py",
            "ui_meta": "ui/tool-meta.json",
            "ui_entry": "ui/panel.html",
        },
        "execution_model": "static_synthetic_only",
    }
    (dest / "pack.json").write_text(json.dumps(pack_meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plugin_id": "demo_gis_analysis", "version": version, "digest": pack_digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
