"""Plugin engine — integrity / signature / immutable storage (Stage P1.1).

Trust boundary (see docs/PLUGIN_TRUST_BOUNDARY.md):
  - A permissions manifest is an *declaration allowlist*, NOT a sandbox.
  - Uploaded ``backend/plugin.py`` is NEVER imported or exec'd inside the
    privileged FastAPI / Uvicorn process.
  - Synthetic demo output is served only from integrity-covered static JSON.
  - Nontrivial plugin Python requires a separately reviewed worker/container
    isolation design (proposed in the trust-boundary doc) before in-process
    or out-of-process execution is enabled.
"""

from __future__ import annotations

import json
import os
import shutil
import time
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
    mutate_registry,
    registry_path,
    upsert_plugin,
    validate_plugin_id,
)
from app.plugins.slots import validate_slot
from app.plugins.staging import (
    load_staging_manifest,
    pack_root_path,
    require_validated_staging,
    stream_upload_to_staging,
    write_staging_manifest,
)
from app.tools.pack_loader import PackIntegrityError, assert_artifact_immutable, host_sdk_compatible, verify_pack, verify_pack_at
from app.tools.pack_ops import PackOpsError, assert_production_trust_ready
from app.tools.pack_paths import artifacts_root, audit_log_path, pack_dir
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


def _normalize_pack_json(source_dir: Path) -> dict[str, Any]:
    pack_json = source_dir / "pack.json"
    if not pack_json.is_file():
        raise PackOpsError("pack.json missing")
    meta = json.loads(pack_json.read_text(encoding="utf-8"))
    plugin_id = str(meta.get("plugin_id") or meta.get("tool_id") or "")
    validate_plugin_id(plugin_id)
    if meta.get("tool_id") and str(meta["tool_id"]) != plugin_id:
        raise PackOpsError("pack.json tool_id must match plugin_id")
    meta["tool_id"] = plugin_id
    meta["plugin_id"] = plugin_id
    pack_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def validate_plugin_package(source_dir: Path) -> dict[str, Any]:
    """Validate package layout, ID, host API, slot, permissions, integrity, signature.

    Does **not** mutate process-wide environment variables.
    Does **not** execute plugin Python.
    """
    if not source_dir.is_dir():
        raise PackOpsError(f"source missing: {source_dir}")
    try:
        meta = _normalize_pack_json(source_dir)
        plugin_id = str(meta["plugin_id"])
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

        # Static synthetic payload required for P1 demo-style plugins (no code exec).
        syn_path = source_dir / "ui" / "synthetic.json"
        if "synthetic_data" in perms and not syn_path.is_file():
            raise PackOpsError(
                "synthetic_data permission requires integrity-covered ui/synthetic.json "
                "(plugin Python is not executed in the API process)"
            )

        verified = verify_pack_at(source_dir, plugin_id, version)
        publisher_id = None
        if _require_signature():
            assert_production_trust_ready()
            sig = read_signature_file(source_dir)
            if sig["digest"] != verified["digest"]:
                raise PackSignatureError("SIGNATURE.json digest mismatch vs artifact")
            pub = verify_digest_signature(
                verified["digest"],
                sig["signature"],
                publisher_id=str(sig["publisher_id"]),
            )
            publisher_id = pub.get("id")
    except (PackIntegrityError, PackSignatureError, PluginRegistryError, ValueError) as exc:
        raise PackOpsError(str(exc)) from exc

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
        "execution_model": "static_synthetic_only",
    }
    _audit(result)
    return result


def validate_staging(staging_id: str) -> dict[str, Any]:
    """Validate a server-side staging pack and bind the digest to the staging ID."""
    meta = load_staging_manifest(staging_id)
    root = pack_root_path(staging_id)
    validated = validate_plugin_package(root)
    meta.update(
        {
            "validated": True,
            "digest": validated["digest"],
            "plugin_id": validated["plugin_id"],
            "version": validated["version"],
            "validated_at": _now(),
            "name": validated.get("name"),
            "frontend_slot": validated.get("frontend_slot"),
            "permissions": validated.get("permissions"),
            "compatible_host_api": validated.get("compatible_host_api"),
            "backend_entrypoint": validated.get("backend_entrypoint"),
            "description": validated.get("description"),
        }
    )
    write_staging_manifest(staging_id, meta)
    out = {**validated, "staging_id": staging_id}
    return out


