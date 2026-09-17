"""Nginx -T parser (same rules as the Ubuntu helper)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.ssh.client import bundled_ubuntu_scripts


def _helper():
    root = bundled_ubuntu_scripts()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import discover_apps  # type: ignore[import-not-found]

    return discover_apps


def parse_nginx_t(text: str) -> list[dict[str, Any]]:
    return _helper().parse_nginx_t(text)


def applications_from_servers(*args, **kwargs) -> list[dict[str, Any]]:
    return _helper().applications_from_servers(*args, **kwargs)


def classify_application(**kwargs) -> str:
    return _helper().classify_application(**kwargs)


def parse_files_dir(config_text: str) -> str | None:
    return _helper().parse_files_dir(config_text)


def helper_path() -> Path:
    return bundled_ubuntu_scripts() / "discover_apps.py"
