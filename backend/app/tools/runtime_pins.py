"""Shared runtime pins for Tool Packs — atomic, validated, multi-worker safe."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from app.tools.pack_paths import pins_path, repo_root

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"mtime": None, "data": None}

# Host SDK semver declared for pack compatibility checks (1.2: optical scene/render/export)
HOST_SDK_VERSION = "1.3.0"

# Re-export for callers that imported pins_path/repo_root from here
__all__ = [
    "HOST_SDK_VERSION",
    "PinError",
    "get_pin",
    "load_pins",
    "pins_path",
    "repo_root",
    "write_pins",
]


class PinError(Exception):
    """Invalid or unrecoverable runtime pin state."""


def _validate_pins_doc(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PinError("pins document must be a JSON object")
    pins = data.get("pins")
    if pins is None:
        data["pins"] = {}
        pins = data["pins"]
    if not isinstance(pins, dict):
        raise PinError("pins.pins must be an object")
    for tool_id, pin in pins.items():
        if not isinstance(pin, dict):
            raise PinError(f"pin for {tool_id} must be an object")
        mode = (pin.get("mode") or "builtin").lower()
        if mode not in {"builtin", "pack"}:
            raise PinError(f"pin {tool_id}: invalid mode {mode!r}")
        if mode == "pack":
            if not pin.get("version"):
                raise PinError(f"pin {tool_id}: pack mode requires version")
            digest = pin.get("digest")
            if not digest or not str(digest).startswith("sha256:"):
                raise PinError(f"pin {tool_id}: pack mode requires sha256: digest")
    data.setdefault("schema_version", 1)
    return data


def _read_json_file(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise PinError(f"empty pin file: {path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PinError(f"corrupt pin JSON in {path}: {exc}") from exc
    return _validate_pins_doc(data)


def load_pins(*, force: bool = False) -> dict[str, Any]:
    """Load pins; recover from ``.bak`` if primary is missing/corrupt."""
    path = pins_path()
    bak = path.with_suffix(path.suffix + ".bak")
    with _LOCK:
        if not path.is_file():
            if bak.is_file():
                data = _read_json_file(bak)
                _CACHE["mtime"] = None
                _CACHE["data"] = data
                return data
            return {"schema_version": 1, "pins": {}}
        try:
            mtime = path.stat().st_mtime_ns
            if not force and _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
                return _CACHE["data"]  # type: ignore[return-value]
            data = _read_json_file(path)
            _CACHE["mtime"] = mtime
            _CACHE["data"] = data
            return data
        except PinError:
            if bak.is_file():
                data = _read_json_file(bak)
                _CACHE["mtime"] = None
                _CACHE["data"] = data
                return data
            raise


def _fsync_dir(dir_path: Path) -> None:
    flags = getattr(os, "O_RDONLY", 0)
    try:
        fd = os.open(str(dir_path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_pins(data: dict[str, Any]) -> None:
    """Atomically replace pins file after validation (fsync + os.replace).

    Uses an exclusive flock when available so concurrent promotes serialize.
    Keeps ``runtime_pins.json.bak`` as the last-known-good document.
    """
    data = _validate_pins_doc(dict(data))
    path = pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    tmp = path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    payload = json.dumps(data, indent=2) + "\n"

    lock_fd = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            import fcntl

            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass

        # Validate round-trip before committing
        _validate_pins_doc(json.loads(payload))

        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        # Keep prior primary as .bak until replace succeeds (rollback window).
        bak = path.with_suffix(path.suffix + ".bak")
        if path.is_file():
            try:
                bak.write_bytes(path.read_bytes())
            except OSError:
                pass

        os.replace(tmp, path)
        _fsync_dir(path.parent)

        # After a successful commit, mirror primary → .bak so post-commit
        # corruption of the primary can recover the last-known-good pin.
        try:
            bak.write_bytes(path.read_bytes())
            if bak.is_file():
                with open(bak, "rb") as bf:
                    os.fsync(bf.fileno())
        except OSError:
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        if lock_fd is not None:
            try:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            os.close(lock_fd)

    with _LOCK:
        _CACHE["mtime"] = None
        _CACHE["data"] = None


def get_pin(tool_id: str) -> dict[str, Any]:
    try:
        pins = load_pins().get("pins") or {}
    except PinError:
        # Unrecoverable primary+bak → safe documented fallback
        return {
            "mode": "builtin",
            "version": None,
            "digest": None,
            "degraded": True,
            "note": "pin file unavailable/corrupt; using builtin fallback",
        }
    pin = pins.get(tool_id)
    if not isinstance(pin, dict):
        return {"mode": "builtin", "version": None, "digest": None}
    return pin
