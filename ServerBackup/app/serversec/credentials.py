"""Rotate only credentials this application manages.

Never rotates MariaDB, OJS, website, PHP, SMTP, or API secrets.
Never stores old secrets in reports or logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config.store import config_dir
from app.security.redact import redact_secrets
from app.serversec.snapshot import SecurityStore
from app.utils.timeutil import backup_id_now

MANAGED_TARGET = "application-security-token"


def credentials_path() -> Path:
    return config_dir() / "security-credentials.json"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_credential_record() -> dict[str, Any]:
    path = credentials_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_credential_record(record: dict[str, Any]) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {k: v for k, v in record.items() if k not in {"token", "old_token", "new_token", "password"}}
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def proposed_rotation(current: dict[str, Any] | None = None) -> dict[str, Any]:
    current = current or load_credential_record()
    return {
        "target": MANAGED_TARGET,
        "action": "replace-application-security-token",
        "keeps_ssh_login": True,
        "keeps_mariadb": True,
        "keeps_ojs": True,
        "current_token_id": current.get("token_id") or "none",
        "lockout_protection": "Previous token hash is retained until the next successful security check verifies the new token.",
        "will_not_change": [
            "MariaDB passwords",
            "OJS passwords",
            "website application secrets",
            "PHP / SMTP / API credentials",
            "SSH server host keys",
            "existing authorized_keys entries",
        ],
    }


def rotate_local_token(store: SecurityStore, *, confirmation: str) -> dict[str, Any]:
    if confirmation.strip() != "ROTATE":
        raise ValueError('Type ROTATE to confirm credential rotation.')
    current = load_credential_record()
    new_token = secrets.token_urlsafe(32)
    new_id = backup_id_now()
    rollback_id = f"cred-{new_id}"
    store.save_rollback_point(
        {
            "id": rollback_id,
            "kind": "credential-rotation",
            "target": MANAGED_TARGET,
            "previous_token_id": current.get("token_id"),
            "previous_token_hash": current.get("token_hash"),
            "new_token_id": new_id,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
    )
    record = {
        "token_id": new_id,
        "token_hash": _hash_token(new_token),
        "previous_token_id": current.get("token_id"),
        "previous_token_hash": current.get("token_hash"),
        "created": datetime.now().isoformat(timespec="seconds"),
        "verified": False,
    }
    save_credential_record(record)
    # Return the new token once to the GUI. It is not written to logs or reports.
    return {
        "ok": True,
        "target": MANAGED_TARGET,
        "token_id": new_id,
        "new_token": new_token,
        "rollback_id": rollback_id,
        "message": redact_secrets(
            "Application security token rotated. SSH login and application passwords were not changed."
        ),
    }


def rollback_local_token(store: SecurityStore, rollback_id: str) -> dict[str, Any]:
    path = store.rollback / f"{rollback_id}.json"
    if not path.is_file():
        raise ValueError("Rollback point not found.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "credential-rotation":
        raise ValueError("Rollback point is not a credential rotation.")
    previous_hash = data.get("previous_token_hash")
    if not previous_hash:
        raise ValueError("No previous token hash is available; refusing a lockout rollback.")
    save_credential_record(
        {
            "token_id": data.get("previous_token_id") or "restored",
            "token_hash": previous_hash,
            "created": datetime.now().isoformat(timespec="seconds"),
            "verified": True,
            "restored_from": rollback_id,
        }
    )
    return {"ok": True, "message": "Application security token pointer restored from rollback hash. Plaintext secrets were never stored."}


def mark_token_verified() -> None:
    record = load_credential_record()
    if not record:
        return
    record["verified"] = True
    record.pop("previous_token_hash", None)
    record.pop("previous_token_id", None)
    save_credential_record(record)
