"""Host Shell client for the restricted plugin worker (P2A).

Fail closed when worker isolation cannot be established or the worker is
unreachable. Never imports or execs plugin Python in-process.
"""

from __future__ import annotations

import json
import os
import secrets
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


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, *, timeout: float = 8.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc)}
        raise PackOpsError(f"plugin worker HTTP {exc.code}: {payload.get('error') or payload}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise PackOpsError(f"plugin worker unreachable or invalid response: {exc}") from exc


def check_isolation(*, require: bool | None = None) -> dict[str, Any]:
    """Probe worker /health and fail closed if isolation report is bad."""
    require = worker_required() if require is None else require
    url = worker_url()
    if not url:
        if require:
            raise PackOpsError(
                "plugin worker isolation cannot be established: EV_PLUGIN_WORKER_URL unset"
            )
        return {"ok": False, "skipped": True, "reason": "worker_url_unset"}
    report = _http_json("GET", f"{url}/health", timeout=3.0)
    isolation = report.get("isolation") or {}
    if not report.get("ok") or not isolation.get("isolated"):
        raise PackOpsError(
            "plugin worker isolation cannot be established: "
            f"{isolation.get('problems') or report}"
        )
    return report


def execute_plugin(
    *,
    plugin_id: str,
    version: str,
    digest: str,
    operation: str = "render",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute via worker only. Fail closed if worker/isolation unavailable when required."""
    url = worker_url()
    if not url:
        raise PackOpsError(
            "plugin worker required for execution but EV_PLUGIN_WORKER_URL is unset"
        )
    check_isolation(require=True)
    body = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "request_id": secrets.token_hex(16),
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "operation": operation,
        "payload": payload or {},
    }
    resp = _http_json("POST", f"{url}/v1/execute", body, timeout=10.0)
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
