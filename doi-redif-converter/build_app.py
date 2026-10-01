#!/usr/bin/env python3
"""Build a standalone DOI_REDIF_Converter executable with PyInstaller."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    dist = ROOT / "dist"
    build = ROOT / "build"
    for path in (dist, build):
        if path.exists():
            shutil.rmtree(path)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "DOI_REDIF_Converter.spec"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    exe_names = [
        "DOI_REDIF_Converter.exe",
        "DOI_REDIF_Converter",
    ]
    built = None
    for name in exe_names:
        candidate = dist / name
        if candidate.exists():
            built = candidate
            break

    if not built:
        print("Build finished but executable was not found in dist/", file=sys.stderr)
        return 1

    print(f"\nBuilt: {built}")
    print("Double-click that file to run the app (internet required for DOI lookup).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
