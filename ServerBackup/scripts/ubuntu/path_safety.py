"""Unix path safety for Ubuntu helpers.

Reject shell injection and root escape. Do not reject legitimate filenames
that contain repeated dots, hyphens, spaces, or long names.
"""

from __future__ import annotations

import os

UNSAFE_CHARS = set(";&|`$<>\\\n\r\x00")
MAX_PATH_LEN = 4096


def has_unsafe_chars(path: str) -> bool:
    return any(ch in path for ch in UNSAFE_CHARS)


def has_traversal_component(path: str) -> bool:
    """True only when a path segment is exactly '..', not 'file..jpg'."""
    return any(part == ".." for part in str(path).replace("\\", "/").split("/") if part)


def lexical_normalize(path: str) -> str:
    if not path.startswith("/"):
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


def is_safe_unix_syntax(path: str) -> bool:
    if not path or not path.startswith("/") or path.startswith("//"):
        return False
    if has_unsafe_chars(path):
        return False
    if len(path) > MAX_PATH_LEN:
        return False
    return True


def contained_in_root(path: str, root: str, *, follow_symlinks: bool = True) -> bool:
    """Return True if path is the root or a descendant after normalization."""
    if not path or not root:
        return False
    try:
        if follow_symlinks:
            candidate = os.path.realpath(path)
            base = os.path.realpath(root)
        else:
            candidate = lexical_normalize(path)
            base = lexical_normalize(root)
    except OSError:
        return False
    base = base.rstrip("/") or "/"
    candidate = candidate.rstrip("/") or "/"
    if candidate == base:
        return True
    if base == "/":
        return candidate.startswith("/")
    return candidate.startswith(base + "/")


def symlink_escapes_root(path: str, root: str) -> bool:
    """Lexical path is inside root, but realpath is not (escaping symlink)."""
    if not os.path.lexists(path):
        return False
    return contained_in_root(path, root, follow_symlinks=False) and not contained_in_root(
        path, root, follow_symlinks=True
    )


def explain_uncontained(path: str, roots: list[str]) -> str:
    if any(symlink_escapes_root(path, root) for root in roots):
        return f"symlink escapes approved root: {path}"
    return f"path not under approved source: {path}"


def require_unix_syntax(path: str) -> str:
    cleaned = (path or "").strip()
    if not is_safe_unix_syntax(cleaned):
        raise ValueError(f"Refusing unsafe path: {cleaned!r}")
    return cleaned.rstrip("/") or "/"
