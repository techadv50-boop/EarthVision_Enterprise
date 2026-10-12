"""Shared runtime pins for Tool Packs — all workers read the same file."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def pins_path() -> Path:
    override = os.environ.get("EV_RUNTIME_PINS")
    if override:
        return Path(override)
    return repo_root() / "tools" / "runtime_pins.json"


def load_pins(*, force: bool = False) -> dict[str, Any]:
    path = pins_path()
    with _LOCK:
        if not path.is_file():
            return {"schema_version": 1, "pins": {}}
        mtime = path.stat().st_mtime_ns
        if not force and _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
            return _CACHE["data"]  # type: ignore[return-value]
        data = json.loads(path.read_text(encoding="utf-8"))
        _CACHE["mtime"] = mtime
        _CACHE["data"] = data
        return data


def write_pins(data: dict[str, Any]) -> None:
    path = pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    with _LOCK:
        _CACHE["mtime"] = None
        _CACHE["data"] = None


def get_pin(tool_id: str) -> dict[str, Any]:
    pins = load_pins().get("pins") or {}
    pin = pins.get(tool_id)
    if not isinstance(pin, dict):
        return {"mode": "builtin", "version": None, "digest": None}
    return pin
