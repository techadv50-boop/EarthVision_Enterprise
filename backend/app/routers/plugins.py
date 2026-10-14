"""Authenticated plugin introspection + sandboxed FE asset serving (P2B)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser
from app.plugins import engine
from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset
from app.plugins.host_sdk_contract import (
    PLUGIN_HOST_SDK_PROTOCOL,
    PLUGIN_HOST_SDK_VERSION,
    HostSdkError,
    assert_method_allowed,
    host_error,
    host_response,
    validate_plugin_message,
)
from app.plugins.registry import get_plugin, list_active_for_slot, list_plugins
from app.plugins.slots import SUPPORTED_SLOTS
from app.tools.pack_ops import PackOpsError
from app.tools.runtime_pins import HOST_SDK_VERSION

router = APIRouter(prefix="/plugins", tags=["Plugins"])


class HostSdkBridgeBody(BaseModel):
    """Server-side Host SDK bridge for methods that need privileged Host Shell access.

    The iframe never receives auth tokens; the Host Shell browser calls this
    authenticated endpoint after validating the postMessage envelope.
    """

    v: int = Field(..., description="Host SDK protocol version")
    type: str = "request"
    id: str
    plugin_id: str
    version: str
    digest: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    method: str
    params: dict = Field(default_factory=dict)


@router.get("/slots")
async def plugin_slots(user: CurrentUser) -> dict:
    return {
        "host_api_version": HOST_SDK_VERSION,
        "plugin_host_sdk_version": PLUGIN_HOST_SDK_VERSION,
        "plugin_host_sdk_protocol": PLUGIN_HOST_SDK_PROTOCOL,
        "supported_slots": sorted(SUPPORTED_SLOTS),
        "loading_model": "sandboxed_iframe_srcdoc",
        "notes": (
            "Independent plugin UI loads only inside a sandboxed iframe (srcdoc) "
            "via a validated postMessage Host SDK. Uploaded JS never runs in the "
            "privileged React Host Shell."
        ),
    }


@router.get("/active")
async def active_plugins(user: CurrentUser, slot: str | None = None) -> dict:
    return {
        "host_api_version": HOST_SDK_VERSION,
        "plugin_host_sdk_version": PLUGIN_HOST_SDK_VERSION,
        "plugins": list_active_for_slot(slot),
    }


@router.get("/")
async def plugins_summary(user: CurrentUser) -> dict:
    """Non-admin summary: active plugins only (no install controls)."""
    active = [p for p in list_plugins() if p.get("activation_status") == "active"]
    return {
        "plugins": active,
        "host_api_version": HOST_SDK_VERSION,
        "plugin_host_sdk_version": PLUGIN_HOST_SDK_VERSION,
    }


@router.get("/{plugin_id}/frontend")
async def plugin_frontend_manifest(plugin_id: str, user: CurrentUser) -> dict:
    try:
        return active_frontend_manifest(plugin_id)
    except PackOpsError as exc:
        engine.audit_frontend_event(
            action="frontend_manifest",
            ok=False,
            plugin_id=plugin_id,
            error=str(exc),
            actor=getattr(user, "email", None) or "user",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{plugin_id}/ui/{asset_path:path}")
async def plugin_ui_asset(plugin_id: str, asset_path: str, user: CurrentUser) -> Response:
    try:
        data, ctype = read_active_ui_asset(plugin_id, asset_path)
    except PackOpsError as exc:
        engine.audit_frontend_event(
            action="frontend_asset",
            ok=False,
            plugin_id=plugin_id,
            error=str(exc),
            actor=getattr(user, "email", None) or "user",
            extra={"asset": asset_path[:200]},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # CSP for direct asset fetches (iframe uses srcdoc; still harden)
    headers = {
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data:; font-src data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "X-EV-Plugin-UI": "1",
    }
    return Response(content=data, media_type=ctype, headers=headers)


@router.post("/{plugin_id}/host-sdk")
async def plugin_host_sdk_bridge(
    plugin_id: str,
    body: HostSdkBridgeBody,
    user: CurrentUser,
) -> dict:
    """Execute an allowlisted Host SDK method on behalf of a sandboxed plugin frame."""
    try:
        envelope = validate_plugin_message(
            {
                "v": body.v,
                "type": body.type,
                "id": body.id,
                "plugin_id": body.plugin_id,
                "version": body.version,
                "digest": body.digest,
                "method": body.method,
                "params": body.params,
            }
        )
        if envelope["plugin_id"] != plugin_id:
            raise HostSdkError("plugin_id mismatch")
        rec = get_plugin(plugin_id)
        if not rec or rec.get("activation_status") != "active":
            raise PackOpsError(f"plugin not active: {plugin_id}")
        if str(rec.get("version")) != envelope["version"]:
            raise PackOpsError("stale or rolled-back version (not active pin)")
        if str(rec.get("digest") or "") != envelope["digest"]:
            raise PackOpsError("digest does not match active pin")
        assert_method_allowed(envelope["method"], list(rec.get("permissions") or []))

        method = envelope["method"]
        if method == "host.meta":
            result = {
                "plugin_id": plugin_id,
                "version": envelope["version"],
                "digest": envelope["digest"],
                "frontend_slot": rec.get("frontend_slot"),
                "host_sdk_version": PLUGIN_HOST_SDK_VERSION,
                "permissions": list(rec.get("permissions") or []),
            }
        elif method == "host.getSynthetic":
            result = engine.run_synthetic(plugin_id)
        elif method == "host.resize":
            h = envelope["params"].get("height")
            if not isinstance(h, (int, float)) or h < 0 or h > 4000:
                raise HostSdkError("invalid resize height")
            result = {"height": int(h)}
        else:
            raise HostSdkError(f"unhandled method: {method}")

        return host_response(
            req_id=envelope["id"],
            plugin_id=plugin_id,
            version=envelope["version"],
            digest=envelope["digest"],
            result=result,
        )
    except (HostSdkError, PackOpsError) as exc:
        engine.audit_frontend_event(
            action="host_sdk",
            ok=False,
            plugin_id=plugin_id,
            version=getattr(body, "version", None),
            digest=getattr(body, "digest", None),
            error=str(exc),
            actor=getattr(user, "email", None) or "user",
            extra={"method": getattr(body, "method", None)},
        )
        return host_error(
            req_id=getattr(body, "id", None),
            plugin_id=plugin_id,
            error=str(exc),
            code="host_sdk_rejected",
        )


@router.post("/{plugin_id}/synthetic")
async def plugin_synthetic(plugin_id: str, user: CurrentUser) -> dict:
    try:
        return engine.run_synthetic(plugin_id)
    except PackOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
