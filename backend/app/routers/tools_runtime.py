"""Tool runtime introspection — pins, pack meta (dev / admin visibility)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentUser
from app.tools.pack_loader import PackIntegrityError, artifacts_root, verify_pack
from app.tools.runtime_pins import get_pin, load_pins, repo_root

router = APIRouter(prefix="/tools", tags=["ToolRuntime"])


@router.get("/runtime")
async def tool_runtime(user: CurrentUser) -> dict:
    """Return runtime pins and deployment model honesty flag."""
    data = load_pins(force=True)
    return {
        "deployment_model": "tool_packs_for_pinned_tools_else_full_app",
        "shell_deploy": "full_app Deploy SATEYE unchanged",
        "pins": data.get("pins") or {},
        "true_color": get_pin("true_color"),
    }


@router.get("/packs/{tool_id}/{version}/meta")
async def pack_ui_meta(tool_id: str, version: str, user: CurrentUser) -> dict:
    if tool_id != "true_color":
        raise HTTPException(status_code=404, detail="Only true_color pack is available in E1")
    try:
        verify_pack(tool_id, version)
    except PackIntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta_path = artifacts_root() / tool_id / version / "ui" / "tool-meta.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="ui meta missing")
    return json.loads(meta_path.read_text(encoding="utf-8"))


@router.get("/packs/{tool_id}/{version}/pack.json")
async def pack_manifest(tool_id: str, version: str, user: CurrentUser) -> dict:
    if tool_id != "true_color":
        raise HTTPException(status_code=404, detail="Only true_color pack is available in E1")
    try:
        return verify_pack(tool_id, version)
    except PackIntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
