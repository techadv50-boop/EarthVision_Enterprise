#!/usr/bin/env python3
"""Apply a master object pack on Ubuntu. Does not restart Nginx."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

UNSAFE = set(";&|`$<>\\\n\r")
MAGIC = b"SB01"
CHUNK = 1024 * 1024


def fail(message: str) -> None:
    json.dump({"ok": False, "error": message}, sys.stdout)
    sys.stdout.write("\n")
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def safe_unix(path: str) -> str:
    if not path or not path.startswith("/") or ".." in path or any(ch in path for ch in UNSAFE):
        fail(f"Refusing unsafe path: {path!r}")
    return path.rstrip("/") or "/"


def mysql_defaults() -> list[str]:
    cnf = Path("/etc/serverbackup/my.cnf")
    if cnf.is_file():
        return [f"--defaults-extra-file={cnf}"]
    return []


def safety_root() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path("/var/backups/serverbackup-safety") / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_tree(src: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dest, dirs_exist_ok=True)
    elif os.path.isfile(src):
        shutil.copy2(src, dest)


def nginx_test() -> None:
    nginx = shutil.which("nginx")
    if not nginx:
        fail("nginx binary not found")
    result = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        fail((result.stderr or result.stdout or "nginx -t failed").strip())


def _read_exact(handle, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = handle.read(min(CHUNK, remaining))
        if not chunk:
            fail("Unexpected end of restore pack")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def iter_pack(path: Path):
    with path.open("rb") as handle:
        magic = handle.read(len(MAGIC))
        if magic != MAGIC:
            fail("Invalid restore pack magic")
        while True:
            header = handle.read(4)
            if not header:
                return
            (path_len,) = struct.unpack(">I", header)
            if path_len == 0:
                return
            key = handle.read(path_len).decode("utf-8")
            (size,) = struct.unpack(">Q", handle.read(8))
            digest = handle.read(32).hex()
            yield key, size, digest, handle


def restore_database_bytes(name: str, payload: bytes) -> None:
    mysql = shutil.which("mysql")
    mysqldump = shutil.which("mysqldump")
    if not mysql or not mysqldump:
        fail("mysql/mysqldump not found")
    safety = safety_root() / f"{name}.sql.gz"
    dump = subprocess.run(
        [
            mysqldump,
            *mysql_defaults(),
            "--single-transaction",
            "--routines",
            "--triggers",
            "--events",
            "--databases",
            name,
        ],
        capture_output=True,
        check=False,
    )
    if dump.returncode == 0:
        with gzip.open(safety, "wb") as handle:
            handle.write(dump.stdout)
    sql = gzip.decompress(payload)
    restore = subprocess.run(
        [mysql, *mysql_defaults(), "--batch"],
        input=sql,
        capture_output=True,
        check=False,
    )
    if restore.returncode != 0:
        fail((restore.stderr or restore.stdout or b"mysql restore failed").decode("utf-8", "replace"))


def apply_pack(payload: dict) -> dict:
    pack_path = safe_unix(str(payload.get("pack_path") or ""))
    if not os.path.isfile(pack_path):
        fail(f"Restore pack not found: {pack_path}")
    create_safety = bool(payload.get("create_safety_copy", True))
    nginx_touched = False
    copied_roots: set[str] = set()
    safety = safety_root() if create_safety else None
    restored = 0
    with Path(pack_path).open("rb") as handle:
        magic = handle.read(len(MAGIC))
        if magic != MAGIC:
            fail("Invalid restore pack magic")
        while True:
            header = handle.read(4)
            if not header:
                break
            (path_len,) = struct.unpack(">I", header)
            if path_len == 0:
                break
            key = handle.read(path_len).decode("utf-8")
            (size,) = struct.unpack(">Q", handle.read(8))
            digest = handle.read(32).hex()
            if key.startswith("databases/") and key.endswith(".sql.gz"):
                payload_bytes = _read_exact(handle, size)
                actual = hashlib.sha256(payload_bytes).hexdigest()
                if actual != digest:
                    fail(f"Corrupt restore object for {key}")
                name = Path(key).name[: -len(".sql.gz")]
                restore_database_bytes(name, payload_bytes)
                restored += 1
                continue
            dest = safe_unix(key)
            if dest.startswith("/etc/nginx"):
                nginx_touched = True
            if safety is not None:
                parent = str(Path(dest).parent)
                for candidate in (dest, parent):
                    if os.path.exists(candidate) and candidate not in copied_roots:
                        copied_roots.add(candidate)
                        copy_tree(candidate, safety / Path(candidate).name)
                        break
            out = Path(dest)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".sbrestore")
            hasher = hashlib.sha256()
            remaining = size
            with tmp.open("wb") as dest_handle:
                while remaining > 0:
                    chunk = handle.read(min(CHUNK, remaining))
                    if not chunk:
                        tmp.unlink(missing_ok=True)
                        fail(f"Truncated restore pack for {key}")
                    dest_handle.write(chunk)
                    hasher.update(chunk)
                    remaining -= len(chunk)
            if hasher.hexdigest() != digest:
                tmp.unlink(missing_ok=True)
                fail(f"Corrupt restore object for {key}")
            os.replace(tmp, out)
            restored += 1
    if nginx_touched:
        nginx_test()
        # Intentionally do not reload or restart Nginx.
    return {
        "ok": True,
        "action": "restore-master",
        "restored": restored,
        "nginx_restarted": False,
        "message": "Restore completed. Nginx was not restarted.",
    }
