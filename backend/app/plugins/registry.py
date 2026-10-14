"""Persistent plugin registry (install ≠ activate; default inactive).

Cross-worker safety: advisory file lock + atomic rename. Each mutation
re-reads the registry under the lock so concurrent Uvicorn workers cannot
clobber each other's updates.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.plugins.permissions import validate_permissions
from app.plugins.slots import validate_slot
from app.tools.pack_paths import tool_packs_root
from app.tools.runtime_pins import HOST_SDK_VERSION

_THREAD_LOCK = threading.RLock()

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


def _lock_path() -> Path:
    return registry_path().with_suffix(".lock")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_doc() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "host_api_version": HOST_SDK_VERSION,
        "notes": "Plugin registry. Default activation_status=inactive for every new plugin.",
        "plugins": {},
    }


@contextmanager
def registry_lock() -> Iterator[None]:
    """Process-wide + cross-process lock for registry RMW.

    Fail closed if ``fcntl`` is unavailable or ``flock`` cannot be acquired —
    thread-only locking is insufficient across Uvicorn workers.
    """
    try:
        import fcntl
    except ImportError as exc:
        raise PluginRegistryError(
            "cross-process registry locking unavailable: fcntl module missing"
        ) from exc

    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = _lock_path()
    with _THREAD_LOCK:
        fh = open(lock_file, "a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise PluginRegistryError(
                    f"cross-process registry locking unavailable: flock failed ({exc})"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()


def _read_unlocked() -> dict[str, Any]:
    path = registry_path()
    if not path.is_file():
        return _empty_doc()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PluginRegistryError("registry must be a JSON object")
    data.setdefault("schema_version", 1)
    data.setdefault("host_api_version", HOST_SDK_VERSION)
    data.setdefault("plugins", {})
    if not isinstance(data["plugins"], dict):
        raise PluginRegistryError("plugins must be an object")
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def load_registry(*, force: bool = False) -> dict[str, Any]:
    with registry_lock():
        data = _read_unlocked()
        if not registry_path().is_file():
            _write_unlocked(data)
        return data


def write_registry(data: dict[str, Any]) -> None:
    with registry_lock():
        _write_unlocked(data)


def mutate_registry(mutator: Callable[[dict[str, Any]], Any]) -> Any:
    """Atomically read-modify-write the registry under the cross-process lock."""
    with registry_lock():
        data = _read_unlocked()
        result = mutator(data)
        _write_unlocked(data)
        return result


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

    def _mut(data: dict[str, Any]) -> dict[str, Any]:
        plugins = data.setdefault("plugins", {})
        pid = record["plugin_id"]
        if pid in plugins and plugins[pid].get("installation_status") == "installed":
            existing = plugins[pid]
            record.setdefault("installation_status", existing.get("installation_status"))
            record.setdefault("activation_status", existing.get("activation_status", "inactive"))
            record.setdefault("installed_versions", existing.get("installed_versions") or [])
            record.setdefault("previous_version", existing.get("previous_version"))
        record["updated_at"] = _now()
        if record.get("activation_status") not in {"inactive", "active", "disabled"}:
            record["activation_status"] = "inactive"
        plugins[pid] = record
        return record

    return mutate_registry(_mut)


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
