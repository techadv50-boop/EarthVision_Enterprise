"""Load versioned Tool Pack plugins with integrity checks (no in-place reload)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from app.tools.runtime_pins import get_pin, repo_root

_LOCK = threading.RLock()
# Cache by (tool_id, version, digest) → module
_MODULES: dict[tuple[str, str, str], ModuleType] = {}


class PackIntegrityError(Exception):
    """Artifact missing, tampered, or digest mismatch."""


def artifacts_root() -> Path:
    return repo_root() / "tools" / "artifacts"


def pack_dir(tool_id: str, version: str) -> Path:
    return artifacts_root() / tool_id / version


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pack(tool_id: str, version: str, expected_digest: str | None = None) -> dict[str, Any]:
    root = pack_dir(tool_id, version)
    pack_json = root / "pack.json"
    sums = root / "SHA256SUMS"
    plugin = root / "backend" / "plugin.py"
    if not root.is_dir():
        raise PackIntegrityError(f"pack directory missing: {root}")
    if not pack_json.is_file():
        raise PackIntegrityError(f"pack.json missing in {root}")
    if not plugin.is_file():
        raise PackIntegrityError(f"backend/plugin.py missing in {root}")
    if not sums.is_file():
        raise PackIntegrityError(f"SHA256SUMS missing in {root}")

    meta = json.loads(pack_json.read_text(encoding="utf-8"))
    if meta.get("tool_id") != tool_id or meta.get("version") != version:
        raise PackIntegrityError("pack.json tool_id/version mismatch")

    # Verify hashed payload files listed in SHA256SUMS
    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, rel = parts[0], parts[-1]
        target = root / rel
        if not target.is_file():
            raise PackIntegrityError(f"listed file missing: {rel}")
        actual = _sha256_file(target)
        if actual != digest:
            raise PackIntegrityError(f"digest mismatch for {rel}")

    # Pack digest = sha256 of SHA256SUMS (pin stores this)
    pack_digest = "sha256:" + _sha256_file(sums)
    meta_digest = meta.get("digest")
    if meta_digest and meta_digest != pack_digest:
        raise PackIntegrityError("pack.json digest does not match SHA256SUMS")
    if expected_digest and expected_digest != pack_digest:
        raise PackIntegrityError(
            f"pin digest {expected_digest} != artifact {pack_digest}"
        )
    meta["digest"] = pack_digest
    return meta


def _module_name(tool_id: str, version: str) -> str:
    safe_v = version.replace(".", "_").replace("-", "_")
    safe_t = tool_id.replace("-", "_")
    return f"ev_pack_{safe_t}_{safe_v}"


def load_pack_module(tool_id: str, version: str, digest: str | None = None) -> ModuleType:
    meta = verify_pack(tool_id, version, expected_digest=digest)
    pack_digest = meta["digest"]
    key = (tool_id, version, pack_digest)
    with _LOCK:
        if key in _MODULES:
            return _MODULES[key]
        plugin = pack_dir(tool_id, version) / "backend" / "plugin.py"
        name = _module_name(tool_id, version)
        # Unique name per version — never importlib.reload
        if name in sys.modules and key not in _MODULES:
            # Stale name from different digest — use suffixed name
            name = name + "_" + pack_digest[-8:]
        spec = importlib.util.spec_from_file_location(name, plugin)
        if spec is None or spec.loader is None:
            raise PackIntegrityError(f"cannot load plugin from {plugin}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        if not hasattr(mod, "render"):
            raise PackIntegrityError("plugin missing render()")
        _MODULES[key] = mod
        return mod


def resolve_true_color_render() -> tuple[str, Callable[..., Any] | None]:
    """Return (source_label, render_callable_or_none).

    ``builtin`` → caller must use in-tree CompositeService path (callable is None).
    ``pack:X`` → callable renders via the verified pack plugin.
    """
    pin = get_pin("true_color")
    mode = (pin.get("mode") or "builtin").lower()
    if mode == "builtin" or not pin.get("version"):
        return "builtin", None

    version = str(pin["version"])
    digest = pin.get("digest")
    mod = load_pack_module("true_color", version, digest=digest)

    def _render(request):  # noqa: ANN001
        from app.tools.host_sdk import composite_host_port

        return mod.render(request, composite_host_port())

    return f"pack:{version}", _render
