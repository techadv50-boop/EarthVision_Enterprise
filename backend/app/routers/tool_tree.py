"""Plugin-first tool category tree and placement APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.database.session import get_db_session
from app.models.user import User, UserRole
from app.services import tool_tree_service as svc
from app.services.tool_tree_service import ToolTreeError

router = APIRouter(prefix="/tools", tags=["ToolTree"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    parent_id: str | None = None
    sort_order: int | None = None


class CategoryRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class CategoryMove(BaseModel):
    parent_id: str | None = None
    sort_order: int | None = None


class ReorderBody(BaseModel):
    ordered_ids: list[str]
    parent_id: str | None = None


class PlacementUpsert(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=128)
    category_id: str
    display_name: str = Field(..., min_length=1, max_length=255)
    execution_slot: str = "right_analysis_panel"
    description: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    visible: bool = True
    enabled: bool = True


class PlacementMove(BaseModel):
    category_id: str
    sort_order: int | None = None


class PlacementReorder(BaseModel):
    ordered_ids: list[str]


class SnapshotBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    note: str | None = None


def _err(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


def _cat(c) -> dict[str, Any]:
    return {
        "ok": True,
        "id": c.id,
        "name": c.name,
        "parent_id": c.parent_id,
        "sort_order": c.sort_order,
    }


def _placement(p) -> dict[str, Any]:
    return {
        "ok": True,
        "id": p.id,
        "plugin_id": p.plugin_id,
        "category_id": p.category_id,
        "display_name": p.display_name,
        "description": p.description,
        "icon": p.icon,
        "sort_order": p.sort_order,
        "execution_slot": p.execution_slot,
        "visible": p.visible,
        "enabled": p.enabled,
    }


@router.get("/tree")
async def get_active_tree(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """End-user / workspace tree: only enabled placements of active plugins."""
    return await svc.build_tree(db, include_inactive_plugins=False, admin=False)


@router.get("/tree/manage")
async def get_manage_tree(admin: AdminUser, db: DbSession) -> dict[str, Any]:
    """Admin tree including inactive / disabled placements."""
    return await svc.build_tree(db, include_inactive_plugins=True, admin=True)


@router.get("/slots/{slot}/active")
async def slot_active_tools(slot: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        items = await svc.active_for_slot(db, slot)
        return {"ok": True, "slot": slot, "plugins": items}
    except (ToolTreeError, ValueError) as exc:
        return _err(exc)


@router.post("/categories")
async def create_category(body: CategoryCreate, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        cat = await svc.create_category(
            db,
            name=body.name,
            parent_id=body.parent_id,
            sort_order=body.sort_order,
            actor=admin.email or str(admin.id),
        )
        return _cat(cat)
    except ToolTreeError as exc:
        return _err(exc)


@router.patch("/categories/{category_id}")
async def rename_category(
    category_id: str, body: CategoryRename, admin: AdminUser, db: DbSession
) -> dict[str, Any]:
    try:
        cat = await svc.rename_category(
            db, category_id, body.name, actor=admin.email or str(admin.id)
        )
        return _cat(cat)
    except ToolTreeError as exc:
        return _err(exc)


@router.post("/categories/{category_id}/move")
async def move_category(
    category_id: str, body: CategoryMove, admin: AdminUser, db: DbSession
) -> dict[str, Any]:
    try:
        cat = await svc.move_category(
            db,
            category_id,
            parent_id=body.parent_id,
            sort_order=body.sort_order,
            actor=admin.email or str(admin.id),
        )
        return _cat(cat)
    except ToolTreeError as exc:
        return _err(exc)


@router.post("/categories/reorder")
async def reorder_categories(body: ReorderBody, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        cats = await svc.reorder_categories(
            db,
            body.ordered_ids,
            parent_id=body.parent_id,
            actor=admin.email or str(admin.id),
        )
        return {"ok": True, "categories": [_cat(c) for c in cats]}
    except ToolTreeError as exc:
        return _err(exc)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        return await svc.delete_category(
            db, category_id, actor=admin.email or str(admin.id)
        )
    except ToolTreeError as exc:
        return _err(exc)


@router.post("/placements")
async def upsert_placement(body: PlacementUpsert, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        p = await svc.upsert_placement(
            db,
            plugin_id=body.plugin_id,
            category_id=body.category_id,
            display_name=body.display_name,
            execution_slot=body.execution_slot,
            description=body.description,
            icon=body.icon,
            sort_order=body.sort_order,
            visible=body.visible,
            enabled=body.enabled,
            actor=admin.email or str(admin.id),
        )
        return _placement(p)
    except (ToolTreeError, ValueError) as exc:
        return _err(exc)


@router.post("/placements/{placement_id}/move")
async def move_placement(
    placement_id: str, body: PlacementMove, admin: AdminUser, db: DbSession
) -> dict[str, Any]:
    try:
        p = await svc.move_placement(
            db,
            placement_id,
            category_id=body.category_id,
            sort_order=body.sort_order,
            actor=admin.email or str(admin.id),
        )
        return _placement(p)
    except ToolTreeError as exc:
        return _err(exc)


@router.post("/placements/reorder/{category_id}")
async def reorder_placements(
    category_id: str, body: PlacementReorder, admin: AdminUser, db: DbSession
) -> dict[str, Any]:
    try:
        items = await svc.reorder_placements(
            db,
            category_id,
            body.ordered_ids,
            actor=admin.email or str(admin.id),
        )
        return {"ok": True, "placements": [_placement(p) for p in items]}
    except ToolTreeError as exc:
        return _err(exc)


@router.delete("/placements/{placement_id}")
async def delete_placement(placement_id: str, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        return await svc.delete_placement(
            db, placement_id, actor=admin.email or str(admin.id)
        )
    except ToolTreeError as exc:
        return _err(exc)


@router.post("/tree/snapshot")
async def snapshot(body: SnapshotBody, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    rev = await svc.snapshot_tree(
        db, label=body.label, actor=admin.email or str(admin.id), note=body.note
    )
    return {"ok": True, "id": rev.id, "label": rev.label}


@router.get("/tree/revisions")
async def revisions(admin: AdminUser, db: DbSession) -> dict[str, Any]:
    return {"ok": True, "revisions": await svc.list_revisions(db)}


@router.get("/tree/export")
async def export_tree(admin: AdminUser, db: DbSession) -> dict[str, Any]:
    return await svc.export_config(db)
