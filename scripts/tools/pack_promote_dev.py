#!/usr/bin/env python3
"""Promote a verified true_color pack pin in development (writes runtime_pins.json)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools.pack_loader import PackIntegrityError, verify_pack  # noqa: E402
from app.tools.runtime_pins import load_pins, write_pins  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default="true_color")
    ap.add_argument("--version", required=True)
    ap.add_argument("--allow-builtin", action="store_true")
    args = ap.parse_args()

    if args.tool != "true_color":
        print("ERROR: E1 only supports true_color", file=sys.stderr)
        return 2

    try:
        meta = verify_pack(args.tool, args.version)
    except PackIntegrityError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1

    data = load_pins(force=True)
    pins = data.setdefault("pins", {})
    prev = pins.get(args.tool)
    pins[args.tool] = {
        "mode": "pack",
        "version": args.version,
        "digest": meta["digest"],
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous": prev,
    }
    data["schema_version"] = 1
    write_pins(data)
    print(json.dumps({"promoted": pins[args.tool]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
