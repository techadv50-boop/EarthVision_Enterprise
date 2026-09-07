"""Never log passwords, private keys, or secret tokens."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "privatekey",
    "ssh_private_key",
    "mysql_password",
    "mariadb_password",
    "passphrase",
    "credential",
    "api_key",
}

_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|passphrase)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----.*?-----END[A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(identityfile|identity_file)\s+[^\s]+"),
]


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        lowered = str(key).lower().replace("-", "_")
        if lowered in _SECRET_KEYS or "password" in lowered or "private_key" in lowered:
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = redact_mapping(value)
        elif isinstance(value, str):
            out[key] = redact_secrets(value)
        else:
            out[key] = value
    return out
