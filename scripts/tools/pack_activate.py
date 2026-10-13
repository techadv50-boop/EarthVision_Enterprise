#!/usr/bin/env python3
"""Activate an already-installed Tool Pack (atomic pin). Separate approval from install."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools.pack_ops import PackOpsError, activate_pack, ensure_default_pins  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tool", default="true_color")
    ap.add_argument("--version", required=True)
    ap.add_argument("--actor", default="ops")
    ap.add_argument("--confirm", required=True, help="Must be exactly: activate")
    args = ap.parse_args()

    ensure_default_pins()
    try:
        result = activate_pack(
            tool_id=args.tool,
            version=args.version,
            actor=args.actor,
            confirm=args.confirm,
        )
    except PackOpsError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
