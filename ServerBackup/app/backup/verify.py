"""Archive integrity checks. A corrupt backup must never be marked SUCCESS."""

from __future__ import annotations

import tarfile
from pathlib import Path


class ArchiveIntegrityError(RuntimeError):
    pass


REQUIRED_PREFIXES = (
    "manifest.json",
    "databases/",
    "nginx/",
)


def verify_archive(
    archive_path: str | Path,
    *,
    website_directories: list[str] | None = None,
    ojs_private_files: str | None = None,
    nginx_directory: str | None = None,
    databases: list[str] | None = None,
    require_size: int | None = None,
) -> dict[str, object]:
    path = Path(archive_path)
    if not path.is_file():
        raise ArchiveIntegrityError(f"Backup archive is missing: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ArchiveIntegrityError("Backup archive is empty.")
    if require_size is not None and size < max(1, require_size // 100):
        raise ArchiveIntegrityError(
            f"Backup archive is unexpectedly small ({size} bytes)."
        )
    try:
        with tarfile.open(path, "r:*") as archive:
            names = archive.getnames()
    except tarfile.TarError as exc:
        raise ArchiveIntegrityError(f"Archive integrity check failed: {exc}") from exc
    if not names:
        raise ArchiveIntegrityError("Archive contains no files.")
    joined = "\n".join(names)
    if "manifest.json" not in names:
        raise ArchiveIntegrityError("Archive is missing manifest.json.")
    if nginx_directory and not any(n.startswith("nginx/") for n in names):
        raise ArchiveIntegrityError("Archive is missing nginx configuration.")
    if databases:
        for name in databases:
            expected = f"databases/{name}.sql.gz"
            if expected not in names and not any(
                n.startswith(f"databases/{name}") for n in names
            ):
                raise ArchiveIntegrityError(f"Archive is missing database dump for {name}.")
    if website_directories:
        for directory in website_directories:
            leaf = directory.rstrip("/").split("/")[-1]
            if leaf and leaf not in joined:
                raise ArchiveIntegrityError(
                    f"Archive is missing website files for {directory}."
                )
    if ojs_private_files:
        leaf = ojs_private_files.rstrip("/").split("/")[-1]
        if leaf and leaf not in joined:
            raise ArchiveIntegrityError(
                f"Archive is missing OJS private files for {ojs_private_files}."
            )
    return {"members": len(names), "size": size, "names": names}
