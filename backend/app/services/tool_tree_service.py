"""Tool category tree + plugin placement service (plugin-first Host Platform)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tool_tree import (
    MAX_CATEGORY_DEPTH,
    ToolCategory,
    ToolPlacement,
    ToolTreeRevision,
)
from app.plugins.registry import get_plugin, list_plugins
from app.plugins.slots import SUPPORTED_SLOTS, validate_slot
from app.tools.pack_ops import PackOpsError


class ToolTreeError(PackOpsError):
    """Tool tree validation / mutation error."""


def _audit_append(action: str, actor: str | None, **payload: Any) -> None:
    try:
        import json
        import os
        from datetime import datetime, timezone

        from app.tools.pack_paths import audit_log_path

        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "subsystem": "tool_tree",
            "action": action,
            "actor": actor,
            "ok": True,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **payload,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


async def list_categories(session: AsyncSession) -> list[ToolCategory]:
    result = await session.execute(
        select(ToolCategory).options(selectinload(ToolCategory.placements)).order_by(
            ToolCategory.sort_order, ToolCategory.name
        )
    )
    return list(result.scalars().unique().all())


async def _get_category(session: AsyncSession, category_id: str) -> ToolCategory:
    cat = await session.get(ToolCategory, category_id)
    if cat is None:
        raise ToolTreeError(f"category not found: {category_id}")
    return cat


async def _depth_of(session: AsyncSession, category_id: str | None) -> int:
    depth = 0
    seen: set[str] = set()
    cur = category_id
    while cur:
        if cur in seen:
            raise ToolTreeError("circular category relationship detected")
        seen.add(cur)
        cat = await session.get(ToolCategory, cur)
        if cat is None:
            break
        depth += 1
        cur = cat.parent_id
        if depth > MAX_CATEGORY_DEPTH + 2:
            raise ToolTreeError("category depth exceeds safe limit")
    return depth


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    parent_id: str | None = None,
    sort_order: int | None = None,
    actor: str | None = None,
) -> ToolCategory:
    name = (name or "").strip()
    if not name:
        raise ToolTreeError("category name required")
    if len(name) > 128:
        raise ToolTreeError("category name too long")
    if parent_id:
        await _get_category(session, parent_id)
        parent_depth = await _depth_of(session, parent_id)
        if parent_depth >= MAX_CATEGORY_DEPTH:
            raise ToolTreeError(f"max category depth is {MAX_CATEGORY_DEPTH}")
    if sort_order is None:
        q = select(ToolCategory).where(ToolCategory.parent_id == parent_id)
        siblings = list((await session.execute(q)).scalars().all())
        sort_order = (max((s.sort_order for s in siblings), default=-1) + 1)
    cat = ToolCategory(name=name, parent_id=parent_id, sort_order=int(sort_order))
    session.add(cat)
    await session.flush()
    _audit_append("category_create", actor, category_id=cat.id, name=cat.name, parent_id=parent_id)
    return cat


async def rename_category(
    session: AsyncSession, category_id: str, name: str, *, actor: str | None = None
) -> ToolCategory:
    cat = await _get_category(session, category_id)
    name = (name or "").strip()
    if not name:
        raise ToolTreeError("category name required")
    cat.name = name
    await session.flush()
    _audit_append("category_rename", actor, category_id=cat.id, name=name)
    return cat


async def move_category(
    session: AsyncSession,
    category_id: str,
    *,
    parent_id: str | None,
    sort_order: int | None = None,
    actor: str | None = None,
) -> ToolCategory:
    cat = await _get_category(session, category_id)
    if parent_id == category_id:
        raise ToolTreeError("category cannot be its own parent")
    if parent_id:
        # Prevent cycles: parent must not be a descendant of category_id
        walk = parent_id
        seen: set[str] = set()
        while walk:
            if walk == category_id:
                raise ToolTreeError("circular category relationship prevented")
            if walk in seen:
                raise ToolTreeError("circular category relationship detected")
            seen.add(walk)
            parent = await session.get(ToolCategory, walk)
            if parent is None:
                raise ToolTreeError(f"parent category not found: {parent_id}")
            walk = parent.parent_id
        parent_depth = await _depth_of(session, parent_id)
        # estimate subtree depth
        subtree = await _subtree_height(session, category_id)
        if parent_depth + subtree > MAX_CATEGORY_DEPTH:
            raise ToolTreeError(f"move would exceed max depth {MAX_CATEGORY_DEPTH}")
    cat.parent_id = parent_id
    if sort_order is not None:
        cat.sort_order = int(sort_order)
    await session.flush()
    _audit_append(
        "category_move",
        actor,
        category_id=category_id,
        parent_id=parent_id,
        sort_order=cat.sort_order,
    )
    return cat


async def _subtree_height(session: AsyncSession, root_id: str) -> int:
    """Height of subtree rooted at root_id (root counts as 1)."""

    async def height(cid: str) -> int:
        kids = list(
            (
                await session.execute(select(ToolCategory).where(ToolCategory.parent_id == cid))
            ).scalars().all()
        )
        if not kids:
            return 1
        return 1 + max([await height(k.id) for k in kids])

    return await height(root_id)


async def reorder_categories(
    session: AsyncSession,
    ordered_ids: list[str],
    *,
    parent_id: str | None,
    actor: str | None = None,
) -> list[ToolCategory]:
    q = select(ToolCategory).where(ToolCategory.parent_id == parent_id)
    siblings = {c.id: c for c in (await session.execute(q)).scalars().all()}
    if set(ordered_ids) != set(siblings.keys()):
        raise ToolTreeError("reorder must include all siblings under the parent")
    out: list[ToolCategory] = []
    for i, cid in enumerate(ordered_ids):
        siblings[cid].sort_order = i
        out.append(siblings[cid])
    await session.flush()
    _audit_append("category_reorder", actor, parent_id=parent_id, ordered_ids=ordered_ids)
    return out


async def delete_category(
    session: AsyncSession, category_id: str, *, actor: str | None = None
) -> dict[str, Any]:
    cat = await _get_category(session, category_id)
    kids = list(
        (
            await session.execute(select(ToolCategory).where(ToolCategory.parent_id == category_id))
        ).scalars().all()
    )
    if kids:
        raise ToolTreeError("cannot delete category with subcategories")
    placements = list(
        (
            await session.execute(
                select(ToolPlacement).where(ToolPlacement.category_id == category_id)
            )
        ).scalars().all()
    )
    if placements:
        raise ToolTreeError("cannot delete category containing tools; move or remove tools first")
    await session.delete(cat)
    await session.flush()
    _audit_append("category_delete", actor, category_id=category_id, name=cat.name)
    return {"ok": True, "deleted": category_id}


async def upsert_placement(
    session: AsyncSession,
    *,
    plugin_id: str,
    category_id: str,
    display_name: str,
    execution_slot: str,
    description: str | None = None,
    icon: str | None = None,
    sort_order: int | None = None,
    visible: bool = True,
    enabled: bool = True,
    actor: str | None = None,
) -> ToolPlacement:
    plugin_id = (plugin_id or "").strip()
    if not plugin_id:
        raise ToolTreeError("plugin_id required")
    await _get_category(session, category_id)
    slot = validate_slot(execution_slot)
    display_name = (display_name or "").strip() or plugin_id
    rec = get_plugin(plugin_id)
    if not rec or rec.get("installation_status") != "installed":
        raise ToolTreeError(f"plugin not installed: {plugin_id}")

    result = await session.execute(
        select(ToolPlacement).where(ToolPlacement.plugin_id == plugin_id)
    )
    placement = result.scalar_one_or_none()
    created = placement is None
    if placement is None:
        if sort_order is None:
            existing = list(
                (
                    await session.execute(
                        select(ToolPlacement).where(ToolPlacement.category_id == category_id)
                    )
                ).scalars().all()
            )
            sort_order = max((p.sort_order for p in existing), default=-1) + 1
        placement = ToolPlacement(
            plugin_id=plugin_id,
            category_id=category_id,
            display_name=display_name,
            description=description,
            icon=icon,
            sort_order=int(sort_order),
            execution_slot=slot,
            visible=visible,
            enabled=enabled,
        )
        session.add(placement)
    else:
        placement.category_id = category_id
        placement.display_name = display_name
        placement.description = description
        placement.icon = icon
        if sort_order is not None:
            placement.sort_order = int(sort_order)
        placement.execution_slot = slot
        placement.visible = visible
        placement.enabled = enabled
    await session.flush()
    _audit_append(
        "placement_upsert",
        actor,
        plugin_id=plugin_id,
        category_id=category_id,
        execution_slot=slot,
        created=created,
    )
    return placement


async def move_placement(
    session: AsyncSession,
    placement_id: str,
    *,
    category_id: str,
    sort_order: int | None = None,
    actor: str | None = None,
) -> ToolPlacement:
    placement = await session.get(ToolPlacement, placement_id)
    if placement is None:
        raise ToolTreeError(f"placement not found: {placement_id}")
    await _get_category(session, category_id)
    placement.category_id = category_id
    if sort_order is not None:
        placement.sort_order = int(sort_order)
    await session.flush()
    _audit_append(
        "placement_move",
        actor,
        placement_id=placement_id,
        category_id=category_id,
        sort_order=placement.sort_order,
    )
    return placement


async def reorder_placements(
    session: AsyncSession,
    category_id: str,
    ordered_ids: list[str],
    *,
    actor: str | None = None,
) -> list[ToolPlacement]:
    await _get_category(session, category_id)
    result = await session.execute(
        select(ToolPlacement).where(ToolPlacement.category_id == category_id)
    )
    items = {p.id: p for p in result.scalars().all()}
    if set(ordered_ids) != set(items.keys()):
        raise ToolTreeError("reorder must include all tools in the category")
    out: list[ToolPlacement] = []
    for i, pid in enumerate(ordered_ids):
        items[pid].sort_order = i
        out.append(items[pid])
    await session.flush()
    _audit_append("placement_reorder", actor, category_id=category_id, ordered_ids=ordered_ids)
    return out


async def delete_placement(
    session: AsyncSession, placement_id: str, *, actor: str | None = None
) -> dict[str, Any]:
    placement = await session.get(ToolPlacement, placement_id)
    if placement is None:
        raise ToolTreeError(f"placement not found: {placement_id}")
    pid = placement.plugin_id
    await session.delete(placement)
    await session.flush()
    _audit_append("placement_delete", actor, placement_id=placement_id, plugin_id=pid)
    return {"ok": True, "deleted": placement_id}


def _placement_dict(p: ToolPlacement, plugin: dict[str, Any] | None) -> dict[str, Any]:
    active = bool(plugin and plugin.get("activation_status") == "active")
    return {
        "id": p.id,
        "plugin_id": p.plugin_id,
        "category_id": p.category_id,
        "display_name": p.display_name,
        "description": p.description or (plugin or {}).get("description"),
        "icon": p.icon,
        "sort_order": p.sort_order,
        "execution_slot": p.execution_slot,
        "visible": p.visible,
        "enabled": p.enabled,
        "plugin_active": active,
        "plugin_version": (plugin or {}).get("version"),
        "plugin_digest": (plugin or {}).get("digest"),
        "activation_status": (plugin or {}).get("activation_status"),
        "installation_status": (plugin or {}).get("installation_status"),
        "in_active_tree": bool(p.visible and p.enabled and active),
    }


async def build_tree(
    session: AsyncSession,
    *,
    include_inactive_plugins: bool = False,
    admin: bool = False,
) -> dict[str, Any]:
    """Return nested category tree with placements.

    Active user tree excludes disabled/invisible placements and inactive plugins
    unless ``include_inactive_plugins`` (admin manage view).
    """
    cats = await list_categories(session)
    plugins = {p["plugin_id"]: p for p in list_plugins()}
    by_parent: dict[str | None, list[ToolCategory]] = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)
    for lst in by_parent.values():
        lst.sort(key=lambda x: (x.sort_order, x.name.lower()))

    def node(cat: ToolCategory) -> dict[str, Any]:
        placements_out: list[dict[str, Any]] = []
        for p in sorted(cat.placements, key=lambda x: (x.sort_order, x.display_name.lower())):
            plugin = plugins.get(p.plugin_id)
            item = _placement_dict(p, plugin)
            if admin or include_inactive_plugins:
                placements_out.append(item)
            elif item["in_active_tree"]:
                placements_out.append(item)
        children = [node(ch) for ch in by_parent.get(cat.id, [])]
        # Drop empty branches for end-user view (keep for admin)
        if not admin and not include_inactive_plugins:
            children = [ch for ch in children if ch["placements"] or ch["children"]]
        return {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "sort_order": cat.sort_order,
            "collapsed_default": cat.collapsed_default,
            "placements": placements_out,
            "children": children,
        }

    roots = [node(c) for c in by_parent.get(None, [])]
    if not admin and not include_inactive_plugins:
        roots = [r for r in roots if r["placements"] or r["children"]]
    return {
        "ok": True,
        "plugin_first": True,
        "supported_slots": sorted(SUPPORTED_SLOTS),
        "max_category_depth": MAX_CATEGORY_DEPTH,
        "empty": len(roots) == 0,
        "roots": roots,
        "message": (
            "No tools installed. Create a category or upload your first tool."
            if len(roots) == 0
            else None
        ),
    }


async def active_for_slot(session: AsyncSession, slot: str) -> list[dict[str, Any]]:
    validate_slot(slot)
    result = await session.execute(select(ToolPlacement).where(ToolPlacement.execution_slot == slot))
    placements = list(result.scalars().all())
    out: list[dict[str, Any]] = []
    for p in sorted(placements, key=lambda x: (x.sort_order, x.display_name.lower())):
        if not (p.visible and p.enabled):
            continue
        plugin = get_plugin(p.plugin_id)
        if not plugin or plugin.get("activation_status") != "active":
            continue
        out.append(
            {
                **_placement_dict(p, plugin),
                "name": p.display_name,
                "frontend_slot": p.execution_slot,
                "version": plugin.get("version"),
                "digest": plugin.get("digest"),
                "permissions": plugin.get("permissions") or [],
            }
        )
    return out


async def snapshot_tree(
    session: AsyncSession, *, label: str, actor: str | None = None, note: str | None = None
) -> ToolTreeRevision:
    tree = await build_tree(session, include_inactive_plugins=True, admin=True)
    rev = ToolTreeRevision(label=label, actor=actor, note=note, snapshot=tree)
    session.add(rev)
    await session.flush()
    _audit_append("tree_snapshot", actor, revision_id=rev.id, label=label)
    return rev


async def list_revisions(session: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    result = await session.execute(
        select(ToolTreeRevision).order_by(ToolTreeRevision.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": r.id,
            "label": r.label,
            "actor": r.actor,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in result.scalars().all()
    ]


async def export_config(session: AsyncSession) -> dict[str, Any]:
    return await build_tree(session, include_inactive_plugins=True, admin=True)
