"""Host↔worker authentication (shared secret HMAC). Plugin IDs are not credentials."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any


class AuthError(RuntimeError):
    """Unauthorized worker request."""


def shared_secret() -> str:
    secret = (os.environ.get("EV_PLUGIN_WORKER_AUTH_TOKEN") or "").strip()
    if not secret or len(secret) < 32:
        raise AuthError(
            "EV_PLUGIN_WORKER_AUTH_TOKEN unset or too short (min 32 chars) — fail closed"
        )
    return secret


def require_bearer(authorization_header: str | None) -> None:
    """Validate Authorization: Bearer <shared token> (Host Shell identity)."""
    secret = shared_secret()
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthError("missing Authorization Bearer token")
    token = authorization_header[len("Bearer ") :].strip()
    if not hmac.compare_digest(token, secret):
        raise AuthError("invalid Authorization Bearer token")


def grant_message(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    exp: int,
) -> bytes:
    return f"v1|{request_id}|{plugin_id}|{version}|{digest}|{exp}".encode("utf-8")


def mint_grant(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    ttl_sec: int = 60,
) -> dict[str, Any]:
    secret = shared_secret()
    exp = int(time.time()) + int(ttl_sec)
    msg = grant_message(
        request_id=request_id,
        plugin_id=plugin_id,
        version=version,
        digest=digest,
        exp=exp,
    )
    mac = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return {"grant_exp": exp, "grant_mac": mac}


def verify_grant(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    grant_exp: Any,
    grant_mac: Any,
) -> None:
    secret = shared_secret()
    try:
        exp = int(grant_exp)
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid grant_exp") from exc
    if not isinstance(grant_mac, str) or len(grant_mac) < 32:
        raise AuthError("invalid grant_mac")
    now = int(time.time())
    if exp < now:
        raise AuthError("execution grant expired")
    if exp > now + 3600:
        raise AuthError("execution grant expiry too far in future")
    msg = grant_message(
        request_id=request_id,
        plugin_id=plugin_id,
        version=version,
        digest=digest,
        exp=exp,
    )
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, grant_mac):
        raise AuthError("execution grant MAC invalid")
