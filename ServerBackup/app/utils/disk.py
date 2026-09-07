"""Local disk space helpers. Never loads backup files into RAM."""

from __future__ import annotations

import os
import shutil
import string
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


def backup_folder_for_drive(root: str | Path) -> str:
    """Return G:\\ServerBackups when the user picks drive G:\\."""
    raw = str(root).strip()
    stripped = raw.rstrip("\\/")
    if len(stripped) == 2 and stripped[1] == ":":
        return stripped + "\\ServerBackups"
    path = Path(root)
    if path.name.lower() == "serverbackups":
        return str(path)
    return str(path / "ServerBackups")


def destination_drive_missing(path: str | Path) -> bool:
    """True when the Windows drive letter for the backup folder is missing."""
    target = Path(path)
    if os.name != "nt":
        return False
    anchor = target.anchor
    if not anchor:
        return True
    try:
        return not Path(anchor).exists()
    except OSError:
        return True


def needs_setup(config) -> bool:
    """Prompt for the backup drive until the user finishes first-run setup."""
    if not bool(getattr(config, "setup_completed", False)):
        return True
    return destination_drive_missing(getattr(config, "backup_destination", ""))


def list_backup_drives() -> list[DriveStatus]:
    """Candidate backup roots: Windows drive letters, or / on Linux."""
    roots: list[Path] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            candidate = Path(f"{letter}:\\")
            try:
                if candidate.exists():
                    roots.append(candidate)
            except OSError:
                continue
    else:
        roots.append(Path("/"))
        for extra in (Path("/mnt"), Path("/media")):
            try:
                if extra.exists():
                    roots.append(extra)
            except OSError:
                continue
    drives: list[DriveStatus] = []
    seen: set[str] = set()
    for root in roots:
        status = drive_status(root)
        key = status.path.rstrip("\\/").upper()
        if key in seen or not status.exists:
            continue
        seen.add(key)
        drives.append(status)
    return drives
