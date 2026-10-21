"""Host↔worker authentication (shared secret HMAC + replay-resistant grants).

Plugin IDs / versions / digests are NOT credentials. TLS client certificates
(mTLS) are an additional transport control when EV_PLUGIN_WORKER_TLS=1.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Any

class AuthError(RuntimeError):
    """Unauthorized worker request."""


_REPLAY_LOCK = threading.Lock()
# grant_mac → expiry unix; entries removed after use or expiry
_CONSUMED_GRANTS: dict[str, int] = {}


def shared_secret() -> str:
    secret = (os.environ.get("EV_PLUGIN_WORKER_AUTH_TOKEN") or "").strip()
    if not secret or len(secret) < 32:
        raise AuthError(
            "EV_PLUGIN_WORKER_AUTH_TOKEN unset or too short (min 32 chars) — fail closed"
        )
    # Reject well-known preview defaults in production-like profiles
    banned = {
        "preview-plugin-worker-auth-token-32b!!",
        "changeme-plugin-worker-auth-token!!!!",
    }
    profile = (os.environ.get("EV_PACK_TRUST_PROFILE") or "production").strip().lower()
    if profile == "production" and secret in banned:
        raise AuthError("default/preview worker auth token forbidden in production trust profile")
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
    nonce: str,
) -> bytes:
    return f"v2|{request_id}|{plugin_id}|{version}|{digest}|{exp}|{nonce}".encode("utf-8")


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
    nonce = secrets.token_hex(16)
    msg = grant_message(
        request_id=request_id,
        plugin_id=plugin_id,
        version=version,
        digest=digest,
        exp=exp,
        nonce=nonce,
    )
    mac = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return {"grant_exp": exp, "grant_mac": mac, "grant_nonce": nonce}


def _purge_expired_locked(now: int) -> None:
    dead = [k for k, exp in _CONSUMED_GRANTS.items() if exp < now]
    for k in dead:
        _CONSUMED_GRANTS.pop(k, None)


def verify_grant(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    grant_exp: Any,
    grant_mac: Any,
    grant_nonce: Any = None,
) -> None:
    secret = shared_secret()
    try:
        exp = int(grant_exp)
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid grant_exp") from exc
    if not isinstance(grant_mac, str) or len(grant_mac) < 32:
        raise AuthError("invalid grant_mac")
    if not isinstance(grant_nonce, str) or len(grant_nonce) < 16:
        raise AuthError("missing or invalid grant_nonce (replay-resistant grants required)")
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
        nonce=grant_nonce,
    )
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, grant_mac):
        raise AuthError("execution grant MAC invalid")

    # Single-use: reject replay of the same MAC
    with _REPLAY_LOCK:
        _purge_expired_locked(now)
        if grant_mac in _CONSUMED_GRANTS:
            raise AuthError("execution grant replay rejected")
        _CONSUMED_GRANTS[grant_mac] = exp
