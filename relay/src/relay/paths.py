"""Path checks for remote listings and the local staging directory."""

from __future__ import annotations

import re
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class PathError(ValueError):
    """A remote or local path is not safe to use."""


def check_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise PathError(
            f"id {value!r} must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, and hyphens"
        )
    if value == "all":
        raise PathError("id 'all' is reserved")
    return value


def check_relative(path: str) -> str:
    if not path or path.startswith("/"):
        raise PathError(f"relative path {path!r} is not allowed")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathError(f"relative path {path!r} is not allowed")
    return path


def remote_join(root: str, relative: str) -> str:
    check_relative(relative)
    cleaned = root.rstrip("/")
    if not cleaned:
        raise PathError("remote directory is empty")
    return f"{cleaned}/{relative}"


def local_path_for(staging_dir: Path, source_id: str, relative: str) -> Path:
    check_id(source_id)
    check_relative(relative)
    root = staging_dir.resolve()
    path = (root / source_id / relative).resolve()
    if path != root and root not in path.parents:
        raise PathError(f"path escapes staging: {relative}")
    return path


def prepare_local_download(local_path: Path, expected_size: int) -> int | None:
    """Return the byte offset to resume from.

    ``None`` means the local file is already the expected size.
    A local file larger than the remote object is discarded.
    """
    if expected_size < 0:
        raise PathError("expected size is negative")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not local_path.exists():
        return 0
    current = local_path.stat().st_size
    if current == expected_size:
        return None
    if current > expected_size:
        local_path.unlink()
        return 0
    return current


def mtime_key(mtime: float) -> str:
    return f"{mtime:.6f}"
