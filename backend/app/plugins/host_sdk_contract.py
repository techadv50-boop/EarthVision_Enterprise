"""Versioned Host SDK contract for sandboxed frontend plugins (P2B).

Plugins in iframes must not import Host Shell modules. They may only call
allowlisted methods via a validated postMessage bridge. Method availability is
gated by pack ``permissions`` declarations (still not an OS sandbox).
"""

from __future__ import annotations

from typing import Any

# Semver for the *plugin frontend* Host SDK (postMessage). Independent of
# Tool Pack ``HOST_SDK_VERSION`` but kept compatible with pack host_sdk ranges.
PLUGIN_HOST_SDK_VERSION = "1.0.0"
PLUGIN_HOST_SDK_PROTOCOL = 1

# Methods the privileged Host Shell may honor for iframe plugins.
HOST_SDK_METHODS: dict[str, str] = {
    # Returns plugin_id / version / digest / slot / sdk version — no secrets.
    "host.meta": "host.sdk.read_meta",
    # Integrity-covered synthetic payload (or worker render) via Host Shell.
    "host.getSynthetic": "synthetic_data",
    # Request iframe chrome height (always allowed when plugin is active).
    "host.resize": "",
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
        # Strip any attempt to smuggle secrets / tokens
        for bad in ("token", "authorization", "password", "cookie", "secret"):
            if bad in params or bad in {k.lower() for k in params}:
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
