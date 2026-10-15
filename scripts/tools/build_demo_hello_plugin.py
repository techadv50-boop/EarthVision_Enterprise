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
    ap.add_argument("--force", action="store_true", help="Replace artifact (dev only)")
    args = ap.parse_args()
    version = args.version

    if not SRC.is_dir():
        print(f"ERROR: missing source {SRC}", file=sys.stderr)
        return 2

    dest = OUT_ROOT / version
    if dest.exists() and any(dest.iterdir()) and not args.force:
        print(f"ERROR: artifact immutable — refusing overwrite: {dest}", file=sys.stderr)
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

    syn = dest / "ui" / "synthetic.json"
    syn_obj = json.loads(syn.read_text(encoding="utf-8"))
    syn_obj["version"] = version
    if version == "1.0.0":
        syn_obj["message"] = (
            "Hello from the SATEYE Plugin Manager demonstration pack (P2B iframe)."
        )
        syn_obj["fe_theme"] = "sky"
    else:
        syn_obj["message"] = (
            f"Hello from Demo Hello {version} — independent frontend update (P2B)."
        )
        syn_obj["fe_theme"] = "emerald"
        syn_obj["note"] = (
            "Frontend panel.html/plugin.js differ from 1.0.0; Host Shell was not rebuilt."
        )
    syn.write_text(json.dumps(syn_obj, indent=2) + "\n", encoding="utf-8")

    # Version-specific FE styling (proves independent UI updates without Host rebuild)
    panel = dest / "ui" / "panel.html"
    html = panel.read_text(encoding="utf-8")
    if version != "1.0.0":
        html = html.replace("--accent: #0369a1;", "--accent: #047857;")
        html = html.replace("background: #e0f2fe;", "background: #d1fae5;")
        html = html.replace(
            "<title>Demo Hello Plugin</title>",
            f"<title>Demo Hello Plugin {version}</title>",
        )
    panel.write_text(html, encoding="utf-8")

    js = dest / "ui" / "plugin.js"
    js_text = js.read_text(encoding="utf-8")
    if version != "1.0.0":
        js_text = js_text.replace(
            'el("badge").textContent = "sandboxed iframe · " + (boot.version || "");',
            'el("badge").textContent = "sandboxed iframe · FE '
            + version
            + ' · " + (boot.version || "");',
        )
    js.write_text(js_text, encoding="utf-8")

    lines = [f"{sha256_file(dest / rel)}  {rel}" for rel in HASHED_RELS]
    sums_path = dest / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pack_digest = "sha256:" + sha256_file(sums_path)

    pack_meta = {
        "plugin_id": "demo_hello",
        "tool_id": "demo_hello",
        "name": "Demo Hello",
        "description": "Harmless sandboxed demonstration plugin for Plugin Manager Stage P2B.",
        "version": version,
        "digest": pack_digest,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_sdk": ">=1.0.0,<2",
        "compatible_host_api": ">=1.0.0,<2",
        "ui_strategy": "sandboxed_iframe",
        "frontend_slot": "right_analysis_panel",
        "permissions": [
            "synthetic_data",
            "ui.slot.right_analysis_panel",
            "host.sdk.read_meta",
        ],
        "entry": {
            "backend": "backend/plugin.py",
            "ui_meta": "ui/tool-meta.json",
            "ui_entry": "ui/panel.html",
        },
        "rollback_targets": ["inactive"] if version == "1.0.0" else ["inactive", "1.0.0"],
        "execution_model": "static_synthetic_only",
    }
    (dest / "pack.json").write_text(json.dumps(pack_meta, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plugin_id": "demo_hello",
                "version": version,
                "digest": pack_digest,
                "path": str(dest),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
