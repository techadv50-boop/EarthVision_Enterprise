"""Serve integrity-covered plugin UI assets bound to the active registry pin (P2B).

Does not execute plugin JavaScript. Assets are static files under ``ui/`` that
appear in SHA256SUMS. Inactive / disabled / digest-mismatched plugins fail closed.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from app.plugins.host_sdk_contract import PLUGIN_HOST_SDK_PROTOCOL, PLUGIN_HOST_SDK_VERSION
from app.plugins.registry import get_plugin
from app.plugins.slots import validate_slot
from app.tools.pack_loader import verify_pack
from app.tools.pack_ops import PackOpsError
from app.tools.pack_paths import pack_dir

# Only these extensions may be served to the Host Shell iframe bootstrap.
_ALLOWED_UI_SUFFIXES = frozenset(
    {
        ".html",
        ".htm",
        ".js",
        ".css",
        ".json",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".woff2",
    }
)


def _listed_ui_files(root: Path) -> set[str]:
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        raise PackOpsError("SHA256SUMS missing")
    listed: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        rel = parts[-1].replace("\\", "/")
        if rel.startswith("ui/"):
            listed.add(rel)
    return listed


def _safe_ui_rel(asset_path: str) -> str:
    rel = (asset_path or "").strip().lstrip("/")
    if not rel:
        raise PackOpsError("asset path required")
    if ".." in Path(rel).parts or Path(rel).is_absolute():
        raise PackOpsError("unsafe asset path")
    if not rel.startswith("ui/"):
        rel = f"ui/{rel}"
    suffix = Path(rel).suffix.lower()
    if suffix not in _ALLOWED_UI_SUFFIXES:
        raise PackOpsError(f"disallowed UI asset type: {suffix or '(none)'}")
    return rel


def active_frontend_manifest(plugin_id: str) -> dict[str, Any]:
    """Return digest-bound frontend bootstrap info for an *active* plugin."""
    rec = get_plugin(plugin_id)
    if not rec or rec.get("activation_status") != "active":
        raise PackOpsError(f"plugin not active: {plugin_id}")
    version = str(rec["version"])
    digest = str(rec.get("digest") or "")
    if not digest.startswith("sha256:"):
        raise PackOpsError("active plugin missing digest pin")
    meta = verify_pack(plugin_id, version, expected_digest=digest)
    root = pack_dir(plugin_id, version)
    ui_meta_path = root / "ui" / "tool-meta.json"
    if not ui_meta_path.is_file() or ui_meta_path.is_symlink():
        raise PackOpsError("ui/tool-meta.json missing")
    ui_meta = json.loads(ui_meta_path.read_text(encoding="utf-8"))
    slot = validate_slot(str(ui_meta.get("frontend_slot") or rec.get("frontend_slot") or ""))
    strategy = str(ui_meta.get("ui_strategy") or meta.get("ui_strategy") or "shell_facade")
    entry = str(ui_meta.get("entry_html") or "ui/panel.html")
    entry = _safe_ui_rel(entry)
    listed = _listed_ui_files(root)
    if strategy == "sandboxed_iframe" and entry not in listed:
        raise PackOpsError(f"entry HTML not integrity-covered: {entry}")
    # Signature status for admin/health (presence only; verify already done at activate)
    sig_path = root / "SIGNATURE.json"
    signature_status = "present" if sig_path.is_file() else "missing"
    return {
        "ok": True,
        "plugin_id": plugin_id,
        "name": rec.get("name") or plugin_id,
        "version": version,
        "digest": digest,
        "frontend_slot": slot,
        "ui_strategy": strategy,
        "entry_html": entry,
        "permissions": list(rec.get("permissions") or []),
        "compatible_host_api": rec.get("compatible_host_api") or meta.get("host_sdk"),
        "host_sdk_version": PLUGIN_HOST_SDK_VERSION,
        "host_sdk_protocol": PLUGIN_HOST_SDK_PROTOCOL,
        "loading_model": "sandboxed_iframe_srcdoc",
        "signature_status": signature_status,
        "ui_files": sorted(listed),
    }


def read_active_ui_asset(plugin_id: str, asset_path: str) -> tuple[bytes, str]:
    """Read a single integrity-covered UI asset for the active pin."""
    rec = get_plugin(plugin_id)
    if not rec or rec.get("activation_status") != "active":
        raise PackOpsError(f"plugin not active: {plugin_id}")
    version = str(rec["version"])
    digest = str(rec.get("digest") or "")
    verify_pack(plugin_id, version, expected_digest=digest)
    root = pack_dir(plugin_id, version)
    rel = _safe_ui_rel(asset_path)
    listed = _listed_ui_files(root)
    if rel not in listed:
        raise PackOpsError(f"UI asset not in SHA256SUMS: {rel}")
    target = root / rel
    if not target.is_file() or target.is_symlink():
        raise PackOpsError("UI asset missing or symlink")
    # Ensure resolved path stays under pack ui/
    try:
        target.resolve().relative_to((root / "ui").resolve())
    except ValueError as exc:
        raise PackOpsError("UI asset escapes pack root") from exc
    data = target.read_bytes()
    ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    if rel.endswith(".js"):
        ctype = "application/javascript; charset=utf-8"
    elif rel.endswith(".html") or rel.endswith(".htm"):
        ctype = "text/html; charset=utf-8"
    elif rel.endswith(".css"):
        ctype = "text/css; charset=utf-8"
    elif rel.endswith(".json"):
        ctype = "application/json; charset=utf-8"
    return data, ctype
