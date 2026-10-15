"""Typed request/response contract for the restricted plugin worker (P2A.1)."""

from __future__ import annotations

from typing import Any

CONTRACT_SCHEMA_VERSION = 1
SUPPORTED_OPERATIONS = frozenset({"render", "ping"})


class ContractError(ValueError):
    """Invalid worker request or response."""


def validate_request(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("request must be a JSON object")
    if data.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ContractError("unsupported request schema_version")
    plugin_id = data.get("plugin_id")
    version = data.get("version")
    digest = data.get("digest")
    operation = data.get("operation")
    request_id = data.get("request_id")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ContractError("plugin_id required")
    if not isinstance(version, str) or not version:
        raise ContractError("version required")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ContractError("digest must be sha256:...")
    if operation not in SUPPORTED_OPERATIONS:
        raise ContractError(f"unsupported operation: {operation!r}")
    if not isinstance(request_id, str) or not request_id:
        raise ContractError("request_id required")
    payload = data.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "request_id": request_id,
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "operation": operation,
        "payload": payload,
        "grant_exp": data.get("grant_exp"),
        "grant_mac": data.get("grant_mac"),
        "grant_nonce": data.get("grant_nonce"),
    }


def make_response(
    *,
    request_id: str,
    plugin_id: str,
    version: str,
    digest: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ContractError("result must be an object")
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "ok": True,
        "request_id": request_id,
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "result": result,
    }


def make_error(*, request_id: str | None, error: str, code: str = "worker_error") -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "ok": False,
        "request_id": request_id,
        "error": error,
        "code": code,
    }
