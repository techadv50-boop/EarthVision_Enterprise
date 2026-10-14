"""Persistent plugin registry (install ≠ activate; default inactive)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.plugins.permissions import validate_permissions
from app.plugins.slots import validate_slot
from app.tools.pack_paths import tool_packs_root
from app.tools.runtime_pins import HOST_SDK_VERSION

_LOCK = threading.RLock()

PLUGIN_ID_RE = __import__("re").compile(r"^[a-z][a-z0-9_]{1,63}$")

# Frozen legacy tools — never registerable as plugins.
LEGACY_FROZEN_IDS = frozenset({"true_color", "ship_detection"})


class PluginRegistryError(Exception):
    """Invalid registry state or plugin metadata."""


def registry_path() -> Path:
    override = os.environ.get("EV_PLUGIN_REGISTRY")
    if override:
        return Path(override)
    return tool_packs_root() / "plugin_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_doc() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "host_api_version": HOST_SDK_VERSION,
        "notes": "Plugin registry. Default activation_status=inactive for every new plugin.",
        "plugins": {},
    }


def load_registry(*, force: bool = False) -> dict[str, Any]:
    path = registry_path()
    if not path.is_file():
        doc = _empty_doc()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_registry(doc)
        return doc
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PluginRegistryError("registry must be a JSON object")
    data.setdefault("schema_version", 1)
    data.setdefault("host_api_version", HOST_SDK_VERSION)
    data.setdefault("plugins", {})
    if not isinstance(data["plugins"], dict):
        raise PluginRegistryError("plugins must be an object")
    return data


def write_registry(data: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with _LOCK:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


def validate_plugin_id(plugin_id: str) -> str:
    if plugin_id in LEGACY_FROZEN_IDS:
        raise PluginRegistryError(
            f"plugin_id {plugin_id!r} is a frozen legacy tool — not registerable as a plugin"
        )
    if not PLUGIN_ID_RE.match(plugin_id or ""):
        raise PluginRegistryError(
            "invalid plugin_id: must match ^[a-z][a-z0-9_]{1,63}$"
        )
    return plugin_id


def make_record(
    *,
    plugin_id: str,
    name: str,
    description: str,
    version: str,
    compatible_host_api: str,
    backend_entrypoint: str,
    frontend_slot: str,
    permissions: list[str],
    digest: str | None = None,
    previous_version: str | None = None,
) -> dict[str, Any]:
    validate_plugin_id(plugin_id)
    slot = validate_slot(frontend_slot)
    perms = validate_permissions(permissions)
    return {
        "plugin_id": plugin_id,
        "name": name,
        "description": description,
        "version": version,
        "compatible_host_api": compatible_host_api,
        "backend_entrypoint": backend_entrypoint or "backend/plugin.py",
        "frontend_slot": slot,
        "permissions": perms,
        "installation_status": "not_installed",
        "activation_status": "inactive",
        "previous_version": previous_version,
        "digest": digest,
        "installed_versions": [],
        "updated_at": _now(),
    }


def upsert_plugin(record: dict[str, Any]) -> dict[str, Any]:
    validate_plugin_id(str(record["plugin_id"]))
    validate_slot(str(record.get("frontend_slot")))
    validate_permissions(list(record.get("permissions") or []))
    with _LOCK:
        data = load_registry(force=True)
        plugins = data.setdefault("plugins", {})
        pid = record["plugin_id"]
        if pid in plugins and plugins[pid].get("installation_status") == "installed":
            # Preserve install/activate state unless caller overwrites explicitly
            existing = plugins[pid]
            record.setdefault("installation_status", existing.get("installation_status"))
            record.setdefault("activation_status", existing.get("activation_status", "inactive"))
            record.setdefault("installed_versions", existing.get("installed_versions") or [])
            record.setdefault("previous_version", existing.get("previous_version"))
        record["updated_at"] = _now()
        # New plugins always default inactive unless activation_status already set to inactive
        if record.get("activation_status") not in {"inactive", "active", "disabled"}:
            record["activation_status"] = "inactive"
        plugins[pid] = record
        write_registry(data)
        return record


def get_plugin(plugin_id: str) -> dict[str, Any] | None:
    data = load_registry()
    return (data.get("plugins") or {}).get(plugin_id)


def list_plugins() -> list[dict[str, Any]]:
    data = load_registry()
    return list((data.get("plugins") or {}).values())


def list_active_for_slot(slot: str | None = None) -> list[dict[str, Any]]:
    out = []
    for p in list_plugins():
        if p.get("activation_status") != "active":
            continue
        if p.get("installation_status") != "installed":
            continue
        if slot and p.get("frontend_slot") != slot:
            continue
        out.append(p)
    return out
