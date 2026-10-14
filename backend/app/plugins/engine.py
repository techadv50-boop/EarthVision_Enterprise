"""Plugin engine — reuse Tool Pack integrity / signature / immutable storage.

Does **not** modify frozen ``pack_ops.ALLOWED_TOOLS`` (true_color).
Plugins are separate IDs with install ≠ activate and default inactive registry state.

Does not grant filesystem / network / database permissions to plugins.
Backend entrypoints may only expose synthetic helpers declared in the pack.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.plugins.permissions import validate_permissions
from app.plugins.registry import (
    PluginRegistryError,
    get_plugin,
    list_plugins,
    load_registry,
    make_record,
    registry_path,
    upsert_plugin,
    validate_plugin_id,
    write_registry,
)
from app.plugins.slots import validate_slot
from app.tools.pack_loader import (
    PackIntegrityError,
    assert_artifact_immutable,
    host_sdk_compatible,
    load_pack_module,
    verify_pack,
)
from app.tools.pack_ops import PackOpsError, assert_production_trust_ready
from app.tools.pack_paths import artifacts_root, audit_log_path, pack_dir, staging_root
from app.tools.pack_signatures import (
    PackSignatureError,
    read_signature_file,
    verify_digest_signature,
)
from app.tools.runtime_pins import HOST_SDK_VERSION

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit(event: dict[str, Any]) -> None:
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {**event, "ts": _now(), "subsystem": "plugin_manager"}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _require_signature() -> bool:
    return os.environ.get("EV_PACK_REQUIRE_SIGNATURE", "1") != "0"


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                with open(fp, "rb") as f:
                    os.fsync(f.fileno())
            except OSError:
                pass


def _read_pack_meta(source_dir: Path) -> dict[str, Any]:
    pack_json = source_dir / "pack.json"
    if not pack_json.is_file():
        raise PackOpsError("pack.json missing")
    meta = json.loads(pack_json.read_text(encoding="utf-8"))
    plugin_id = str(meta.get("plugin_id") or meta.get("tool_id") or "")
    validate_plugin_id(plugin_id)
    if meta.get("tool_id") and str(meta["tool_id"]) != plugin_id:
        raise PackOpsError("pack.json tool_id must match plugin_id")
    # verify_pack expects tool_id field
    if meta.get("tool_id") != plugin_id:
        meta["tool_id"] = plugin_id
        pack_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def validate_plugin_package(source_dir: Path) -> dict[str, Any]:
    """Validate package layout, ID, host API, slot, permissions, integrity, signature."""
    if not source_dir.is_dir():
        raise PackOpsError(f"source missing: {source_dir}")
    try:
        meta = _read_pack_meta(source_dir)
        plugin_id = str(meta.get("plugin_id") or meta["tool_id"])
        version = str(meta["version"])
        validate_plugin_id(plugin_id)

        ui_meta_path = source_dir / "ui" / "tool-meta.json"
        if not ui_meta_path.is_file():
            raise PackOpsError("ui/tool-meta.json missing")
        ui_meta = json.loads(ui_meta_path.read_text(encoding="utf-8"))
        slot = str(ui_meta.get("frontend_slot") or meta.get("frontend_slot") or "")
        validate_slot(slot)
        perms = validate_permissions(
            list(ui_meta.get("permissions") or meta.get("permissions") or [])
        )

        req = str(meta.get("host_sdk") or meta.get("compatible_host_api") or "")
        if not host_sdk_compatible(req or None):
            raise PackOpsError(
                f"incompatible plugin host API: requires {req!r}, host is {HOST_SDK_VERSION}"
            )
    except (PluginRegistryError, ValueError) as exc:
        raise PackOpsError(str(exc)) from exc

    # Integrity via temporary artifacts layout (same as pack_ops)
    tmp_root = staging_root() / f"_plugin_validate_{time.time_ns()}"
    dest = tmp_root / plugin_id / version
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, dest)
    # Ensure tool_id in copied pack.json
    pj = dest / "pack.json"
    m2 = json.loads(pj.read_text(encoding="utf-8"))
    m2["tool_id"] = plugin_id
    m2["plugin_id"] = plugin_id
    pj.write_text(json.dumps(m2, indent=2) + "\n", encoding="utf-8")

    prev = os.environ.get("EV_ARTIFACTS_ROOT")
    os.environ["EV_ARTIFACTS_ROOT"] = str(tmp_root)
    try:
        verified = verify_pack(plugin_id, version)
        publisher_id = None
        if _require_signature():
            assert_production_trust_ready()
            sig = read_signature_file(dest)
            if sig["digest"] != verified["digest"]:
                raise PackSignatureError("SIGNATURE.json digest mismatch vs artifact")
            pub = verify_digest_signature(
                verified["digest"],
                sig["signature"],
                publisher_id=str(sig["publisher_id"]),
            )
            publisher_id = pub.get("id")
    except (PackIntegrityError, PackSignatureError, PackOpsError, PluginRegistryError, ValueError) as exc:
        raise PackOpsError(str(exc)) from exc
    finally:
        if prev is None:
            os.environ.pop("EV_ARTIFACTS_ROOT", None)
        else:
            os.environ["EV_ARTIFACTS_ROOT"] = prev
        shutil.rmtree(tmp_root, ignore_errors=True)

    result = {
        "ok": True,
        "action": "validate",
        "plugin_id": plugin_id,
        "name": ui_meta.get("label") or meta.get("name") or plugin_id,
        "description": ui_meta.get("description") or meta.get("description") or "",
        "version": version,
        "compatible_host_api": req,
        "backend_entrypoint": (meta.get("entry") or {}).get("backend") or "backend/plugin.py",
        "frontend_slot": slot,
        "permissions": perms,
        "digest": verified["digest"],
        "publisher_id": publisher_id,
        "host_api_version": HOST_SDK_VERSION,
    }
    _audit(result)
    return result


def register_from_validation(validated: dict[str, Any]) -> dict[str, Any]:
    """Register plugin metadata; remains inactive / not_installed until install."""
    existing = get_plugin(validated["plugin_id"])
    if existing and existing.get("installation_status") == "installed":
        if existing.get("version") == validated["version"]:
            raise PackOpsError(
                f"duplicate plugin version already installed: "
                f"{validated['plugin_id']}@{validated['version']}"
            )
    record = make_record(
        plugin_id=validated["plugin_id"],
        name=str(validated.get("name") or validated["plugin_id"]),
        description=str(validated.get("description") or ""),
        version=str(validated["version"]),
        compatible_host_api=str(validated.get("compatible_host_api") or f">={HOST_SDK_VERSION}"),
        backend_entrypoint=str(validated.get("backend_entrypoint") or "backend/plugin.py"),
        frontend_slot=str(validated["frontend_slot"]),
        permissions=list(validated.get("permissions") or []),
        digest=validated.get("digest"),
        previous_version=(existing or {}).get("version") if existing else None,
    )
    # Explicit default inactive
    record["activation_status"] = "inactive"
    record["installation_status"] = "not_installed"
    if existing and existing.get("installed_versions"):
        record["installed_versions"] = list(existing["installed_versions"])
    return upsert_plugin(record)


def install_plugin_from_dir(
    source_dir: Path,
    *,
    plugin_id: str,
    version: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "install":
        raise PackOpsError("refusing install: confirm must be exactly 'install'")
    validate_plugin_id(plugin_id)
    validated = validate_plugin_package(source_dir)
    if validated["plugin_id"] != plugin_id or validated["version"] != version:
        raise PackOpsError("plugin_id/version mismatch vs package")

    # Register if missing
    if not get_plugin(plugin_id):
        register_from_validation(validated)

    stage = staging_root() / f"plugin-{plugin_id}-{version}-{time.time_ns()}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, stage)
    # Normalize pack.json tool_id
    pj = stage / "pack.json"
    m = json.loads(pj.read_text(encoding="utf-8"))
    m["tool_id"] = plugin_id
    m["plugin_id"] = plugin_id
    pj.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")

    try:
        assert_artifact_immutable(plugin_id, version)
        final = pack_dir(plugin_id, version)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp_final = final.with_name(final.name + f".installing.{os.getpid()}")
        if tmp_final.exists():
            shutil.rmtree(tmp_final)
        shutil.copytree(stage, tmp_final)
        _fsync_tree(tmp_final)
        os.replace(tmp_final, final)
        _fsync_tree(final.parent)

        # Re-verify at final location
        verify_pack(plugin_id, version)

        data = load_registry(force=True)
        rec = data.setdefault("plugins", {}).get(plugin_id) or make_record(
            plugin_id=plugin_id,
            name=str(validated["name"]),
            description=str(validated["description"]),
            version=version,
            compatible_host_api=str(validated["compatible_host_api"]),
            backend_entrypoint=str(validated["backend_entrypoint"]),
            frontend_slot=str(validated["frontend_slot"]),
            permissions=list(validated["permissions"]),
            digest=validated["digest"],
        )
        versions = list(rec.get("installed_versions") or [])
        if version not in versions:
            versions.append(version)
        # Preserve an already-active pin on a *different* version; never auto-activate.
        prior_status = rec.get("activation_status") or "inactive"
        prior_version = rec.get("version")
        keep_active = prior_status == "active" and prior_version and prior_version != version
        rec.update(
            {
                "name": validated["name"],
                "description": validated["description"],
                "compatible_host_api": validated["compatible_host_api"],
                "backend_entrypoint": validated["backend_entrypoint"],
                "frontend_slot": validated["frontend_slot"],
                "permissions": validated["permissions"],
                "installation_status": "installed",
                "installed_versions": versions,
                "updated_at": _now(),
                "installed_by": actor,
                "latest_installed_version": version,
                "latest_installed_digest": validated["digest"],
            }
        )
        if keep_active:
            # Active version unchanged; new artifact is installed but inactive
            rec["activation_status"] = "active"
            rec["version"] = prior_version
        else:
            rec["version"] = version
            rec["digest"] = validated["digest"]
            rec["activation_status"] = "inactive"
        data["plugins"][plugin_id] = rec
        write_registry(data)

        result = {
            "action": "install",
            "ok": True,
            "plugin_id": plugin_id,
            "version": version,
            "digest": validated["digest"],
            "path": str(final),
            "actor": actor,
            "activation_status": rec["activation_status"],
            "installation_status": "installed",
        }
        _audit(result)
        return result
    except (PackIntegrityError, PackSignatureError, PackOpsError, PluginRegistryError, ValueError) as exc:
        _audit(
            {
                "action": "install",
                "ok": False,
                "plugin_id": plugin_id,
                "version": version,
                "actor": actor,
                "error": str(exc),
            }
        )
        raise PackOpsError(str(exc)) from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def activate_plugin(
    *,
    plugin_id: str,
    version: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "activate":
        raise PackOpsError("refusing activate: confirm must be exactly 'activate'")
    validate_plugin_id(plugin_id)
    if _require_signature():
        assert_production_trust_ready()

    rec = get_plugin(plugin_id)
    if not rec or rec.get("installation_status") != "installed":
        raise PackOpsError(f"plugin not installed: {plugin_id}")
    if version not in (rec.get("installed_versions") or []) and version != rec.get("version"):
        # Allow if artifact exists
        if not (pack_dir(plugin_id, version) / "pack.json").is_file():
            raise PackOpsError(f"version not installed: {plugin_id}@{version}")

    try:
        meta = verify_pack(plugin_id, version)
        if _require_signature():
            sig = read_signature_file(pack_dir(plugin_id, version))
            if sig["digest"] != meta["digest"]:
                raise PackSignatureError("SIGNATURE.json digest mismatch")
            verify_digest_signature(
                meta["digest"],
                sig["signature"],
                publisher_id=str(sig["publisher_id"]),
            )

        data = load_registry(force=True)
        cur = data["plugins"][plugin_id]
        previous_version = cur.get("version") if cur.get("activation_status") == "active" else cur.get(
            "previous_version"
        )
        if cur.get("activation_status") == "active" and cur.get("version") != version:
            previous_version = cur.get("version")
        cur["previous_version"] = previous_version
        cur["version"] = version
        cur["digest"] = meta["digest"]
        cur["activation_status"] = "active"
        cur["installation_status"] = "installed"
        cur["activated_by"] = actor
        cur["updated_at"] = _now()
        data["plugins"][plugin_id] = cur
        write_registry(data)

        result = {
            "action": "activate",
            "ok": True,
            "plugin_id": plugin_id,
            "version": version,
            "digest": meta["digest"],
            "previous_version": previous_version,
            "actor": actor,
            "frontend_slot": cur.get("frontend_slot"),
        }
        _audit(result)
        return result
    except (PackIntegrityError, PackSignatureError, PackOpsError) as exc:
        _audit(
            {
                "action": "activate",
                "ok": False,
                "plugin_id": plugin_id,
                "version": version,
                "actor": actor,
                "error": str(exc),
            }
        )
        raise PackOpsError(str(exc)) from exc


def disable_plugin(*, plugin_id: str, actor: str, confirm: str) -> dict[str, Any]:
    if confirm != "disable":
        raise PackOpsError("refusing disable: confirm must be exactly 'disable'")
    validate_plugin_id(plugin_id)
    data = load_registry(force=True)
    cur = data.get("plugins", {}).get(plugin_id)
    if not cur:
        raise PackOpsError(f"unknown plugin: {plugin_id}")
    cur["activation_status"] = "disabled"
    cur["updated_at"] = _now()
    cur["disabled_by"] = actor
    data["plugins"][plugin_id] = cur
    write_registry(data)
    result = {
        "action": "disable",
        "ok": True,
        "plugin_id": plugin_id,
        "actor": actor,
        "activation_status": "disabled",
    }
    _audit(result)
    return result


def rollback_plugin(
    *,
    plugin_id: str,
    to: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "rollback":
        raise PackOpsError("refusing rollback: confirm must be exactly 'rollback'")
    validate_plugin_id(plugin_id)
    data = load_registry(force=True)
    cur = data.get("plugins", {}).get(plugin_id)
    if not cur:
        raise PackOpsError(f"unknown plugin: {plugin_id}")

    previous = cur.get("version")
    if to == "inactive" or to == "builtin":
        cur["activation_status"] = "inactive"
        cur["previous_version"] = previous
        cur["updated_at"] = _now()
        cur["rolled_back_by"] = actor
        data["plugins"][plugin_id] = cur
        write_registry(data)
        result = {
            "action": "rollback",
            "ok": True,
            "plugin_id": plugin_id,
            "to": "inactive",
            "previous_version": previous,
            "actor": actor,
        }
        _audit(result)
        return result

    # Rollback to a prior installed version and activate it
    if not (pack_dir(plugin_id, to) / "pack.json").is_file():
        raise PackOpsError(f"rollback target missing: {plugin_id}@{to}")
    meta = verify_pack(plugin_id, to)
    cur["previous_version"] = previous
    cur["version"] = to
    cur["digest"] = meta["digest"]
    cur["activation_status"] = "active"
    cur["updated_at"] = _now()
    cur["rolled_back_by"] = actor
    data["plugins"][plugin_id] = cur
    write_registry(data)
    result = {
        "action": "rollback",
        "ok": True,
        "plugin_id": plugin_id,
        "to": to,
        "digest": meta["digest"],
        "previous_version": previous,
        "actor": actor,
    }
    _audit(result)
    return result


def extract_upload_zip(upload_bytes: bytes, dest_parent: Path) -> Path:
    """Extract a plugin zip safely (no path traversal). Returns pack root."""
    dest_parent.mkdir(parents=True, exist_ok=True)
    raw = dest_parent / f"upload-{time.time_ns()}"
    raw.mkdir()
    zip_path = raw / "plugin.zip"
    zip_path.write_bytes(upload_bytes)
    extract_to = raw / "extracted"
    extract_to.mkdir()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise PackOpsError(f"unsafe zip path: {name}")
            zf.extract(info, extract_to)
    # Find pack.json
    candidates = list(extract_to.rglob("pack.json"))
    if not candidates:
        raise PackOpsError("zip missing pack.json")
    # Prefer shallowest
    candidates.sort(key=lambda p: len(p.parts))
    return candidates[0].parent


def read_audit_history(limit: int = 100) -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("subsystem") == "plugin_manager" or ev.get("plugin_id"):
            events.append(ev)
        if len(events) >= limit:
            break
    return events


def run_synthetic(plugin_id: str) -> dict[str, Any]:
    """Invoke active plugin render() for synthetic/demo data only."""
    rec = get_plugin(plugin_id)
    if not rec or rec.get("activation_status") != "active":
        raise PackOpsError(f"plugin not active: {plugin_id}")
    if "synthetic_data" not in (rec.get("permissions") or []):
        raise PackOpsError("plugin lacks synthetic_data permission")
    version = str(rec["version"])
    digest = rec.get("digest")
    mod = load_pack_module(plugin_id, version, digest=digest)
    if not hasattr(mod, "render"):
        raise PackOpsError("plugin missing render()")
    # No host imagery — synthetic only
    out = mod.render(None)
    if not isinstance(out, dict):
        raise PackOpsError("plugin render() must return a dict")
    # Strip anything that looks like a path escape
    return {
        "plugin_id": plugin_id,
        "version": version,
        "frontend_slot": rec.get("frontend_slot"),
        "payload": out,
    }


def version_history(plugin_id: str) -> list[dict[str, Any]]:
    validate_plugin_id(plugin_id)
    rec = get_plugin(plugin_id)
    if not rec:
        return []
    root = artifacts_root() / plugin_id
    versions = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            pj = child / "pack.json"
            if pj.is_file():
                meta = json.loads(pj.read_text(encoding="utf-8"))
                versions.append(
                    {
                        "version": child.name,
                        "digest": meta.get("digest"),
                        "active": rec.get("activation_status") == "active"
                        and rec.get("version") == child.name,
                    }
                )
    return versions


def registry_snapshot() -> dict[str, Any]:
    data = load_registry(force=True)
    return {
        "schema_version": data.get("schema_version"),
        "host_api_version": data.get("host_api_version", HOST_SDK_VERSION),
        "registry_path": str(registry_path()),
        "artifacts_root": str(artifacts_root()),
        "plugins": list_plugins(),
        "supported_slots": sorted(__import__("app.plugins.slots", fromlist=["SUPPORTED_SLOTS"]).SUPPORTED_SLOTS),
    }
