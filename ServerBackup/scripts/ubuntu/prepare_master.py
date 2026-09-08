#!/usr/bin/env python3
"""Master-backup helper actions. Read-only against production trees.

Never copies large OJS trees into /tmp. Never stops MariaDB/Nginx/PHP-FPM/Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
import struct
import sys
from pathlib import Path

UNSAFE = set(";&|`$<>\\\n\r")
SKIP_NAMES = {".git"}
CHUNK = 1024 * 1024
MAGIC = b"SB01"
_FILES_DIR = re.compile(r"^\s*files_dir\s*=\s*(.*)$", re.IGNORECASE)
_VERSION = re.compile(r"^\s*version\s*=\s*(.*)$", re.IGNORECASE)
DEFAULT_FALLBACK = "/var/www/ojs-files"


def fail(message: str, code: int = 1) -> None:
    sys.stderr.write(message + "\n")
    if os.environ.get("SERVERBACKUP_STREAM") != "1":
        json.dump({"ok": False, "error": message}, sys.stdout)
        sys.stdout.write("\n")
    raise SystemExit(code)


def safe_unix(path: str) -> str:
    if not path or not path.startswith("/") or ".." in path or any(ch in path for ch in UNSAFE):
        fail(f"Refusing unsafe path: {path!r}")
    return path.rstrip("/") or "/"


def _strip_value(raw: str) -> str:
    value = raw.strip()
    if ";" in value and not (value.startswith('"') or value.startswith("'")):
        value = value.split(";", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def parse_files_dir(config_text: str) -> str | None:
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = _FILES_DIR.match(stripped)
        if not match:
            continue
        return _strip_value(match.group(1)) or None
    return None


def parse_ojs_version(config_text: str) -> str:
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = _VERSION.match(stripped)
        if match:
            value = _strip_value(match.group(1))
            if value:
                return value
    return "unknown"


def resolve_files_dir(raw: str, application_path: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        fail("OJS files_dir is empty")
    if cleaned.startswith("/"):
        return safe_unix(cleaned)
    return safe_unix(str(Path(application_path.rstrip("/")) / cleaned))


def _dir_stats(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    if not path.is_dir():
        return 0, 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_NAMES]
        for name in names:
            file_path = Path(root) / name
            try:
                info = file_path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                files += 1
                size += int(info.st_size)
    return size, files


def discover_ojs(payload: dict) -> dict:
    websites = [safe_unix(p) for p in payload.get("website_directories") or []]
    installations = []
    errors = []
    for app in websites:
        config_path = Path(app) / "config.inc.php"
        if not config_path.is_file():
            continue
        text = config_path.read_text(encoding="utf-8", errors="replace")
        raw = parse_files_dir(text)
        domain = Path(app).name
        if not raw:
            errors.append(f"{app}: config.inc.php has no files_dir")
            installations.append(
                {
                    "domain": domain,
                    "application_path": app,
                    "config_path": str(config_path),
                    "ojs_version": parse_ojs_version(text),
                    "files_dir_raw": "",
                    "files_dir": "",
                    "exists": False,
                    "size_bytes": 0,
                    "file_count": 0,
                }
            )
            continue
        resolved = resolve_files_dir(raw, app)
        if resolved == DEFAULT_FALLBACK and raw not in {DEFAULT_FALLBACK, DEFAULT_FALLBACK + "/"}:
            errors.append(f"{app}: refusing silent fallback to {DEFAULT_FALLBACK}")
        dest = Path(resolved)
        exists = dest.is_dir()
        size_bytes, file_count = _dir_stats(dest) if exists else (0, 0)
        if not exists:
            errors.append(f"{app}: files_dir {resolved} does not exist")
        installations.append(
            {
                "domain": domain,
                "application_path": app,
                "config_path": str(config_path),
                "ojs_version": parse_ojs_version(text),
                "files_dir_raw": raw,
                "files_dir": resolved,
                "exists": exists,
                "size_bytes": size_bytes,
                "file_count": file_count,
            }
        )
    ok = not errors
    result = {
        "ok": ok,
        "hostname": socket.gethostname(),
        "installations": installations,
        "errors": errors,
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def _allowed(path: str, roots: list[str]) -> bool:
    cleaned = safe_unix(path)
    for root in roots:
        base = root.rstrip("/")
        if cleaned == base or cleaned.startswith(base + "/"):
            return True
    return False


def inventory(payload: dict) -> dict:
    sources = payload.get("sources") or []
    files = []
    errors = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        root = safe_unix(str(source.get("root") or ""))
        category = str(source.get("category") or "file")
        path = Path(root)
        if not path.exists():
            errors.append(f"missing source {root}")
            continue
        if path.is_file():
            info = path.lstat()
            files.append(_file_record(root, ".", info, category, path))
            continue
        for walk_root, dirs, names in os.walk(path, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_NAMES]
            for name in names:
                file_path = Path(walk_root) / name
                try:
                    info = file_path.lstat()
                except OSError as exc:
                    errors.append(f"{file_path}: {exc}")
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                rel = str(file_path.relative_to(path)).replace("\\", "/")
                files.append(_file_record(root, rel, info, category, file_path))
    return {
        "ok": not errors,
        "files": files,
        "errors": errors,
        "file_count": len(files),
        "bytes": int(sum(int(item["size"]) for item in files)),
    }


def _file_record(root: str, relative: str, info: os.stat_result, category: str, path: Path) -> dict:
    return {
        "source_root": root,
        "relative_path": relative,
        "type": "file",
        "size": int(info.st_size),
        "mtime": int(info.st_mtime),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "inode": int(info.st_ino),
        "category": category,
        "absolute_path": str(path),
    }


def hash_files(payload: dict) -> dict:
    roots = [safe_unix(p) for p in payload.get("allowed_roots") or []]
    hashes = []
    errors = []
    for raw in payload.get("paths") or []:
        path = safe_unix(str(raw))
        if roots and not _allowed(path, roots):
            errors.append(f"path not under approved source: {path}")
            continue
        file_path = Path(path)
        if not file_path.is_file():
            errors.append(f"missing file {path}")
            continue
        digest = hashlib.sha256()
        size = 0
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        hashes.append({"path": path, "sha256": digest.hexdigest(), "size": size})
    return {"ok": not errors, "hashes": hashes, "errors": errors}


def stream_objects(payload: dict) -> None:
    """Never load a whole OJS tree into memory. Hash, then stream."""
    stream_objects_lowmem(payload)


def stream_objects_lowmem(payload: dict) -> None:
    """Hash first then stream so memory stays bounded for large files."""
    os.environ["SERVERBACKUP_STREAM"] = "1"
    roots = [safe_unix(p) for p in payload.get("allowed_roots") or []]
    stdout = sys.stdout.buffer
    stdout.write(MAGIC)
    for item in payload.get("files") or []:
        path = safe_unix(str(item.get("path") or item.get("absolute_path") or item))
        if roots and not _allowed(path, roots):
            fail(f"path not under approved source: {path}")
        file_path = Path(path)
        if not file_path.is_file():
            fail(f"missing file {path}")
        hasher = hashlib.sha256()
        size = 0
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
                size += len(chunk)
        digest = hasher.hexdigest()
        encoded = path.encode("utf-8")
        stdout.write(struct.pack(">I", len(encoded)))
        stdout.write(encoded)
        stdout.write(struct.pack(">Q", int(size)))
        stdout.write(bytes.fromhex(digest))
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                stdout.write(chunk)
    stdout.write(struct.pack(">I", 0))
    stdout.flush()


def database_fingerprint(payload: dict, run, mysql_defaults) -> dict:
    names = list(payload.get("databases") or [])
    fingerprints = []
    errors = []
    for name in names:
        if any(ch in name for ch in UNSAFE) or "/" in name or " " in name:
            errors.append(f"unsafe database name {name!r}")
            continue
        status = run(["mysql", *mysql_defaults(), "--batch", "--skip-column-names", name, "-e", "SHOW TABLE STATUS"])
        create = run(["mysql", *mysql_defaults(), "--batch", "--skip-column-names", name, "-e", "SHOW TABLES"])
        if status.returncode != 0:
            errors.append(status.stderr.strip() or f"fingerprint failed for {name}")
            continue
        blob = (status.stdout or "") + "\n" + (create.stdout or "")
        digest = hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()
        fingerprints.append({"name": name, "sha256": digest, "bytes": len(blob.encode("utf-8", errors="replace"))})
    return {"ok": not errors, "fingerprints": fingerprints, "errors": errors}


def handle(action: str, payload: dict, *, run=None, mysql_defaults=None) -> dict | None:
    if action == "discover-ojs":
        return discover_ojs(payload)
    if action == "inventory":
        return inventory(payload)
    if action == "hash-files":
        return hash_files(payload)
    if action == "stream-objects":
        stream_objects_lowmem(payload)
        return None
    if action == "database-fingerprint":
        if run is None or mysql_defaults is None:
            fail("database fingerprint requires mysql helpers")
        return database_fingerprint(payload, run, mysql_defaults)
    fail(f"unhandled master action {action}")
    return None
