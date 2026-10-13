#!/usr/bin/env python3
"""Sign a Tool Pack digest with an Ed25519 publisher private key (dev/preview)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools.pack_loader import verify_pack  # noqa: E402
from app.tools.pack_signatures import sign_digest, write_signature_file  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tool", default="true_color")
    ap.add_argument("--version", required=True)
    ap.add_argument("--publisher-id", required=True)
    ap.add_argument("--private-key-file", required=True)
    args = ap.parse_args()

    priv = Path(args.private_key_file).read_text(encoding="utf-8").strip()
    meta = verify_pack(args.tool, args.version)
    sig = sign_digest(meta["digest"], priv)
    from app.tools.pack_paths import pack_dir

    path = write_signature_file(
        pack_dir(args.tool, args.version),
        digest=meta["digest"],
        signature=sig,
        publisher_id=args.publisher_id,
    )
    print(f"SIGNED {args.tool}@{args.version} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
