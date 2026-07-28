"""Disk cache for analysis overlay PNGs.

Tunnels like Serveo return HTTP 502 when JSON responses embed large base64
images (~400KB+). Store PNG bytes on disk and return a small overlay_url instead.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.core.config import get_settings


def _root() -> Path:
    path = get_settings().imagery_cache_dir / "result_overlays"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_overlay_png(png: bytes, prefix: str = "ov") -> str:
    """Persist PNG and return an opaque overlay id for URL serving."""
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "", prefix)[:24] or "ov"
    overlay_id = f"{safe_prefix}_{uuid.uuid4().hex[:16]}"
    path = _root() / f"{overlay_id}.png"
    path.write_bytes(png)
    return overlay_id


def overlay_url_for(overlay_id: str) -> str:
    return f"/api/v1/analytics/overlays/{overlay_id}.png"


def read_overlay_png(overlay_id: str) -> bytes | None:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "", overlay_id)[:80]
    if not safe:
        return None
    path = _root() / f"{safe}.png"
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    return None
