"""HTTP API for the tool plugin catalog and admin uploads."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_full_admin
from app.database.session import get_db
from app.models.user import User
from app.plugins import service as plugins

router = APIRouter(prefix="/plugins", tags=["Plugins"])

CurrentUser = Annotated[User, Depends(get_current_user)]
Operator = Annotated[User, Depends(require_full_admin)]
Db = Annotated[AsyncSession, Depends(get_db)]


class PluginToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_plugins(db: Db, user: CurrentUser):
    items = await plugins.catalog(db, user, include_disabled=user.is_full_admin())
    return {"plugins": items}


@router.post("/upload")
async def upload_plugin(
    db: Db,
    admin: Operator,
    file: UploadFile = File(...),
):
    name = (file.filename or "plugin.zip").lower()
    if not name.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip plugin package")
    data = await file.read()
    try:
        item = await plugins.install_zip(db, data, uploaded_by=admin.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@router.patch("/{plugin_id}")
async def toggle_plugin(plugin_id: str, body: PluginToggle, db: Db, _admin: Operator):
    try:
        return await plugins.set_enabled(db, plugin_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Plugin not found") from None


@router.delete("/{plugin_id}")
async def delete_plugin(plugin_id: str, db: Db, _admin: Operator):
    try:
        return await plugins.remove_upload(db, plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Plugin not found") from None


@router.get("/{plugin_id}/file/{path:path}")
async def plugin_file(plugin_id: str, path: str, db: Db, user: CurrentUser):
    items = await plugins.catalog(db, user, include_disabled=user.is_full_admin())
    item = next((row for row in items if row["id"] == plugin_id), None)
    if item is None or (not item["enabled"] and not user.is_full_admin()):
        raise HTTPException(status_code=404, detail="Plugin not found")
    if item["kind"] != "uploaded":
        raise HTTPException(status_code=404, detail="This tool has no uploaded files")
    target = (plugins.plugin_dir(plugin_id) / path).resolve()
    root = plugins.plugin_dir(plugin_id).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Invalid plugin path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)
