"""Opaque plugin upload staging (Stage P1.1).

Server-generated staging IDs only — no client-supplied filesystem paths.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from app.tools.pack_ops import PackOpsError
from app.tools.pack_paths import staging_root

# Upload / archive limits (fail closed).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 200
MAX_DECOMPRESSED_BYTES = 40 * 1024 * 1024
STAGING_TTL_SECONDS = 60 * 60  # 1 hour
STAGING_ID_RE = __import__("re").compile(r"^[a-f0-9]{32}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def staging_base() -> Path:
    root = staging_root() / "plugin_uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_staging_id() -> str:
    return secrets.token_hex(16)


def staging_dir(staging_id: str) -> Path:
    if not STAGING_ID_RE.match(staging_id or ""):
        raise PackOpsError("invalid staging_id")
    return staging_base() / staging_id


def manifest_path(staging_id: str) -> Path:
    return staging_dir(staging_id) / "staging.json"


def pack_root_path(staging_id: str) -> Path:
    return staging_dir(staging_id) / "pack"


def expire_stale_staging(*, now: float | None = None) -> int:
    """Delete expired staging directories. Returns number removed."""
    now = time.time() if now is None else now
    removed = 0
    base = staging_base()
    if not base.is_dir():
        return 0
    for child in base.iterdir():
        if not child.is_dir():
            continue
        meta = child / "staging.json"
        expired = False
        if meta.is_file():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                exp = float(data.get("expires_at_epoch") or 0)
                if exp and now > exp:
                    expired = True
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                # Corrupt staging — remove
                expired = True
        else:
            # No manifest and older than TTL by mtime
            try:
                if now - child.stat().st_mtime > STAGING_TTL_SECONDS:
                    expired = True
            except OSError:
                expired = True
        if expired:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def _safe_zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise PackOpsError(f"archive entry count exceeds limit ({MAX_ARCHIVE_ENTRIES})")
    total_uncompressed = 0
    safe: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename
        if not name or name.endswith("/"):
            continue
        # Traversal / absolute
        if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
            raise PackOpsError(f"unsafe zip path: {name}")
        # Symlink / special (ZipInfo flag bits / external attrs on Unix)
        if info.external_attr and ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise PackOpsError(f"symlinks not allowed in zip: {name}")
        if info.is_dir():
            continue
        total_uncompressed += int(info.file_size or 0)
        if total_uncompressed > MAX_DECOMPRESSED_BYTES:
            raise PackOpsError(
                f"decompressed size exceeds limit ({MAX_DECOMPRESSED_BYTES} bytes)"
            )
        safe.append(info)
    if not safe:
        raise PackOpsError("zip contains no files")
    return safe


def stream_upload_to_staging(stream: BinaryIO, *, max_bytes: int = MAX_UPLOAD_BYTES) -> str:
    """Read upload with a hard size cap into a new opaque staging directory."""
    expire_stale_staging()
    staging_id = new_staging_id()
    dest = staging_dir(staging_id)
    dest.mkdir(parents=True, exist_ok=False)
    zip_path = dest / "upload.zip"
    written = 0
    with zip_path.open("wb") as out:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                shutil.rmtree(dest, ignore_errors=True)
                raise PackOpsError(f"upload too large (max {max_bytes} bytes)")
            out.write(chunk)
    if written == 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackOpsError("empty upload")

    extract_to = dest / "extracted"
    extract_to.mkdir()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if zf.testzip() is not None:
                raise PackOpsError("corrupt zip archive")
            members = _safe_zip_members(zf)
            for info in members:
                # Extract file-by-file with size accounting
                target = extract_to / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise PackOpsError(f"refusing overwrite/symlink: {info.filename}")
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    remaining = int(info.file_size or 0)
                    while remaining > 0:
                        buf = src.read(min(64 * 1024, remaining))
                        if not buf:
                            break
                        dst.write(buf)
                        remaining -= len(buf)
                if target.is_symlink():
                    raise PackOpsError(f"symlink created during extract: {info.filename}")
    except zipfile.BadZipFile as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackOpsError("invalid zip archive") from exc
    except PackOpsError:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    candidates = sorted(extract_to.rglob("pack.json"), key=lambda p: len(p.parts))
    if not candidates:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackOpsError("zip missing pack.json")
    pack_src = candidates[0].parent
    # Reject if pack tree contains symlinks
    for p in pack_src.rglob("*"):
        if p.is_symlink():
            shutil.rmtree(dest, ignore_errors=True)
            raise PackOpsError(f"symlinks not allowed in pack: {p.relative_to(pack_src)}")

    pack_dst = pack_root_path(staging_id)
    shutil.copytree(pack_src, pack_dst, symlinks=False)

    expires = time.time() + STAGING_TTL_SECONDS
    write_staging_manifest(
        staging_id,
        {
            "staging_id": staging_id,
            "created_at": _now_iso(),
            "expires_at_epoch": expires,
            "upload_bytes": written,
            "validated": False,
            "digest": None,
            "plugin_id": None,
            "version": None,
        },
    )
    return staging_id


def write_staging_manifest(staging_id: str, data: dict[str, Any]) -> None:
    path = manifest_path(staging_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_staging_manifest(staging_id: str) -> dict[str, Any]:
    expire_stale_staging()
    path = manifest_path(staging_id)
    if not path.is_file():
        raise PackOpsError("unknown or expired staging_id")
    data = json.loads(path.read_text(encoding="utf-8"))
    exp = float(data.get("expires_at_epoch") or 0)
    if exp and time.time() > exp:
        shutil.rmtree(staging_dir(staging_id), ignore_errors=True)
        raise PackOpsError("staging_id expired")
    return data


def require_validated_staging(staging_id: str, *, expected_digest: str) -> tuple[Path, dict[str, Any]]:
    """Return pack root only if staging was validated and digest matches."""
    meta = load_staging_manifest(staging_id)
    if not meta.get("validated"):
        raise PackOpsError("staging_id not validated")
    if not expected_digest or not str(expected_digest).startswith("sha256:"):
        raise PackOpsError("expected_digest required (sha256:...)")
    if meta.get("digest") != expected_digest:
        raise PackOpsError("digest mismatch vs validated staging artifact")
    root = pack_root_path(staging_id)
    if not root.is_dir():
        raise PackOpsError("staging pack missing")
    return root, meta
