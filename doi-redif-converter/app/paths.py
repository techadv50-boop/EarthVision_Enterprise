"""Resolve app resource paths for source runs and frozen (PyInstaller) builds."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Return the directory that contains `static/`, `app/`, etc."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    return app_root() / "static"
