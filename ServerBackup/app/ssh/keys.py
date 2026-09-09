"""Create and locate the local OpenSSH private key. Never stores Ubuntu passwords."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class KeyCreateError(RuntimeError):
    pass


def user_home() -> Path:
    for key in ("USERPROFILE", "HOME"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return Path.home()


def default_private_key_path() -> Path:
    return user_home() / ".ssh" / "id_ed25519"


def default_public_key_path(private: Path | None = None) -> Path:
    path = private or default_private_key_path()
    return Path(str(path) + ".pub")


def normalize_private_key_path(path: str) -> str:
    """If the user picked a .pub file, use the matching private key when it exists."""
    text = (path or "").strip()
    if not text:
        return text
    candidate = Path(os.path.expandvars(os.path.expanduser(text)))
    as_text = str(candidate)
    if as_text.endswith(".pub"):
        private = Path(as_text[:-4])
        if private.is_file():
            return str(private)
    return str(candidate)


def create_ed25519_key(path: Path | None = None) -> dict[str, str | bool]:
    """Create id_ed25519 if missing. Returns paths; does not contact Ubuntu."""
    private = Path(path) if path is not None else default_private_key_path()
    public = default_public_key_path(private)
    private.parent.mkdir(parents=True, exist_ok=True)
    if private.is_file():
        return {
            "private": str(private),
            "public": str(public),
            "created": False,
            "public_text": public.read_text(encoding="utf-8").strip() if public.is_file() else "",
        }
    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise KeyCreateError(
            "OpenSSH ssh-keygen was not found. In Windows: Settings → Apps → Optional features → OpenSSH Client."
        )
    try:
        completed = subprocess.run(
            [ssh_keygen, "-t", "ed25519", "-f", str(private), "-N", "", "-C", "serverbackup"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError as exc:
        raise KeyCreateError(f"Could not run ssh-keygen: {exc}") from exc
    if completed.returncode != 0 or not private.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise KeyCreateError(detail or "ssh-keygen failed.")
    return {
        "private": str(private),
        "public": str(public),
        "created": True,
        "public_text": public.read_text(encoding="utf-8").strip() if public.is_file() else "",
    }
