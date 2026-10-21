#!/usr/bin/env python3
"""Rollback true_color pin to previous pack version or builtin fallback."""

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
    ap.add_argument(
        "--to",
        required=True,
        help="builtin | <version>  (must be a verified artifact unless builtin)",
    )
    args = ap.parse_args()
    if args.tool != "true_color":
        print("ERROR: E1 only supports true_color", file=sys.stderr)
        return 2

    data = load_pins(force=True)
    pins = data.setdefault("pins", {})
    current = pins.get(args.tool)

    if args.to == "builtin":
        pins[args.tool] = {
            "mode": "builtin",
            "version": None,
            "digest": None,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "previous": current,
            "note": "Verified in-tree CompositeService true_color path (not an independent artifact)",
        }
    else:
        try:
            meta = verify_pack(args.tool, args.to)
        except PackIntegrityError as exc:
            print(f"ROLLBACK REJECTED: {exc}", file=sys.stderr)
            return 1
        pins[args.tool] = {
            "mode": "pack",
            "version": args.to,
            "digest": meta["digest"],
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "previous": current,
        }

    write_pins(data)
    print(json.dumps({"rolled_back_to": pins[args.tool]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
