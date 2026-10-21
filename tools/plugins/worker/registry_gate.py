"""Authorize execution against the Host Shell plugin registry (active pin only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class RegistryGateError(RuntimeError):
    """Plugin not authorized for execution by current registry state."""


def registry_path() -> Path:
    override = os.environ.get("EV_PLUGIN_REGISTRY")
    if override:
        return Path(override)
    packs = os.environ.get("EV_TOOL_PACKS_ROOT")
    if packs:
        return Path(packs) / "plugin_registry.json"
    arts = os.environ.get("EV_ARTIFACTS_ROOT")
    if arts:
        p = Path(arts)
        if p.name == "artifacts":
            return p.parent / "plugin_registry.json"
    raise RegistryGateError("EV_PLUGIN_REGISTRY not configured")


def assert_active_pin(plugin_id: str, version: str, digest: str) -> dict[str, Any]:
    """Fail closed unless registry says this plugin/version/digest is active."""
    path = registry_path()
    if not path.is_file():
        raise RegistryGateError(f"plugin registry missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rec = (data.get("plugins") or {}).get(plugin_id)
    if not isinstance(rec, dict):
        raise RegistryGateError(f"unknown plugin: {plugin_id}")
    status = rec.get("activation_status")
    if status == "disabled":
        raise RegistryGateError(f"plugin disabled: {plugin_id}")
    if status != "active":
        raise RegistryGateError(
            f"plugin not active (status={status!r}): {plugin_id}"
        )
    if str(rec.get("version")) != version:
        raise RegistryGateError(
            f"stale or rolled-back version requested: want {rec.get('version')}, got {version}"
        )
    if str(rec.get("digest") or "") != digest:
        raise RegistryGateError("digest does not match currently active pin")
    if rec.get("installation_status") != "installed":
        raise RegistryGateError("plugin not installed")
    return rec
