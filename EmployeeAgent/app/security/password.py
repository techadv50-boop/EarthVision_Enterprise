"""Password hashing for the agent dashboard. Never store plaintext."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from app.constants import (
    PASSWORD_ITERATIONS,
    PASSWORD_KEY_BYTES,
    PASSWORD_SALT_BYTES,
    PASSWORD_SCHEME,
)


class PasswordError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str, *, iterations: int | None = None) -> str:
    if not password:
        raise PasswordError("Password must not be empty.")
    if iterations is None:
        env = os.environ.get("EMPLOYEE_AGENT_PBKDF2_ITERATIONS")
        iterations = int(env) if env else PASSWORD_ITERATIONS
    salt = os.urandom(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=PASSWORD_KEY_BYTES,
    )
    return f"{PASSWORD_SCHEME}${iterations}${_b64(salt)}${_b64(digest)}"


def password_is_hashed(stored: str) -> bool:
    if not stored or stored.count("$") != 3:
        return False
    scheme, _iters, _salt, _digest = stored.split("$", 3)
    return scheme == PASSWORD_SCHEME and bool(_salt) and bool(_digest)


def verify_password(password: str, stored: str) -> bool:
    if not password or not password_is_hashed(stored):
        return False
    try:
        _scheme, iter_s, salt_b64, digest_b64 = stored.split("$", 3)
        iterations = int(iter_s)
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
    except (ValueError, OSError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def random_setup_token() -> str:
    return secrets.token_urlsafe(16)
