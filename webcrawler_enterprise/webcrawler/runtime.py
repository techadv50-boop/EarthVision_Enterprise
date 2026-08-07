"""Runtime path helpers for source and frozen (PyInstaller) builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Directory containing the executable (frozen) or project root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # webcrawler/runtime.py -> project root is parent of package
    return Path(__file__).resolve().parent.parent


def configure_runtime() -> Path:
    """
    Configure environment for standalone Windows packages.

    - Points Playwright at a locally bundled ms-playwright folder when present
      so end users do not need Python, VS Code, or `playwright install`.
    """
    base = app_base_dir()
    bundled = base / "ms-playwright"
    if bundled.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
    # Prefer no debug noise in packaged builds
    os.environ.setdefault("PYTHONUTF8", "1")
    return base
