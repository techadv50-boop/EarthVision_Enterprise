"""Restore a master generation by packing objects and applying them on Ubuntu.

Does not restart Nginx. Safety copies are created on the server first.
"""

from __future__ import annotations

import gzip
import hashlib
import struct
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from app.master.objects import object_path
from app.master.pack import MAGIC, CHUNK
from app.master.store import MasterStore
from app.master.tree import index_active

CATEGORY_WEBSITE = "website"
CATEGORY_OJS = "ojs"
CATEGORY_NGINX = "nginx"
CATEGORY_EXTRA = "extra"


def select_tree_files(
    tree: dict[str, Any],
    *,
    kind: str,
    target_path: str | None = None,
) -> list[dict[str, Any]]:
    files = list(index_active(tree).values())
    if kind == "restore-complete":
        return files
    if kind == "restore-files":
        if target_path:
            wanted = target_path.rstrip("/")
            return [item for item in files if str(item.get("source_root") or "").rstrip("/") == wanted]
        return [
            item
            for item in files
            if str(item.get("category") or "") in {CATEGORY_WEBSITE, CATEGORY_OJS, CATEGORY_EXTRA}
        ]
    if kind == "restore-nginx":
        return [item for item in files if str(item.get("category") or "") == CATEGORY_NGINX]
    if kind == "restore-database":
        return []
    return files


def destination_path(record: dict[str, Any]) -> str:
    root = str(record.get("source_root") or "").rstrip("/")
    rel = str(record.get("relative_path") or "").lstrip("/")
    if rel in {"", "."}:
        return root
    return f"{root}/{rel}"


def write_restore_pack(store: MasterStore, records: Iterable[dict[str, Any]], dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open("wb") as stream:
        stream.write(MAGIC)
        for record in records:
            digest = str(record.get("sha256") or "")
            key = destination_path(record)
            source = object_path(store.objects_root, digest)
            if not source.is_file():
                raise FileNotFoundError(f"Missing object {digest} for {key}")
            size = source.stat().st_size
            encoded = key.encode("utf-8")
            stream.write(struct.pack(">I", len(encoded)))
            stream.write(encoded)
            stream.write(struct.pack(">Q", int(size)))
            stream.write(bytes.fromhex(digest))
            with source.open("rb") as handle:
                while True:
                    chunk = handle.read(CHUNK)
                    if not chunk:
                        break
                    stream.write(chunk)
                    written += len(chunk)
        stream.write(struct.pack(">I", 0))
    return written


def write_database_pack(store: MasterStore, tree: dict[str, Any], names: list[str], dest: Path) -> int:
    objects = tree.get("database_objects") or {}
    records = []
    for name in names:
        digest = objects.get(name)
        if not digest:
            raise FileNotFoundError(f"No database object for {name} in this generation.")
        records.append(
            {
                "sha256": digest,
                "source_root": "databases",
                "relative_path": f"{name}.sql.gz",
            }
        )
    return write_restore_pack(store, records, dest)


def append_database_records(stream: BinaryIO, store: MasterStore, tree: dict[str, Any], names: list[str]) -> None:
    objects = tree.get("database_objects") or {}
    for name in names:
        digest = str(objects.get(name) or "")
        if not digest:
            raise FileNotFoundError(f"No database object for {name} in this generation.")
        key = f"databases/{name}.sql.gz"
        source = object_path(store.objects_root, digest)
        size = source.stat().st_size
        encoded = key.encode("utf-8")
        stream.write(struct.pack(">I", len(encoded)))
        stream.write(encoded)
        stream.write(struct.pack(">Q", int(size)))
        stream.write(bytes.fromhex(digest))
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                stream.write(chunk)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def gunzip_bytes(data: bytes) -> bytes:
    return gzip.decompress(data)
