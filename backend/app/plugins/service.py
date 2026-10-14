"""Load, install, and merge built-in and uploaded tool plugins."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.plugin import PluginInstall
from app.models.user import User
from app.plugins.builtin import BUILTIN_BY_ID, BUILTIN_PLUGINS, MAX_PLUGIN_BYTES, PLUGIN_ID_RE

ID_RE = re.compile(PLUGIN_ID_RE)


def plugins_root() -> Path:
    root = Path(get_settings().upload_dir) / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    return root


def plugin_dir(plugin_id: str) -> Path:
    return plugins_root() / plugin_id


def _safe_id(value: str) -> str:
    slug = (value or "").strip().lower()
    if not ID_RE.match(slug):
        raise ValueError(
            "Plugin id must be lowercase letters, numbers, and hyphens (2–63 characters)."
        )
    return slug


def _user_may_open(user: User, service: str) -> bool:
    key = (service or "open").strip().lower()
    if key in ("", "open", "everyone"):
        return True
    if key in ("admin", "operator"):
        return user.is_full_admin()
    return user.has_service(key)


def _payload_from_builtin(row: dict[str, Any], install: Optional[PluginInstall] = None) -> dict[str, Any]:
    enabled = True if install is None else bool(install.enabled)
    overridden = bool(install and install.source == "uploaded")
    entry = (install.entry if overridden else "") or ""
    route = f"/tools/{row['id']}" if overridden else row["route"]
    return {
        "id": row["id"],
        "name": install.name if overridden else row["name"],
        "description": install.description if overridden else row["description"],
        "version": install.version if overridden else row["version"],
        "service": row["service"],
        "route": route,
        "icon": row["icon"],
        "kind": "uploaded" if overridden else "builtin",
        "enabled": enabled,
        "entry": entry,
        "overridden": overridden,
        "package": row.get("package") or "",
        "uploaded_by": install.uploaded_by if install else None,
    }


def _payload_from_install(install: PluginInstall) -> dict[str, Any]:
    return {
        "id": install.plugin_id,
        "name": install.name,
        "description": install.description or "",
        "version": install.version or "1.0.0",
        "service": install.service or "open",
        "route": f"/tools/{install.plugin_id}",
        "icon": install.icon or "puzzle",
        "kind": "uploaded",
        "enabled": bool(install.enabled),
        "entry": install.entry or "index.html",
        "overridden": install.plugin_id in BUILTIN_BY_ID,
        "package": "",
        "uploaded_by": install.uploaded_by,
    }


async def catalog(db: AsyncSession, user: User, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    rows = list((await db.execute(select(PluginInstall))).scalars().all())
    by_id = {row.plugin_id: row for row in rows}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for builtin in BUILTIN_PLUGINS:
        item = _payload_from_builtin(builtin, by_id.get(builtin["id"]))
        seen.add(item["id"])
        if not include_disabled:
            if not item["enabled"] or not _user_may_open(user, item["service"]):
                continue
        out.append(item)
    for install in rows:
        if install.plugin_id in seen:
            continue
        item = _payload_from_install(install)
        if not include_disabled:
            if not item["enabled"] or not _user_may_open(user, item["service"]):
                continue
        out.append(item)
    return out


def _read_manifest(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    plugin_id = _safe_id(str(raw.get("id") or fallback_id))
    name = str(raw.get("name") or plugin_id).strip()[:200]
    if not name:
        raise ValueError("manifest.json needs a name")
    entry = str(raw.get("entry") or "index.html").replace("\\", "/").lstrip("/")
    if ".." in entry.split("/"):
        raise ValueError("Plugin entry path is not allowed")
    service = str(raw.get("service") or "open").strip().lower() or "open"
    return {
        "id": plugin_id,
        "name": name,
        "description": str(raw.get("description") or "").strip()[:2000],
        "version": str(raw.get("version") or "1.0.0").strip()[:40],
        "service": service[:40],
        "icon": str(raw.get("icon") or "puzzle").strip()[:40],
        "entry": entry or "index.html",
    }


def _unzip_plugin(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    if len(data) > MAX_PLUGIN_BYTES:
        raise ValueError("Plugin zip is larger than 20 MB")
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Upload a .zip plugin package") from exc
    names = [
        name
        for name in archive.namelist()
        if name and not name.startswith("__MACOSX/") and not name.split("/")[-1].startswith("._")
    ]
    if not names:
        raise ValueError("The zip is empty")
    manifest_name = next((n for n in names if n == "manifest.json" or n.endswith("/manifest.json")), None)
    if not manifest_name:
        raise ValueError("The zip must contain manifest.json")
    prefix = ""
    if "/" in manifest_name:
        prefix = manifest_name.rsplit("/", 1)[0] + "/"
    try:
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must be an object")
    fallback = prefix.strip("/").split("/")[-1] if prefix else "plugin"
    spec = _read_manifest(manifest, fallback)
    files: dict[str, bytes] = {}
    for name in names:
        if name.endswith("/"):
            continue
        rel = name[len(prefix) :] if prefix and name.startswith(prefix) else name
        if not rel or rel == "manifest.json":
            if rel == "manifest.json":
                files[rel] = archive.read(name)
            continue
        parts = Path(rel).parts
        if any(part in ("", "..") or part.startswith("/") for part in parts):
            raise ValueError(f"Unsafe path in zip: {name}")
        files[rel] = archive.read(name)
    files["manifest.json"] = archive.read(manifest_name)
    entry = spec["entry"]
    if entry not in files:
        raise ValueError(f"manifest entry {entry!r} is missing from the zip")
    return spec, files


def _write_files(plugin_id: str, files: dict[str, bytes]) -> None:
    dest = plugin_dir(plugin_id)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, blob in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)


async def install_zip(
    db: AsyncSession, data: bytes, *, uploaded_by: str
) -> dict[str, Any]:
    spec, files = _unzip_plugin(data)
    plugin_id = spec["id"]
    _write_files(plugin_id, files)
    row = (
        await db.execute(select(PluginInstall).where(PluginInstall.plugin_id == plugin_id))
    ).scalar_one_or_none()
    if row is None:
        row = PluginInstall(plugin_id=plugin_id)
        db.add(row)
    row.name = spec["name"]
    row.description = spec["description"]
    row.version = spec["version"]
    if plugin_id in BUILTIN_BY_ID:
        row.service = BUILTIN_BY_ID[plugin_id]["service"]
    else:
        row.service = spec["service"]
    row.icon = spec["icon"]
    row.entry = spec["entry"]
    row.enabled = True
    row.source = "uploaded"
    row.uploaded_by = uploaded_by
    await db.flush()
    if plugin_id in BUILTIN_BY_ID:
        return _payload_from_builtin(BUILTIN_BY_ID[plugin_id], row)
    return _payload_from_install(row)


async def set_enabled(db: AsyncSession, plugin_id: str, enabled: bool) -> dict[str, Any]:
    plugin_id = _safe_id(plugin_id)
    row = (
        await db.execute(select(PluginInstall).where(PluginInstall.plugin_id == plugin_id))
    ).scalar_one_or_none()
    if row is None:
        if plugin_id not in BUILTIN_BY_ID:
            raise KeyError(plugin_id)
        builtin = BUILTIN_BY_ID[plugin_id]
        row = PluginInstall(
            plugin_id=plugin_id,
            name=builtin["name"],
            description=builtin["description"],
            version=builtin["version"],
            service=builtin["service"],
            icon=builtin["icon"],
            source="builtin",
            enabled=enabled,
        )
        db.add(row)
    else:
        row.enabled = enabled
    await db.flush()
    if plugin_id in BUILTIN_BY_ID:
        return _payload_from_builtin(BUILTIN_BY_ID[plugin_id], row)
    return _payload_from_install(row)


async def remove_upload(db: AsyncSession, plugin_id: str) -> dict[str, Any]:
    plugin_id = _safe_id(plugin_id)
    row = (
        await db.execute(select(PluginInstall).where(PluginInstall.plugin_id == plugin_id))
    ).scalar_one_or_none()
    dest = plugin_dir(plugin_id)
    if dest.exists():
        shutil.rmtree(dest)
    if row is not None:
        if plugin_id in BUILTIN_BY_ID:
            row.source = "builtin"
            row.entry = ""
            row.uploaded_by = None
            row.enabled = True
            row.name = BUILTIN_BY_ID[plugin_id]["name"]
            row.description = BUILTIN_BY_ID[plugin_id]["description"]
            row.version = BUILTIN_BY_ID[plugin_id]["version"]
            await db.flush()
            return _payload_from_builtin(BUILTIN_BY_ID[plugin_id], row)
        await db.delete(row)
        await db.flush()
        return {"id": plugin_id, "removed": True}
    if plugin_id in BUILTIN_BY_ID:
        return _payload_from_builtin(BUILTIN_BY_ID[plugin_id], None)
    raise KeyError(plugin_id)
