"""Master generation tree (path → object)."""

from __future__ import annotations

from typing import Any

STATE_ACTIVE = "ACTIVE"
STATE_DELETED = "DELETED"
STATE_RENAMED = "RENAMED"


def file_key(source_root: str, relative_path: str) -> str:
    root = source_root.rstrip("/")
    rel = relative_path.replace("\\", "/").lstrip("/")
    return f"{root}/{rel}" if rel else root


def make_record(
    *,
    source_root: str,
    relative_path: str,
    file_type: str = "file",
    size: int = 0,
    mtime: int | float = 0,
    mode: int = 0,
    uid: int = 0,
    gid: int = 0,
    inode: int | None = None,
    sha256: str | None = None,
    state: str = STATE_ACTIVE,
    generation: int = 1,
    first_seen: str | None = None,
    last_seen: str | None = None,
    old_path: str | None = None,
    category: str = "file",
) -> dict[str, Any]:
    return {
        "relative_path": relative_path.replace("\\", "/").lstrip("/"),
        "source_root": source_root.rstrip("/"),
        "type": file_type,
        "size": int(size),
        "mtime": int(mtime),
        "mode": int(mode),
        "uid": int(uid),
        "gid": int(gid),
        "inode": inode,
        "sha256": (sha256 or "").lower() or None,
        "state": state,
        "generation": int(generation),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "old_path": old_path,
        "category": category,
    }


def index_active(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = tree.get("files") if isinstance(tree, dict) else None
    if not isinstance(files, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        if str(item.get("state") or STATE_ACTIVE) != STATE_ACTIVE:
            continue
        indexed[file_key(str(item.get("source_root") or ""), str(item.get("relative_path") or ""))] = item
    return indexed
