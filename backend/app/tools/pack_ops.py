"""Secure Tool Pack install / activate / rollback (production-oriented).

Separate phases:
1. **install** — verify signature + integrity, publish immutable artifact (no pin flip)
2. **activate** — atomic pin update after install verification (requires confirm)
3. **rollback** — atomic pin to previous pack or builtin

Never allows unsigned activation when ``EV_PACK_REQUIRE_SIGNATURE=1`` (default in preview/prod).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.pack_loader import PackIntegrityError, assert_artifact_immutable, verify_pack
from app.tools.pack_paths import (
    artifacts_root,
    audit_log_path,
    pack_dir,
    staging_root,
)
from app.tools.pack_signatures import (
    PackSignatureError,
    load_approved_publishers,
    read_signature_file,
    trust_profile,
    verify_digest_signature,
)
from app.tools.runtime_pins import get_pin, load_pins, write_pins

ALLOWED_TOOLS = frozenset({"true_color"})


class PackOpsError(Exception):
    """Install/activate/rollback rejected."""


def _require_signature() -> bool:
    return os.environ.get("EV_PACK_REQUIRE_SIGNATURE", "1") != "0"


def assert_production_trust_ready() -> None:
    """Fail closed before install/activate when production trust is misconfigured."""
    if trust_profile() != "production":
        return
    try:
        pubs = load_approved_publishers()
    except PackSignatureError as exc:
        raise PackOpsError(f"production trust rejected: {exc}") from exc
    for pub in pubs:
        if str(pub.get("id")) == "preview-dev" or str(pub.get("environment") or "").lower() == "preview":
            raise PackOpsError("production trust rejected: preview publisher present")



def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit(event: dict[str, Any]) -> None:
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {**event, "ts": _now()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                with open(fp, "rb") as f:
                    os.fsync(f.fileno())
            except OSError:
                pass
        try:
            fd = os.open(dirpath, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass


def ensure_default_pins() -> Path:
    """Create builtin-default pins file if missing (preview volume bootstrap)."""
    from app.tools.pack_paths import pins_path

    path = pins_path()
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pins(
        {
            "schema_version": 1,
            "notes": "Tool Pack runtime pins (volume). Default builtin preserves shell behavior.",
            "pins": {
                "true_color": {
                    "mode": "builtin",
                    "version": None,
                    "digest": None,
                    "updated_at": _now(),
                    "note": "Default: verified builtin fallback",
                }
            },
        }
    )
    return path


def install_pack_from_dir(
    source_dir: Path,
    *,
    tool_id: str,
    version: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    """Verify and publish an immutable artifact. Does **not** change the runtime pin."""
    if confirm != "install":
        raise PackOpsError("refusing install: confirm must be exactly 'install'")
    if tool_id not in ALLOWED_TOOLS:
        raise PackOpsError(f"tool not approved for pack install: {tool_id}")
    if not source_dir.is_dir():
        raise PackOpsError(f"source missing: {source_dir}")
    assert_production_trust_ready()

    # Stage under unique dir
    stage = staging_root() / f"{tool_id}-{version}-{time.time_ns()}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, stage)

    try:
        # Temporarily point verification at staging by copying layout:
        # verify_pack reads artifacts_root()/tool/version — use env override via
        # installing into a temp artifacts layout under staging.
        staged_art = stage  # source already is pack root content
        # Move into expected relative structure for verify using a temp root
        tmp_root = staging_root() / f"_verify_{time.time_ns()}"
        dest_verify = tmp_root / tool_id / version
        dest_verify.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged_art, dest_verify)

        prev = os.environ.get("EV_ARTIFACTS_ROOT")
        os.environ["EV_ARTIFACTS_ROOT"] = str(tmp_root)
        try:
            meta = verify_pack(tool_id, version)
            if _require_signature():
                sig = read_signature_file(dest_verify)
                if sig["digest"] != meta["digest"]:
                    raise PackSignatureError("SIGNATURE.json digest mismatch vs artifact")
                pub = verify_digest_signature(
                    meta["digest"],
                    sig["signature"],
                    publisher_id=str(sig["publisher_id"]),
                )
                meta["publisher_id"] = pub.get("id")
                meta["publisher_name"] = pub.get("name")
            else:
                meta["publisher_id"] = None
                meta["signature_skipped"] = True
        finally:
            if prev is None:
                os.environ.pop("EV_ARTIFACTS_ROOT", None)
            else:
                os.environ["EV_ARTIFACTS_ROOT"] = prev
            shutil.rmtree(tmp_root, ignore_errors=True)

        # Immutable publish
        assert_artifact_immutable(tool_id, version)
        final = pack_dir(tool_id, version)
        final.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: copy to sibling then rename
        tmp_final = final.with_name(final.name + f".installing.{os.getpid()}")
        if tmp_final.exists():
            shutil.rmtree(tmp_final)
        shutil.copytree(staged_art, tmp_final)
        _fsync_tree(tmp_final)
        os.replace(tmp_final, final)
        _fsync_tree(final.parent)

        result = {
            "action": "install",
            "ok": True,
            "tool_id": tool_id,
            "version": version,
            "digest": meta["digest"],
            "path": str(final),
            "actor": actor,
            "publisher_id": meta.get("publisher_id"),
        }
        _audit(result)
        return result
    except (PackIntegrityError, PackSignatureError, PackOpsError) as exc:
        _audit(
            {
                "action": "install",
                "ok": False,
                "tool_id": tool_id,
                "version": version,
                "actor": actor,
                "error": str(exc),
            }
        )
        raise PackOpsError(str(exc)) from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def activate_pack(
    *,
    tool_id: str,
    version: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    """Atomically pin an already-installed pack. Requires confirm=activate."""
    if confirm != "activate":
        raise PackOpsError("refusing activate: confirm must be exactly 'activate'")
    if tool_id not in ALLOWED_TOOLS:
        raise PackOpsError(f"tool not approved for activation: {tool_id}")
    assert_production_trust_ready()

    try:
        meta = verify_pack(tool_id, version)
        if _require_signature():
            sig = read_signature_file(pack_dir(tool_id, version))
            if sig["digest"] != meta["digest"]:
                raise PackSignatureError("SIGNATURE.json digest mismatch")
            verify_digest_signature(
                meta["digest"],
                sig["signature"],
                publisher_id=str(sig["publisher_id"]),
            )

        data = load_pins(force=True)
        pins = data.setdefault("pins", {})
        previous = pins.get(tool_id)
        pins[tool_id] = {
            "mode": "pack",
            "version": version,
            "digest": meta["digest"],
            "updated_at": _now(),
            "activated_by": actor,
            "previous": previous,
        }
        data["schema_version"] = 1
        write_pins(data)

        result = {
            "action": "activate",
            "ok": True,
            "tool_id": tool_id,
            "version": version,
            "digest": meta["digest"],
            "previous": previous,
            "actor": actor,
        }
        _audit(result)
        return result
    except (PackIntegrityError, PackSignatureError, PackOpsError) as exc:
        _audit(
            {
                "action": "activate",
                "ok": False,
                "tool_id": tool_id,
                "version": version,
                "actor": actor,
                "error": str(exc),
            }
        )
        raise PackOpsError(str(exc)) from exc


def rollback_pack(
    *,
    tool_id: str,
    to: str,
    actor: str,
    confirm: str,
) -> dict[str, Any]:
    """Rollback pin to ``builtin`` or an installed version. confirm=rollback."""
    if confirm != "rollback":
        raise PackOpsError("refusing rollback: confirm must be exactly 'rollback'")
    if tool_id not in ALLOWED_TOOLS:
        raise PackOpsError(f"tool not approved: {tool_id}")

    try:
        data = load_pins(force=True)
        pins = data.setdefault("pins", {})
        previous = pins.get(tool_id)

        if to == "builtin":
            pins[tool_id] = {
                "mode": "builtin",
                "version": None,
                "digest": None,
                "updated_at": _now(),
                "activated_by": actor,
                "previous": previous,
                "note": "rollback to builtin",
            }
            target_meta: dict[str, Any] = {"mode": "builtin"}
        else:
            meta = verify_pack(tool_id, to)
            if _require_signature():
                sig = read_signature_file(pack_dir(tool_id, to))
                verify_digest_signature(
                    meta["digest"],
                    sig["signature"],
                    publisher_id=str(sig["publisher_id"]),
                )
            pins[tool_id] = {
                "mode": "pack",
                "version": to,
                "digest": meta["digest"],
                "updated_at": _now(),
                "activated_by": actor,
                "previous": previous,
                "note": f"rollback to {to}",
            }
            target_meta = meta

        write_pins(data)
        result = {
            "action": "rollback",
            "ok": True,
            "tool_id": tool_id,
            "to": to,
            "digest": target_meta.get("digest"),
            "previous": previous,
            "actor": actor,
            "current": get_pin(tool_id),
        }
        _audit(result)
        return result
    except (PackIntegrityError, PackSignatureError, PackOpsError) as exc:
        _audit(
            {
                "action": "rollback",
                "ok": False,
                "tool_id": tool_id,
                "to": to,
                "actor": actor,
                "error": str(exc),
            }
        )
        raise PackOpsError(str(exc)) from exc
