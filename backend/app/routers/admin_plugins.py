"""Admin-only Plugin Manager API (Stage P1.1).

Upload/install uses opaque staging IDs only — no client ``source_path``.
"""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database.session import get_db_session
from app.models.user import User, UserRole
from app.plugins import engine
from app.plugins.registry import list_plugins
from app.services import tool_tree_service as tool_tree_svc
from app.tools.pack_ops import PackOpsError

router = APIRouter(prefix="/admin/plugins", tags=["AdminPlugins"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class ConfirmBody(BaseModel):
    confirm: str
    version: str | None = None
    to: str | None = None


class InstallStagingBody(BaseModel):
    staging_id: str = Field(..., min_length=32, max_length=32)
    expected_digest: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    confirm: str = "install"


class ZipBase64Body(BaseModel):
    """JSON zip upload — avoids broken multipart/FormData proxies and axios Content-Type bugs."""

    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=16)


def _err(exc: Exception) -> None:
    """Surface pack/validation failures as HTTP 422 with a readable detail string."""
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _staging_from_base64(body: ZipBase64Body) -> str:
    name = (body.filename or "").strip()
    if not name.lower().endswith(".zip"):
        raise PackOpsError("filename must end with .zip")
    try:
        raw = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PackOpsError("invalid content_base64") from exc
    if not raw:
        raise PackOpsError("empty upload")
    return engine.upload_stream(BytesIO(raw))


async def _staging_from_request(request: Request) -> str:
    """Accept multipart ``file`` or JSON ``{filename, content_base64}``.

    Parsed from the raw Request so JSON bodies are not rejected by ``File(...)``.
    """
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        payload = await request.json()
        return _staging_from_base64(ZipBase64Body.model_validate(payload))
    if "multipart/form-data" in ctype:
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            raise PackOpsError("missing zip upload: multipart field 'file' required")
        return engine.upload_stream(upload.file)
    raise PackOpsError(
        "missing zip upload: send multipart field 'file' or JSON "
        "{filename, content_base64}"
    )


@router.get("")
async def list_installed(admin: AdminUser) -> dict:
    return {"ok": True, "plugins": list_plugins(), "registry": engine.registry_snapshot()}


@router.get("/health")
async def plugins_health(admin: AdminUser) -> dict:
    """Plugin subsystem health for admin indicators (no secrets)."""
    return engine.plugin_system_health()


@router.get("/audit")
async def audit_history(admin: AdminUser, limit: int = 100) -> dict:
    return {"ok": True, "events": engine.read_audit_history(limit=min(limit, 500))}


@router.get("/{plugin_id}/versions")
async def plugin_versions(plugin_id: str, admin: AdminUser) -> dict:
    return {"ok": True, "plugin_id": plugin_id, "versions": engine.version_history(plugin_id)}


@router.post("/upload")
async def upload_plugin(request: Request, admin: AdminUser) -> dict:
    """Stream zip into opaque staging. Does not validate or install.

    Accepts multipart ``file`` or JSON ``{filename, content_base64}``.
    """
    try:
        staging_id = await _staging_from_request(request)
        return {"ok": True, "staging_id": staging_id}
    except (PackOpsError, ValueError, OSError, ValidationError) as exc:
        _err(exc)


@router.post("/validate-upload")
async def validate_upload(request: Request, admin: AdminUser) -> dict:
    """Upload + validate in one step; returns staging_id + digest (not installed).

    Accepts multipart ``file`` or JSON ``{filename, content_base64}`` so clients
    that cannot send multipart (axios JSON Content-Type) still work.
    """
    try:
        staging_id = await _staging_from_request(request)
        return engine.validate_staging(staging_id)
    except (PackOpsError, ValueError, OSError, ValidationError) as exc:
        _err(exc)


@router.post("/staging/{staging_id}/validate")
async def validate_staged(staging_id: str, admin: AdminUser) -> dict:
    try:
        return engine.validate_staging(staging_id)
    except (PackOpsError, ValueError, OSError) as exc:
        _err(exc)


@router.post("/install")
async def install_plugin(admin: AdminUser, body: InstallStagingBody) -> dict:
    """Install only a validated staging artifact whose digest matches."""
    try:
        return engine.install_from_staging(
            staging_id=body.staging_id,
            expected_digest=body.expected_digest,
            actor=admin.email or str(admin.id),
            confirm=body.confirm,
        )
    except (PackOpsError, ValueError, OSError) as exc:
        _err(exc)


@router.post("/{plugin_id}/activate")
async def activate(plugin_id: str, admin: AdminUser, body: ConfirmBody) -> dict:
    try:
        if not body.version:
            raise PackOpsError("version required")
        return engine.activate_plugin(
            plugin_id=plugin_id,
            version=body.version,
            actor=admin.email or str(admin.id),
            confirm=body.confirm,
        )
    except (PackOpsError, ValueError) as exc:
        _err(exc)


@router.post("/{plugin_id}/disable")
async def disable(plugin_id: str, admin: AdminUser, body: ConfirmBody) -> dict:
    try:
        return engine.disable_plugin(
            plugin_id=plugin_id,
            actor=admin.email or str(admin.id),
            confirm=body.confirm,
        )
    except (PackOpsError, ValueError) as exc:
        _err(exc)


@router.post("/{plugin_id}/uninstall")
async def uninstall(plugin_id: str, admin: AdminUser, body: ConfirmBody, db: DbSession) -> dict:
    """Delete Tool Tree placements and remove the plugin from the active registry."""
    try:
        if body.confirm != "uninstall":
            raise PackOpsError("refusing uninstall: confirm must be exactly 'uninstall'")
        actor = admin.email or str(admin.id)
        placements = await tool_tree_svc.delete_placements_for_plugin(
            db, plugin_id, actor=actor
        )
        result = engine.uninstall_plugin(
            plugin_id=plugin_id,
            actor=actor,
            confirm=body.confirm,
        )
        result["placements"] = placements
        return result
    except (PackOpsError, ValueError, tool_tree_svc.ToolTreeError) as exc:
        _err(exc)


@router.post("/{plugin_id}/rollback")
async def rollback(plugin_id: str, admin: AdminUser, body: ConfirmBody) -> dict:
    try:
        if not body.to:
            raise PackOpsError("to required (version or inactive)")
        return engine.rollback_plugin(
            plugin_id=plugin_id,
            to=body.to,
            actor=admin.email or str(admin.id),
            confirm=body.confirm,
        )
    except (PackOpsError, ValueError) as exc:
        _err(exc)
