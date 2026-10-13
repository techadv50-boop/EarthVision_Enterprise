#!/usr/bin/env python3
"""Build an immutable true_color Tool Pack artifact under tools/artifacts/."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "packs" / "true_color" / "src"
OUT_ROOT = ROOT / "tools" / "artifacts" / "true_color"

# Files covered by integrity (not pack.json — pack.json carries the digest of SUMS)
HASHED_RELS = ("backend/plugin.py", "ui/tool-meta.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--png-quality", type=int, default=None)
    ap.add_argument("--message-tag", default=None)
    args = ap.parse_args()
    version = args.version

    if not SRC.is_dir():
        print(f"ERROR: missing source {SRC}", file=sys.stderr)
        return 2

    dest = OUT_ROOT / version
    if dest.exists() and any(dest.iterdir()):
        print(
            f"ERROR: artifact immutable — refusing overwrite: {dest}",
            file=sys.stderr,
        )
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
    if args.png_quality is not None:
        text = text.replace("PNG_QUALITY = 95", f"PNG_QUALITY = {int(args.png_quality)}")
    if args.message_tag is not None:
        text = text.replace('MESSAGE_TAG = "tool_pack"', f'MESSAGE_TAG = "{args.message_tag}"')
    plugin.write_text(text, encoding="utf-8")

    lines = [f"{sha256_file(dest / rel)}  {rel}" for rel in HASHED_RELS]
    sums_path = dest / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pack_digest = "sha256:" + sha256_file(sums_path)

    pack_meta = {
        "tool_id": "true_color",
        "version": version,
        "digest": pack_digest,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_sdk": ">=1.0.0,<2",
        "ui_strategy": "shell_facade",
        "entry": {"backend": "backend/plugin.py", "ui_meta": "ui/tool-meta.json"},
        "rollback_targets": ["builtin", "1.0.0"],
    }
    (dest / "pack.json").write_text(json.dumps(pack_meta, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "tool_id": "true_color",
                "version": version,
                "digest": pack_digest,
                "path": str(dest),
            }
        )
    )
    print(f"BUILT true_color@{version} digest={pack_digest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
