"""Load the Earth Vision tool manifest (repo-root tools/manifest.json)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    # backend/app/tools/manifest_loader.py → repo root
    return Path(__file__).resolve().parents[3]


def manifest_path() -> Path:
    override = os.environ.get("EV_TOOLS_MANIFEST")
    if override:
        return Path(override)
    return repo_root() / "tools" / "manifest.json"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        raise FileNotFoundError(f"Tool manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tools" not in data:
        raise ValueError("Invalid tool manifest: expected object with 'tools'")
    return data


def tool_by_id(tool_id: str, toolbox: str | None = None) -> dict[str, Any] | None:
    tools = load_manifest().get("tools") or []
    matches = [t for t in tools if t.get("id") == tool_id]
    if toolbox:
        matches = [t for t in matches if t.get("toolbox") == toolbox]
    return matches[0] if matches else None


def approved_tools() -> list[dict[str, Any]]:
    return [t for t in (load_manifest().get("tools") or []) if t.get("status") == "approved"]
