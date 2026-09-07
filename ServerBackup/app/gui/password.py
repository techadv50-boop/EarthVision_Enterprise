"""Ask for the Ubuntu SSH password in the GUI. It is never saved."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QLineEdit, QWidget


def prompt_ubuntu_password(parent: QWidget | None, username: str, server_ip: str) -> str | None:
    text, ok = QInputDialog.getText(
        parent,
        "Ubuntu password",
        f"Enter the SSH password for {username}@{server_ip}.\n\n"
        "This password is not saved on this Windows PC.",
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return None
    return text
