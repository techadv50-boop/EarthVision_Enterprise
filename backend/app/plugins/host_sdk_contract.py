"""Versioned Host SDK contract for sandboxed frontend plugins (RC).

Plugins in iframes must not import Host Shell modules. They may only call
allowlisted methods via a validated postMessage bridge. Method availability is
gated by pack ``permissions`` declarations (still not an OS sandbox).
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Semver for the plugin frontend Host SDK (postMessage).
# 1.3: map presentation + clearMapLayer · 1.4: host.getCapabilities (geo profile lock)
PLUGIN_HOST_SDK_VERSION = "1.4.0"
PLUGIN_HOST_SDK_PROTOCOL = 1

HOST_SDK_METHODS: dict[str, str] = {
    "host.meta": "host.sdk.read_meta",
    "host.getSynthetic": "synthetic_data",
    "host.resize": "",
    "host.getAoiBounds": "host.sdk.read_aoi",
    "host.setAnalysisResult": "host.sdk.set_analysis_result",
    "host.getAnalysisResult": "host.sdk.read_analysis_result",
    # Frozen Host geospatial profile (libs + tool families)
    "host.getCapabilities": "host.sdk.read_capabilities",
    # Optical true-color plugin (Host Shell fulfills; bridge echoes / gates only)
    "host.getSceneContext": "host.sdk.read_scene",
    "host.renderTrueColor": "host.sdk.render_true_color",
    # Permanent clear for any host-presented layer (plugins never touch Leaflet)
    "host.clearMapLayer": "host.sdk.clear_map_layer",
    "host.exportGeotiff": "host.sdk.export_geotiff",
    "host.exportMapJpeg": "host.sdk.export_map_jpeg",
}

FORBIDDEN_HOST_SDK_METHODS = frozenset(
    {
        "host.getAuthToken",
        "host.getSession",
        "host.fetch",
        "host.leaflet",
        "host.map",
        "host.eval",
        "host.import",
        "host.admin",
        "host.database",
    }
)

_ANALYSIS_LOCK = threading.Lock()
# plugin_id → {result, updated_at, version, digest}
_ANALYSIS_RESULTS: dict[str, dict[str, Any]] = {}


class HostSdkError(ValueError):
    """Invalid Host SDK request from a plugin frame."""


def assert_method_allowed(method: str, permissions: list[str] | None) -> None:
    if method in FORBIDDEN_HOST_SDK_METHODS:
        raise HostSdkError(f"forbidden Host SDK method: {method}")
    if method not in HOST_SDK_METHODS:
        raise HostSdkError(f"unknown Host SDK method: {method}")
    need = HOST_SDK_METHODS[method]
    if need and need not in (permissions or []):
        raise HostSdkError(f"permission denied for {method}: requires {need}")


def store_analysis_result(
    *,
    plugin_id: str,
    version: str,
    digest: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise HostSdkError("analysis result must be an object")
    # Cap payload size / shape
    raw = str(result)
    if len(raw) > 50_000:
        raise HostSdkError("analysis result too large")
    for bad in ("token", "password", "authorization", "cookie", "secret"):
        if bad in raw.lower():
            raise HostSdkError("analysis result must not include secrets")
    entry = {
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "result": result,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _ANALYSIS_LOCK:
        _ANALYSIS_RESULTS[plugin_id] = entry
    return {"stored": True, "updated_at": entry["updated_at"]}


def load_analysis_result(plugin_id: str) -> dict[str, Any] | None:
    with _ANALYSIS_LOCK:
        return _ANALYSIS_RESULTS.get(plugin_id)


def validate_plugin_message(data: Any) -> dict[str, Any]:
    """Validate a plugin→host postMessage envelope (fail closed)."""
    if not isinstance(data, dict):
        raise HostSdkError("message must be an object")
    if data.get("v") != PLUGIN_HOST_SDK_PROTOCOL:
        raise HostSdkError("unsupported Host SDK protocol version")
    msg_type = data.get("type")
    if msg_type not in {"ready", "request"}:
        raise HostSdkError(f"unsupported message type: {msg_type!r}")
    plugin_id = data.get("plugin_id")
    version = data.get("version")
    digest = data.get("digest")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise HostSdkError("plugin_id required")
    if not isinstance(version, str) or not version:
        raise HostSdkError("version required")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise HostSdkError("digest must be sha256:...")
    out: dict[str, Any] = {
        "v": PLUGIN_HOST_SDK_PROTOCOL,
        "type": msg_type,
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
    }
    if msg_type == "request":
        req_id = data.get("id")
        method = data.get("method")
        params = data.get("params")
        if not isinstance(req_id, str) or not req_id:
            raise HostSdkError("request id required")
        if not isinstance(method, str) or not method:
            raise HostSdkError("method required")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise HostSdkError("params must be an object")
        for k in params:
            lk = str(k).lower()
            if any(s in lk for s in ("token", "authorization", "password", "cookie", "secret")):
                raise HostSdkError("params must not include secrets")
        out["id"] = req_id
        out["method"] = method
        out["params"] = params
    return out


def host_response(
    *,
    req_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    result: Any,
) -> dict[str, Any]:
    return {
        "v": PLUGIN_HOST_SDK_PROTOCOL,
        "type": "response",
        "id": req_id,
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "ok": True,
        "result": result,
    }


def host_error(
    *,
    req_id: str | None,
    plugin_id: str | None,
    error: str,
    code: str = "host_sdk_error",
) -> dict[str, Any]:
    return {
        "v": PLUGIN_HOST_SDK_PROTOCOL,
        "type": "error",
        "id": req_id,
        "plugin_id": plugin_id,
        "ok": False,
        "error": error,
        "code": code,
    }
