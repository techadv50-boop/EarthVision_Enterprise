#!/usr/bin/env python3
"""Export recoverable inventory of the legacy hardcoded toolbox catalog + manifest."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_frontend_catalog() -> list[dict]:
    text = (ROOT / "frontend/src/toolbox/catalog.ts").read_text(encoding="utf-8")
    # Lightweight extraction of toolbox ids/titles and tool ids/labels
    boxes: list[dict] = []
    for m in re.finditer(
        r"id:\s*'([^']+)',\s*title:\s*'([^']+)',\s*blurb:\s*'([^']*)',\s*tools:\s*\[(.*?)\]\s*,?\s*\}",
        text,
        re.S,
    ):
        tid, title, blurb, body = m.groups()
        tools = []
        for tm in re.finditer(r"id:\s*'([^']+)',\s*label:\s*'([^']+)'", body):
            tools.append({"id": tm.group(1), "label": tm.group(2)})
        boxes.append({"toolbox_id": tid, "title": title, "blurb": blurb, "tools": tools})
    return boxes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((ROOT / "tools/manifest.json").read_text(encoding="utf-8"))
    tools = manifest.get("tools") or []
    boxes = parse_frontend_catalog()
    out = {
        "schema_version": 1,
        "note": "Legacy inventory — not shown in plugin-first UI",
        "manifest_entry_count": len(tools) if isinstance(tools, list) else None,
        "frontend_toolbox_count": len(boxes),
        "frontend_tool_count": sum(len(b["tools"]) for b in boxes),
        "frontend_toolboxes": boxes,
        "manifest_tool_ids": [
            t.get("id") or t.get("tool_id") for t in tools if isinstance(t, dict)
        ]
        if isinstance(tools, list)
        else [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} boxes={out['frontend_toolbox_count']} tools={out['frontend_tool_count']} manifest={out['manifest_entry_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
