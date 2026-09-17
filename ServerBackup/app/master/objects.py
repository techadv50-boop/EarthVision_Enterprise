"""SHA-256 content-addressed objects. Already-compressed types are stored as-is."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.backup.checksum import sha256_file

CHUNK = 1024 * 1024
SKIP_RECOMPRESS = {".pdf", ".zip", ".jpg", ".jpeg", ".png", ".mp4", ".docx", ".gz", ".tgz", ".7z"}


def object_path(root: Path, digest: str) -> Path:
    digest = digest.lower()
    return Path(root) / "objects" / digest[:2] / digest


def has_object(root: Path, digest: str) -> bool:
    """True when the content-addressed object file exists.

    Empty files are valid objects (SHA-256 of zero bytes). A zero-length
    object must not be reported as missing.
    """
    if not digest:
        return False
    path = object_path(root, digest)
    return path.is_file()


def write_object_from_file(root: Path, source: Path, *, expected: str | None = None) -> str:
    digest = sha256_file(source)
    if expected and expected.lower() != digest:
        raise ValueError(f"Object hash mismatch: expected {expected}, got {digest}")
    dest = object_path(root, digest)
    if dest.is_file():
        return digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with source.open("rb") as src, tmp.open("wb") as handle:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            handle.write(chunk)
    os.replace(tmp, dest)
    return digest


def write_object_from_bytes(root: Path, data: bytes, *, expected: str | None = None) -> str:
    digest = hashlib.sha256(data).hexdigest()
    if expected and expected.lower() != digest:
        raise ValueError(f"Object hash mismatch: expected {expected}, got {digest}")
    dest = object_path(root, digest)
    if dest.is_file():
        return digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return digest


def verify_object(root: Path, digest: str) -> bool:
    path = object_path(root, digest)
    if not path.is_file():
        return False
    return sha256_file(path) == digest.lower()