def register_from_validation(validated: dict[str, Any]) -> dict[str, Any]:
    """Register plugin metadata; remains inactive / not_installed until install."""
    existing = get_plugin(validated["plugin_id"])
    if existing and existing.get("installation_status") == "installed":
        if validated["digest"] in {
            *(existing.get("installed_digests") or []),
            existing.get("digest"),
        }:
            raise PackOpsError(
                f"duplicate plugin digest already installed: {validated['digest']}"
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
    record["activation_status"] = "inactive"
    record["installation_status"] = "not_installed"
    if existing and existing.get("installed_versions"):
        record["installed_versions"] = list(existing["installed_versions"])
    return upsert_plugin(record)


def install_from_staging(
    *,
    staging_id: str,
    expected_digest: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    """Install only the previously validated staging artifact matching expected_digest."""
    if confirm != "install":
        raise PackOpsError("refusing install: confirm must be exactly 'install'")
    source_dir, stage_meta = require_validated_staging(
        staging_id, expected_digest=expected_digest
    )
    plugin_id = str(stage_meta["plugin_id"])
    version = str(stage_meta["version"])
    validate_plugin_id(plugin_id)

    # Re-validate at install time (TOCTOU) without env mutation.
    validated = validate_plugin_package(source_dir)
    if validated["digest"] != expected_digest:
        raise PackOpsError("digest changed since validation — refusing install")
    if validated["plugin_id"] != plugin_id or validated["version"] != version:
        raise PackOpsError("plugin_id/version mismatch vs staging")

    if not get_plugin(plugin_id):
        register_from_validation(validated)

    try:
        assert_artifact_immutable(plugin_id, version)
        final = pack_dir(plugin_id, version)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp_final = final.with_name(final.name + f".installing.{os.getpid()}.{time.time_ns()}")
        if tmp_final.exists():
            shutil.rmtree(tmp_final)
        shutil.copytree(source_dir, tmp_final, symlinks=False)
        _fsync_tree(tmp_final)
        try:
            os.replace(tmp_final, final)
        except OSError as exc:
            shutil.rmtree(tmp_final, ignore_errors=True)
            # Concurrent install won the race — treat as immutable collision.
            if final.is_dir() and any(final.iterdir()):
                raise PackOpsError(
                    f"artifact is immutable and already exists: {plugin_id}@{version}"
                ) from exc
            raise PackOpsError(f"install replace failed: {exc}") from exc
        _fsync_tree(final.parent)

        # Verify at final artifacts location (uses EV_ARTIFACTS_ROOT paths, no mutation)
        verify_pack(plugin_id, version, expected_digest=expected_digest)

        def _mut(data: dict[str, Any]) -> dict[str, Any]:
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
            digests = list(rec.get("installed_digests") or [])
            if validated["digest"] not in digests:
                digests.append(validated["digest"])
            prior_status = rec.get("activation_status") or "inactive"
            prior_version = rec.get("version")
            keep_active = (
                prior_status == "active" and prior_version and prior_version != version
            )
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
                    "installed_digests": digests,
                    "updated_at": _now(),
                    "installed_by": actor,
                    "latest_installed_version": version,
                    "latest_installed_digest": validated["digest"],
                }
            )
            if keep_active:
                rec["activation_status"] = "active"
                rec["version"] = prior_version
            else:
                rec["version"] = version
                rec["digest"] = validated["digest"]
                rec["activation_status"] = "inactive"
            data["plugins"][plugin_id] = rec
            return rec

        rec = mutate_registry(_mut)

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
            "staging_id": staging_id,
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

        def _mut(data: dict[str, Any]) -> dict[str, Any]:
            cur = data["plugins"][plugin_id]
            previous_version = cur.get("previous_version")
            if cur.get("activation_status") == "active" and cur.get("version") != version:
                previous_version = cur.get("version")
            elif cur.get("activation_status") == "active":
                previous_version = cur.get("previous_version")
            cur["previous_version"] = previous_version
            cur["version"] = version
            cur["digest"] = meta["digest"]
            cur["activation_status"] = "active"
            cur["installation_status"] = "installed"
            cur["activated_by"] = actor
            cur["updated_at"] = _now()
            data["plugins"][plugin_id] = cur
            return cur

        cur = mutate_registry(_mut)
        result = {
            "action": "activate",
            "ok": True,
            "plugin_id": plugin_id,
            "version": version,
            "digest": meta["digest"],
            "previous_version": cur.get("previous_version"),
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

    def _mut(data: dict[str, Any]) -> dict[str, Any]:
        cur = data.get("plugins", {}).get(plugin_id)
        if not cur:
            raise PackOpsError(f"unknown plugin: {plugin_id}")
        cur["activation_status"] = "disabled"
        cur["updated_at"] = _now()
        cur["disabled_by"] = actor
        data["plugins"][plugin_id] = cur
        return cur

    try:
        mutate_registry(_mut)
    except PackOpsError:
        raise
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

    def _mut(data: dict[str, Any]) -> dict[str, Any]:
        cur = data.get("plugins", {}).get(plugin_id)
        if not cur:
            raise PackOpsError(f"unknown plugin: {plugin_id}")
        previous = cur.get("version")
        if to in {"inactive", "builtin"}:
            cur["activation_status"] = "inactive"
            cur["previous_version"] = previous
            cur["updated_at"] = _now()
            cur["rolled_back_by"] = actor
            data["plugins"][plugin_id] = cur
            return {
                "action": "rollback",
                "ok": True,
                "plugin_id": plugin_id,
                "to": "inactive",
                "previous_version": previous,
                "actor": actor,
            }

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
        return {
            "action": "rollback",
            "ok": True,
            "plugin_id": plugin_id,
            "to": to,
            "digest": meta["digest"],
            "previous_version": previous,
            "actor": actor,
        }

    result = mutate_registry(_mut)
    _audit(result)
    return result


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
    """Serve integrity-covered static synthetic JSON — never exec plugin.py."""
    rec = get_plugin(plugin_id)
    if not rec or rec.get("activation_status") != "active":
        raise PackOpsError(f"plugin not active: {plugin_id}")
    if "synthetic_data" not in (rec.get("permissions") or []):
        raise PackOpsError("plugin lacks synthetic_data permission")
    version = str(rec["version"])
    digest = rec.get("digest")
    root = pack_dir(plugin_id, version)
    # Re-verify artifact; do not import backend/plugin.py
    verify_pack(plugin_id, version, expected_digest=digest)
    syn_path = root / "ui" / "synthetic.json"
    if not syn_path.is_file():
        raise PackOpsError("ui/synthetic.json missing (in-process plugin exec is disabled)")
    if syn_path.is_symlink():
        raise PackOpsError("symlinks not allowed")
    payload = json.loads(syn_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PackOpsError("synthetic.json must be a JSON object")
    return {
        "plugin_id": plugin_id,
        "version": version,
        "frontend_slot": rec.get("frontend_slot"),
        "execution_model": "static_synthetic_only",
        "payload": payload,
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
    from app.plugins.slots import SUPPORTED_SLOTS

    return {
        "schema_version": data.get("schema_version"),
        "host_api_version": data.get("host_api_version", HOST_SDK_VERSION),
        "registry_path": str(registry_path()),
        "artifacts_root": str(artifacts_root()),
        "plugins": list_plugins(),
        "supported_slots": sorted(SUPPORTED_SLOTS),
        "execution_model": "static_synthetic_only",
        "in_process_plugin_exec": False,
    }


# Re-export for admin router
upload_stream = stream_upload_to_staging
