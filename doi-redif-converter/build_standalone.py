"""Build the native standalone executable (no browser)."""

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
        str(ROOT / "DOI_REDIF_Standalone.spec"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    for name in ("DOI_URL_REDIF_Standalone.exe", "DOI_URL_REDIF_Standalone"):
        candidate = dist / name
        if candidate.exists():
            print(f"\nBuilt: {candidate}")
            print("This is a native desktop app — it does NOT open a browser.")
            return 0

    print("Build finished but executable was not found in dist/", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
