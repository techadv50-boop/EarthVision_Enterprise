"""Admin-only Plugin Manager API (Stage P1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.core.deps import require_roles
from app.models.user import User, UserRole
from app.plugins import engine
from app.plugins.registry import list_plugins
from app.tools.pack_ops import PackOpsError
from app.tools.pack_paths import staging_root

router = APIRouter(prefix="/admin/plugins", tags=["AdminPlugins"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


class ConfirmBody(BaseModel):
    confirm: str
    version: str | None = None
    to: str | None = None


class ValidatePathBody(BaseModel):
    """Dev/preview: validate an already-extracted directory (local preview only)."""

    source_path: str = Field(..., description="Absolute path to pack directory")


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


@router.post("/validate-upload")
async def validate_upload(
    admin: AdminUser,
    file: UploadFile = File(...),
) -> dict:
    try:
        raw = await file.read()
        if len(raw) > 20 * 1024 * 1024:
            raise PackOpsError("upload too large (max 20MB)")
        pack_root = engine.extract_upload_zip(raw, staging_root() / "uploads")
        result = engine.validate_plugin_package(pack_root)
        # Keep extracted path for subsequent install in same session via returned staging hint
        result["staging_path"] = str(pack_root)
        return result
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


@router.post("/validate-path")
async def validate_path(admin: AdminUser, body: ValidatePathBody) -> dict:
    """Validate a local pack directory (preview / tests)."""
    from pathlib import Path

    try:
        return engine.validate_plugin_package(Path(body.source_path))
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


@router.post("/register")
async def register_plugin(admin: AdminUser, body: ValidatePathBody) -> dict:
    from pathlib import Path

    try:
        validated = engine.validate_plugin_package(Path(body.source_path))
        record = engine.register_from_validation(validated)
        return {"ok": True, "plugin": record}
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)


@router.post("/install")
async def install_plugin(
    admin: AdminUser,
    source_path: Annotated[str, Form()],
    plugin_id: Annotated[str, Form()],
    version: Annotated[str, Form()],
    confirm: Annotated[str, Form()] = "install",
) -> dict:
    from pathlib import Path

    try:
        return engine.install_plugin_from_dir(
            Path(source_path),
            plugin_id=plugin_id,
            version=version,
            actor=admin.email or str(admin.id),
            confirm=confirm,
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


@router.post("/upload-install")
async def upload_and_install(
    admin: AdminUser,
    file: UploadFile = File(...),
    confirm: Annotated[str, Form()] = "install",
) -> dict:
    """Validate uploaded zip then install (still inactive)."""
    try:
        if confirm != "install":
            raise PackOpsError("confirm must be install")
        raw = await file.read()
        if len(raw) > 20 * 1024 * 1024:
            raise PackOpsError("upload too large (max 20MB)")
        pack_root = engine.extract_upload_zip(raw, staging_root() / "uploads")
        validated = engine.validate_plugin_package(pack_root)
        return engine.install_plugin_from_dir(
            pack_root,
            plugin_id=validated["plugin_id"],
            version=validated["version"],
            actor=admin.email or str(admin.id),
            confirm="install",
        )
    except (PackOpsError, ValueError, OSError) as exc:
        return _err(exc)
