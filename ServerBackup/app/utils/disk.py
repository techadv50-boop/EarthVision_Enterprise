"""Local disk space helpers. Never loads backup files into RAM."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DriveStatus:
    path: str
    exists: bool
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    error: str | None = None

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024**3)

    @property
    def free_gb(self) -> float:
        return self.free_bytes / (1024**3)


def _root_for(path: Path) -> Path:
    resolved = path
    try:
        resolved = path.expanduser()
        if resolved.exists():
            resolved = resolved.resolve()
    except OSError:
        pass
    anchor = resolved.anchor
    if anchor:
        return Path(anchor)
    return resolved if resolved.is_dir() else resolved.parent


def drive_status(path: str | Path) -> DriveStatus:
    target = Path(path)
    root = _root_for(target)
    if os.name == "nt":
        drive = Path(target.anchor or root)
        if not drive.exists():
            return DriveStatus(path=str(drive), exists=False, error=f"Drive unavailable: {drive}")
        probe = drive
    else:
        probe = root if root.exists() else Path("/")
        if not probe.exists():
            return DriveStatus(path=str(probe), exists=False, error=f"Path unavailable: {probe}")
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return DriveStatus(path=str(probe), exists=False, error=str(exc))
    used = usage.total - usage.free
    return DriveStatus(
        path=str(probe),
        exists=True,
        total_bytes=usage.total,
        used_bytes=used,
        free_bytes=usage.free,
    )


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
