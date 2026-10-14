"""Authenticated plugin introspection for Host Shell UI slots (read-only + synthetic)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentUser
from app.plugins.engine import run_synthetic
from app.plugins.registry import list_active_for_slot, list_plugins
from app.plugins.slots import SUPPORTED_SLOTS
from app.tools.pack_ops import PackOpsError
from app.tools.runtime_pins import HOST_SDK_VERSION

router = APIRouter(prefix="/plugins", tags=["Plugins"])


@router.get("/slots")
async def plugin_slots(user: CurrentUser) -> dict:
    return {
        "host_api_version": HOST_SDK_VERSION,
        "supported_slots": sorted(SUPPORTED_SLOTS),
        "loading_model": "shell_facade_registry",
        "notes": (
            "Independent frontend bundles are not loaded into the Host Shell in P1. "
            "Plugins declare a slot; the shell renders a registered host component."
        ),
    }


@router.get("/active")
async def active_plugins(user: CurrentUser, slot: str | None = None) -> dict:
    return {
        "host_api_version": HOST_SDK_VERSION,
        "plugins": list_active_for_slot(slot),
    }


@router.get("/")
async def plugins_summary(user: CurrentUser) -> dict:
    """Non-admin summary: active plugins only (no install controls)."""
    active = [p for p in list_plugins() if p.get("activation_status") == "active"]
    return {"plugins": active, "host_api_version": HOST_SDK_VERSION}


@router.post("/{plugin_id}/synthetic")
async def plugin_synthetic(plugin_id: str, user: CurrentUser) -> dict:
    try:
        return run_synthetic(plugin_id)
    except PackOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
