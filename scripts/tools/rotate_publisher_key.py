#!/usr/bin/env python3
"""Rotate an approved publisher key (offline / operator tool).

Adds a new enabled publisher entry and optionally disables an old id.
Does not write production secrets into the repository — operator supplies
the public key material.

Example:
  python3 scripts/tools/rotate_publisher_key.py \\
    --publishers tools/publishers/approved_publishers.preview.json \\
    --add-id ops-2026-10 --name "Ops Oct 2026" \\
    --public-key-file /secure/path/pub.b64 \\
    --disable-id preview-dev
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publishers", required=True, type=Path)
    ap.add_argument("--add-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--public-key-file", required=True, type=Path)
    ap.add_argument("--environment", default="preview")
    ap.add_argument("--disable-id", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.publishers.is_file():
        print(f"ERROR: missing {args.publishers}", file=sys.stderr)
        return 2
    pub = args.public_key_file.read_text(encoding="utf-8").strip()
    if len(pub) < 32:
        print("ERROR: public key too short", file=sys.stderr)
        return 2

    data = json.loads(args.publishers.read_text(encoding="utf-8"))
    pubs = list(data.get("publishers") or [])
    if any(str(p.get("id")) == args.add_id for p in pubs):
        print(f"ERROR: publisher id already exists: {args.add_id}", file=sys.stderr)
        return 1
    if args.disable_id:
        found = False
        for p in pubs:
            if str(p.get("id")) == args.disable_id:
                p["enabled"] = False
                p["disabled_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                found = True
        if not found:
            print(f"ERROR: disable target not found: {args.disable_id}", file=sys.stderr)
            return 1
    pubs.append(
        {
            "id": args.add_id,
            "name": args.name,
            "enabled": True,
            "environment": args.environment,
            "public_key": pub,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    data["publishers"] = pubs
    data["rotated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = json.dumps(data, indent=2) + "\n"
    if args.dry_run:
        print(text)
        return 0
    args.publishers.write_text(text, encoding="utf-8")
    print(f"OK: updated {args.publishers} (+{args.add_id}"
          f"{f', disabled {args.disable_id}' if args.disable_id else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
