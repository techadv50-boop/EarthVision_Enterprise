#!/usr/bin/env python3
"""Install a signed Tool Pack into EV_ARTIFACTS_ROOT (does not activate)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools.pack_ops import PackOpsError, ensure_default_pins, install_pack_from_dir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tool", default="true_color")
    ap.add_argument("--version", required=True)
    ap.add_argument(
        "--source",
        default=None,
        help="Pack directory (defaults to repo tools/artifacts/<tool>/<version>)",
    )
    ap.add_argument("--actor", default="ops")
    ap.add_argument("--confirm", required=True, help="Must be exactly: install")
    args = ap.parse_args()

    ensure_default_pins()
    source = (
        Path(args.source)
        if args.source
        else ROOT / "tools" / "artifacts" / args.tool / args.version
    )
    try:
        result = install_pack_from_dir(
            source,
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
