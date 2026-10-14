"""Host Shell client for the restricted plugin worker (P2A.1).

Authenticated Host→worker communication via shared Bearer token + HMAC grant.
Plugin id/version/digest are never treated as authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any

from app.tools.pack_ops import PackOpsError

CONTRACT_SCHEMA_VERSION = 1


def worker_url() -> str | None:
    url = (os.environ.get("EV_PLUGIN_WORKER_URL") or "").strip().rstrip("/")
    return url or None


def worker_required() -> bool:
    return os.environ.get("EV_PLUGIN_WORKER_REQUIRED", "0") == "1"


def _auth_token() -> str:
    token = (os.environ.get("EV_PLUGIN_WORKER_AUTH_TOKEN") or "").strip()
    if not token or len(token) < 32:
        raise PackOpsError(
            "EV_PLUGIN_WORKER_AUTH_TOKEN unset or too short — cannot authenticate to worker"
        )
    return token


def _mint_grant(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    ttl_sec: int = 60,
) -> dict[str, Any]:
    secret = _auth_token()
    exp = int(time.time()) + ttl_sec
    msg = f"v1|{request_id}|{plugin_id}|{version}|{digest}|{exp}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return {"grant_exp": exp, "grant_mac": mac}


def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 8.0,
    auth: bool = False,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {_auth_token()}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc)}
        raise PackOpsError(
            f"plugin worker HTTP {exc.code}: {payload.get('error') or payload}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise PackOpsError(f"plugin worker unreachable or invalid response: {exc}") from exc


def check_isolation(*, require: bool | None = None) -> dict[str, Any]:
    require = worker_required() if require is None else require
    url = worker_url()
    if not url:
        if require:
            raise PackOpsError(
                "plugin worker isolation cannot be established: EV_PLUGIN_WORKER_URL unset"
            )
        return {"ok": False, "skipped": True, "reason": "worker_url_unset"}
    report = _http_json("GET", f"{url}/health", timeout=3.0, auth=False)
    isolation = report.get("isolation") or {}
    if not report.get("ok") or not isolation.get("isolated"):
        raise PackOpsError(
            "plugin worker isolation cannot be established: "
            f"{isolation.get('problems') or report}"
        )
    if not isolation.get("auth_configured"):
        raise PackOpsError("plugin worker auth not configured")
    return report


def execute_plugin(
    *,
    plugin_id: str,
    version: str,
    digest: str,
    operation: str = "render",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = worker_url()
    if not url:
        raise PackOpsError(
            "plugin worker required for execution but EV_PLUGIN_WORKER_URL is unset"
        )
    check_isolation(require=True)
    request_id = secrets.token_hex(16)
    grant = _mint_grant(
        request_id=request_id,
        plugin_id=plugin_id,
        version=version,
        digest=digest,
    )
    body = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "request_id": request_id,
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "operation": operation,
        "payload": payload or {},
        **grant,
    }
    resp = _http_json("POST", f"{url}/v1/execute", body, timeout=15.0, auth=True)
    if not resp.get("ok"):
        raise PackOpsError(resp.get("error") or "plugin worker rejected execution")
    if resp.get("digest") != digest or resp.get("plugin_id") != plugin_id:
        raise PackOpsError("plugin worker response identity mismatch")
    result = resp.get("result")
    if not isinstance(result, dict):
        raise PackOpsError("plugin worker returned invalid result")
    return {
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "execution_model": "restricted_worker",
        "request_id": resp.get("request_id"),
        "payload": result,
    }
