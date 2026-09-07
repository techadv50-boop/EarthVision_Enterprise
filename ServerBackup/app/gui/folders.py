"""Folder and SSH-key pickers used by first-run setup and Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget, QLineEdit

from app.ssh.keys import (
    KeyCreateError,
    create_ed25519_key,
    default_private_key_path,
    normalize_private_key_path,
    user_home,
)
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
    suggested = Path(normalize_private_key_path(current)) if current.strip() else default_private_key_path()
    start = str(suggested)
    if not suggested.exists():
        start = str(suggested.parent if suggested.parent.exists() else user_home())
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select SSH private key (not the .pub file)",
        start,
        "SSH private key (id_ed25519 id_rsa *);;All files (*.*)",
    )
    if not path:
        return None
    return normalize_private_key_path(path)


def create_and_fill_ssh_key(parent: QWidget | None, field: QLineEdit, username: str, server_ip: str) -> None:
    try:
        info = create_ed25519_key()
    except KeyCreateError as exc:
        QMessageBox.critical(parent, "Create SSH key", str(exc))
        return
    field.setText(str(info["private"]))
    user = (username or "zhzh").strip() or "zhzh"
    host = (server_ip or "192.168.18.18").strip() or "192.168.18.18"
    public = str(info["public"])
    created = "Created a new key" if info["created"] else "This key already exists"
    command = (
        f'type "{public}" | ssh {user}@{host} '
        '"mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"'
    )
    QMessageBox.information(
        parent,
        "SSH key",
        f"{created} on this Windows PC.\n\n"
        f"Private key (this app uses this file):\n{info['private']}\n\n"
        f"Public key (this file goes on Ubuntu user {user}):\n{public}\n\n"
        "There is no password box in this app. Run this once in Windows PowerShell. "
        "That command will ask for the Ubuntu password:\n\n"
        f"{command}",
    )


def drive_label(path: str, free_bytes: int, total_bytes: int) -> str:
    free = format_gb(free_bytes) if total_bytes else "—"
    total = format_gb(total_bytes) if total_bytes else "—"
    return f"{path}    Free {free}    Total {total}"
