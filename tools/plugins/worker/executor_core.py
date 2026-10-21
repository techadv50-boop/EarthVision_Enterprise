"""Shared verify/load helpers used by parent and child (no threading)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


class ExecError(RuntimeError):
    """Plugin execution rejected or failed."""


def artifacts_root() -> Path:
    override = os.environ.get("EV_ARTIFACTS_ROOT")
    if not override:
        raise ExecError("EV_ARTIFACTS_ROOT not set")
    return Path(override)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_artifact(plugin_id: str, version: str, expected_digest: str) -> Path:
    root = artifacts_root() / plugin_id / version
    pack_json = root / "pack.json"
    sums = root / "SHA256SUMS"
    plugin = root / "backend" / "plugin.py"
    if not root.is_dir():
        raise ExecError(f"artifact missing: {plugin_id}@{version}")
    if root.is_symlink() or pack_json.is_symlink() or plugin.is_symlink():
        raise ExecError("symlinks not allowed in artifact")
    if not pack_json.is_file() or not sums.is_file() or not plugin.is_file():
        raise ExecError("incomplete artifact")

    meta = json.loads(pack_json.read_text(encoding="utf-8"))
    if meta.get("tool_id") != plugin_id and meta.get("plugin_id") != plugin_id:
        raise ExecError("pack.json plugin_id mismatch")
    if str(meta.get("version")) != version:
        raise ExecError("pack.json version mismatch")

    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, rel = parts[0], parts[-1]
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise ExecError(f"unsafe path in SHA256SUMS: {rel}")
        target = root / rel
        if not target.is_file() or target.is_symlink():
            raise ExecError(f"listed file missing or symlink: {rel}")
        if _sha256_file(target) != digest:
            raise ExecError(f"digest mismatch for {rel}")

    pack_digest = "sha256:" + _sha256_file(sums)
    if meta.get("digest") and meta["digest"] != pack_digest:
        raise ExecError("pack.json digest does not match SHA256SUMS")
    if pack_digest != expected_digest:
        raise ExecError("request digest does not match artifact")
    return root


def _load_module(plugin_id: str, version: str, root: Path) -> ModuleType:
    plugin = root / "backend" / "plugin.py"
    safe_v = version.replace(".", "_").replace("-", "_")
    safe_t = plugin_id.replace("-", "_")
    name = f"ev_worker_{safe_t}_{safe_v}_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(name, plugin)
    if spec is None or spec.loader is None:
        raise ExecError("cannot load plugin module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_and_render(
    plugin_id: str,
    version: str,
    root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    mod = _load_module(plugin_id, version, root)
    if not hasattr(mod, "render"):
        raise ExecError("plugin missing render()")
    out = mod.render(payload)
    if not isinstance(out, dict):
        raise ExecError("render() must return a dict")
    return out
