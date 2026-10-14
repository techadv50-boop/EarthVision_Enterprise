"""Admin-only Plugin Manager API (Stage P1.1).

Upload/install uses opaque staging IDs only — no client ``source_path``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.core.deps import require_roles
from app.models.user import User, UserRole
from app.plugins import engine
from app.plugins.registry import list_plugins
from app.tools.pack_ops import PackOpsError

router = APIRouter(prefix="/admin/plugins", tags=["AdminPlugins"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


class ConfirmBody(BaseModel):
    confirm: str
    version: str | None = None
    to: str | None = None


class InstallStagingBody(BaseModel):
    staging_id: str = Field(..., min_length=32, max_length=32)
    expected_digest: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    confirm: str = "install"


def _err(exc: Exception) -> dict:
    return {"ok": False, "error": str(exc)}


@router.get("")
async def list_installed(admin: AdminUser) -> dict:
    return {"ok": True, "plugins": list_plugins(), "registry": engine.registry_snapshot()}


@router.get("/audit")
async def audit_history(admin: AdminUser, limit: int = 100) -> dict:
    return {"ok": True, "events": engine.read_audit_history(limit=min(limit, 500))}


@router.get("/{plugin_id}/versions")
async def plugin_versions(plugin_id: str, admin: AdminUser) -> dict:
    return {"ok": True, "plugin_id": plugin_id, "versions": engine.version_history(plugin_id)}


@router.post("/upload")
async def upload_plugin(
    admin: AdminUser,
    file: UploadFile = File(...),
) -> dict:
    """Stream zip into opaque staging. Does not validate or install."""
    try:
        staging_id = engine.upload_stream(file.file)
        return {"ok": True, "staging_id": staging_id}
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


@router.post("/validate-upload")
async def validate_upload(
    admin: AdminUser,
    file: UploadFile = File(...),
) -> dict:
    """Upload + validate in one step; returns staging_id + digest (not installed)."""
    try:
        staging_id = engine.upload_stream(file.file)
        return engine.validate_staging(staging_id)
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


@router.post("/staging/{staging_id}/validate")
async def validate_staged(staging_id: str, admin: AdminUser) -> dict:
    try:
        return engine.validate_staging(staging_id)
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


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
        return _err(exc)


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
        return _err(exc)


@router.post("/{plugin_id}/disable")
async def disable(plugin_id: str, admin: AdminUser, body: ConfirmBody) -> dict:
    try:
        return engine.disable_plugin(
            plugin_id=plugin_id,
            actor=admin.email or str(admin.id),
            confirm=body.confirm,
        )
    except (PackOpsError, ValueError) as exc:
        return _err(exc)


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
        return _err(exc)
