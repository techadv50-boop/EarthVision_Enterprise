"""Folder and SSH-key pickers used by first-run setup and Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

from app.utils.disk import backup_folder_for_drive
from app.utils.format import format_gb


def pick_existing_folder(parent: QWidget | None, current: str, title: str) -> str | None:
    start = current if Path(current).exists() else str(Path.home())
    chosen = QFileDialog.getExistingDirectory(parent, title, start)
    if not chosen:
        return None
    return str(Path(chosen))


def pick_backup_folder(parent: QWidget | None, current: str) -> str | None:
    chosen = pick_existing_folder(parent, current, "Select backup folder")
    if not chosen:
        return None
    path = Path(chosen)
    # A drive root such as G:\ becomes G:\ServerBackups.
    if path.parent == path or path.name.lower() in {"", "."}:
        return backup_folder_for_drive(path)
    return str(path)


def pick_ssh_key(parent: QWidget | None, current: str) -> str | None:
    start = current if Path(current).expanduser().exists() else str(Path.home() / ".ssh")
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select SSH private key",
        start,
        "All files (*.*)",
    )
    if not path:
        return None
    return path


def drive_label(path: str, free_bytes: int, total_bytes: int) -> str:
    free = format_gb(free_bytes) if total_bytes else "—"
    total = format_gb(total_bytes) if total_bytes else "—"
    return f"{path}    Free {free}    Total {total}"
