"""Admin Host library install — persistent extras volume, no image rebuild."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.deps import require_roles
from app.host_libraries import (
    HostLibraryError,
    install_from_index,
    install_wheels,
    list_installed,
    uninstall_package,
)
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/host-libraries", tags=["admin-host-libraries"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _err(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": str(exc)[:800]},
    )


class WheelFileIn(BaseModel):
    filename: str = Field(..., min_length=1, max_length=240)
    content_base64: str = Field(..., min_length=8)


class UploadWheelsBody(BaseModel):
    files: list[WheelFileIn] = Field(..., min_length=1, max_length=20)


class PipInstallBody(BaseModel):
    package: str = Field(..., min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=64)


class UninstallBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


@router.get("")
async def get_host_libraries(admin: AdminUser) -> dict:
    _ = admin
    return list_installed()


@router.post("/upload")
async def upload_host_libraries(admin: AdminUser, body: UploadWheelsBody) -> dict | JSONResponse:
    """Install uploaded .whl / .tar.gz into the Host extras volume (no rebuild)."""
    try:
        files: list[tuple[str, bytes]] = []
        for item in body.files:
            try:
                blob = base64.b64decode(item.content_base64, validate=False)
            except binascii.Error as exc:
                raise HostLibraryError(f"invalid base64 for {item.filename}") from exc
            files.append((item.filename, blob))
        actor = admin.email or str(admin.id)
        return install_wheels(files=files, actor=actor)
    except HostLibraryError as exc:
        return _err(exc)


@router.post("/pip-install")
async def pip_install_host_library(
    admin: AdminUser, body: PipInstallBody
) -> dict | JSONResponse:
    """Allowlisted PyPI install into extras (disabled unless EV_HOST_LIBS_ALLOW_PIP=1)."""
    try:
        actor = admin.email or str(admin.id)
        return install_from_index(
            package=body.package, version=body.version, actor=actor
        )
    except HostLibraryError as exc:
        return _err(exc)


@router.post("/uninstall")
async def uninstall_host_library(
    admin: AdminUser, body: UninstallBody
) -> dict | JSONResponse:
    try:
        actor = admin.email or str(admin.id)
        return uninstall_package(name=body.name, actor=actor)
    except HostLibraryError as exc:
        return _err(exc)
