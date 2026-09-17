"""Validate backup paths so they cannot be used for command injection.

Path traversal is detected from '..' path *components* and from canonical
root containment. A filename such as 'techniques..jpg' is not traversal.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SHELL_UNSAFE = re.compile(r"[;&|`$<>\\]")
MAX_UNIX_PATH = 4096


class PathValidationError(ValueError):
    pass


def has_traversal_component(path: str) -> bool:
    """True only when a segment is exactly '..', not 'file..jpg'."""
    return any(part == ".." for part in str(path).replace("\\", "/").split("/") if part)


def lexical_normalize_unix(path: str) -> str:
    if not str(path).startswith("/"):
        return path
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/" + "/".join(parts)


def is_safe_unix_path(path: str) -> bool:
    if not path or not path.startswith("/") or path.startswith("//"):
        return False
    if "\x00" in path or "\n" in path or "\r" in path:
        return False
    if _SHELL_UNSAFE.search(path):
        return False
    if has_traversal_component(path):
        return False
    if len(path) > MAX_UNIX_PATH:
        return False
    return True


def contained_in_unix_root(path: str, root: str, *, follow_symlinks: bool = True) -> bool:
    """True if path is root or a descendant after canonicalization."""
    if not path or not root:
        return False
    try:
        if follow_symlinks:
            candidate = os.path.realpath(path)
            base = os.path.realpath(root)
        else:
            candidate = lexical_normalize_unix(path)
            base = lexical_normalize_unix(root)
    except OSError:
        return False
    base = base.rstrip("/") or "/"
    candidate = candidate.rstrip("/") or "/"
    if candidate == base:
        return True
    if base == "/":
        return candidate.startswith("/")
    return candidate.startswith(base + "/")


def validate_unix_path(path: str, *, field: str = "path") -> str:
    cleaned = (path or "").strip()
    if not is_safe_unix_path(cleaned):
        raise PathValidationError(f"Invalid {field}: {cleaned!r}")
    return cleaned.rstrip("/") or "/"


def is_safe_windows_path(path: str) -> bool:
    if not path or "\x00" in path:
        return False
    try:
        parsed = Path(path)
    except (OSError, ValueError):
        return False
    text = str(parsed)
    if any(ch in text for ch in ["\n", "\r", "&", "|", "<", ">", "`"]):
        return False
    return True


def validate_windows_path(path: str, *, field: str = "path") -> str:
    cleaned = (path or "").strip()
    if not is_safe_windows_path(cleaned):
        raise PathValidationError(f"Invalid {field}: {cleaned!r}")
    return str(Path(cleaned))


def expand_user_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))
