"""Binary object stream used by stream-objects. Bounded memory; one file at a time."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

MAGIC = b"SB01"
CHUNK = 1024 * 1024


def write_begin(stream: BinaryIO) -> None:
    stream.write(MAGIC)


def write_file(stream: BinaryIO, key: str, data_iter: Iterator[bytes], size: int, digest: str) -> None:
    encoded = key.encode("utf-8")
    stream.write(struct.pack(">I", len(encoded)))
    stream.write(encoded)
    stream.write(struct.pack(">Q", int(size)))
    stream.write(bytes.fromhex(digest))
    written = 0
    for chunk in data_iter:
        stream.write(chunk)
        written += len(chunk)
    if written != size:
        raise ValueError(f"Pack size mismatch for {key}: {written} != {size}")


def write_end(stream: BinaryIO) -> None:
    stream.write(struct.pack(">I", 0))


def iter_file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                return
            yield chunk


def hash_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_records(stream: BinaryIO) -> Iterator[tuple[str, int, str, bytes]]:
    """Yield (key, size, sha256, payload). Payload is returned whole; caller should use read_to_path for large files."""
    magic = stream.read(len(MAGIC))
    if magic != MAGIC:
        raise ValueError("Invalid object stream magic.")
    while True:
        header = stream.read(4)
        if not header:
            return
        (path_len,) = struct.unpack(">I", header)
        if path_len == 0:
            return
        key = stream.read(path_len).decode("utf-8")
        (size,) = struct.unpack(">Q", stream.read(8))
        digest = stream.read(32).hex()
        payload = _read_exact(stream, size)
        yield key, size, digest, payload


def read_to_path(stream: BinaryIO, destination: Path) -> tuple[str, int, str]:
    """Read one record from an already-opened stream positioned at a record. Not used with magic."""
    raise NotImplementedError


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(min(CHUNK, remaining))
        if not chunk:
            raise ValueError("Unexpected end of object stream.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def unpack_to_objects(
    stream: BinaryIO,
    objects_root: Path,
    write_object,
    *,
    should_cancel=None,
) -> list[dict[str, str | int]]:
    magic = stream.read(len(MAGIC))
    if magic != MAGIC:
        raise ValueError("Invalid object stream magic.")
    stored: list[dict[str, str | int]] = []
    while True:
        if should_cancel is not None and should_cancel():
            raise ValueError("Object stream cancelled.")
        header = stream.read(4)
        if not header:
            break
        if len(header) < 4:
            raise ValueError("Interrupted object stream (truncated header).")
        (path_len,) = struct.unpack(">I", header)
        if path_len == 0:
            break
        key_bytes = stream.read(path_len)
        if len(key_bytes) < path_len:
            raise ValueError(f"Interrupted object stream (truncated path).")
        key = key_bytes.decode("utf-8")
        size_bytes = stream.read(8)
        if len(size_bytes) < 8:
            raise ValueError(f"Interrupted object stream for {key}")
        (size,) = struct.unpack(">Q", size_bytes)
        digest_bytes = stream.read(32)
        if len(digest_bytes) < 32:
            raise ValueError(f"Interrupted object stream for {key}")
        digest = digest_bytes.hex()
        tmp = Path(objects_root) / ".incoming.tmp"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        remaining = size
        with tmp.open("wb") as handle:
            while remaining > 0:
                chunk = stream.read(min(CHUNK, remaining))
                if not chunk:
                    tmp.unlink(missing_ok=True)
                    raise ValueError(f"Truncated object stream for {key}")
                handle.write(chunk)
                hasher.update(chunk)
                remaining -= len(chunk)
        actual = hasher.hexdigest()
        if digest != actual:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Corrupt object for {key}: {digest} != {actual}")
        write_object(tmp, expected=actual)
        tmp.unlink(missing_ok=True)
        stored.append({"key": key, "sha256": actual, "size": size})
    return stored
