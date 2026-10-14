#!/usr/bin/env python3
"""Build immutable demo_hello plugin artifact under tools/plugins/demo_hello/artifacts/."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "plugins" / "demo_hello" / "src"
OUT_ROOT = ROOT / "tools" / "plugins" / "demo_hello" / "artifacts"

HASHED_RELS = ("backend/plugin.py", "ui/tool-meta.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1.0.0")
    args = ap.parse_args()
    version = args.version

    if not SRC.is_dir():
        print(f"ERROR: missing source {SRC}", file=sys.stderr)
        return 2

    dest = OUT_ROOT / version
    if dest.exists() and any(dest.iterdir()):
        print(f"ERROR: artifact immutable — refusing overwrite: {dest}", file=sys.stderr)
        return 1

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

    lines = [f"{sha256_file(dest / rel)}  {rel}" for rel in HASHED_RELS]
    sums_path = dest / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pack_digest = "sha256:" + sha256_file(sums_path)

    pack_meta = {
        "plugin_id": "demo_hello",
        "tool_id": "demo_hello",
        "name": "Demo Hello",
        "description": "Harmless synthetic demonstration plugin for Plugin Manager Stage P1.",
        "version": version,
        "digest": pack_digest,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_sdk": ">=1.0.0,<2",
        "compatible_host_api": ">=1.0.0,<2",
        "ui_strategy": "shell_facade",
        "frontend_slot": "right_analysis_panel",
        "permissions": [
            "synthetic_data",
            "ui.slot.right_analysis_panel",
            "host.sdk.read_meta",
        ],
        "entry": {"backend": "backend/plugin.py", "ui_meta": "ui/tool-meta.json"},
        "rollback_targets": ["inactive"],
    }
    (dest / "pack.json").write_text(json.dumps(pack_meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plugin_id": "demo_hello", "version": version, "digest": pack_digest, "path": str(dest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
