"""Validate backup paths so they cannot be used for command injection."""

from __future__ import annotations

import os
import re
from pathlib import Path

_UNIX_PATH = re.compile(r"^/([A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*)?/?$")
_UNSAFE_UNIX = re.compile(r"[;&|`$<>\\]|(\.\.)")


class PathValidationError(ValueError):
    pass


def is_safe_unix_path(path: str) -> bool:
    if not path or not path.startswith("/"):
        return False
    if _UNSAFE_UNIX.search(path):
        return False
    if "\x00" in path or "\n" in path or "\r" in path:
        return False
    return bool(_UNIX_PATH.match(path.rstrip("/")) or path == "/")


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
